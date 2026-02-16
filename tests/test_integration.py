"""Integration tests — full sync -> diff -> apply -> backup -> restore round-trip.

Uses real git repos (temp directories) and a mock DSF connection to exercise
the complete flow across ConfigManager and git_utils."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from config_manager import ConfigManager


@pytest.fixture
def reference_repo(tmp_path):
    """Create a bare reference repo with branches and config files."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "receive.denyCurrentBranch", "ignore"],
        cwd=str(bare), check=True, capture_output=True,
    )

    clone_dir = tmp_path / "ref_setup"
    subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)

    # Create sys/ and macros/ with config files
    sys_dir = clone_dir / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\nM906 X800 Y800\n")
    (sys_dir / "homex.g").write_text("G91\nG1 H1 X-300 F3000\n")

    macros_dir = clone_dir / "macros"
    macros_dir.mkdir()
    (macros_dir / "print_start.g").write_text("T0\nM116\n")

    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial config"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    # Create a 3.5 branch with different config
    subprocess.run(["git", "checkout", "-b", "3.5"], cwd=str(clone_dir), check=True, capture_output=True)
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\nM906 X1000 Y1000\n")
    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "version 3.5 - higher current"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "3.5"], cwd=str(clone_dir), check=True, capture_output=True)

    return str(bare)


@pytest.fixture
def printer_files():
    """Simulated printer filesystem as a dict."""
    return {
        "0:/sys/config.g": "G28\nM584 X0 Y1\nM906 X800 Y800\n",
        "0:/sys/homex.g": "G91\nG1 H1 X-300 F3000\n",
        "0:/macros/print_start.g": "T0\nM116\n",
    }


@pytest.fixture
def mock_dsf(printer_files):
    """Mock DSF connection backed by the printer_files dict."""
    dsf = MagicMock()

    def get_file(path):
        return printer_files.get(path)

    def put_file(path, content):
        printer_files[path] = content

    dsf.get_file.side_effect = get_file
    dsf.put_file.side_effect = put_file
    return dsf


@pytest.fixture
def integration_env(tmp_path, reference_repo, mock_dsf):
    """Set up complete integration environment with patched paths."""
    ref_dir = str(tmp_path / "reference")
    backup_dir = str(tmp_path / "backups")

    with (
        patch("config_manager.REFERENCE_DIR", ref_dir),
        patch("config_manager.BACKUP_DIR", backup_dir),
        patch("config_manager.PLUGIN_DIR", str(tmp_path)),
    ):
        manager = ConfigManager(dsf_command_connection=mock_dsf)
        yield {
            "manager": manager,
            "ref_dir": ref_dir,
            "backup_dir": backup_dir,
            "repo_url": reference_repo,
            "dsf": mock_dsf,
        }


class TestSyncDiffApplyRoundTrip:
    def test_sync_then_diff_shows_no_changes(self, integration_env):
        """After syncing main, printer files match reference → no changes."""
        env = integration_env
        result = env["manager"].sync(env["repo_url"], "1.0")  # Falls back to main
        assert "error" not in result
        assert result["activeBranch"] == "main"

        diff = env["manager"].diff_all()
        for f in diff:
            assert f["status"] == "unchanged", f"Expected {f['file']} unchanged"

    def test_sync_different_branch_shows_diff(self, integration_env, printer_files):
        """Syncing to 3.5 branch shows modified config.g (different motor currents)."""
        env = integration_env
        result = env["manager"].sync(env["repo_url"], "3.5")
        assert result["activeBranch"] == "3.5"
        assert result["exact"] is True

        diff = env["manager"].diff_all()
        statuses = {f["file"]: f["status"] for f in diff}
        assert statuses["sys/config.g"] == "modified"
        # homex.g and print_start.g unchanged on 3.5
        assert statuses.get("sys/homex.g") == "unchanged"
        assert statuses.get("macros/print_start.g") == "unchanged"

    def test_apply_all_updates_printer(self, integration_env, printer_files):
        """apply_all should update printer files to match reference."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        result = env["manager"].apply_all()
        assert "error" not in result
        assert "sys/config.g" in result["applied"]

        # Printer should now have 3.5 content
        assert "M906 X1000 Y1000" in printer_files["0:/sys/config.g"]

    def test_apply_all_then_diff_shows_no_changes(self, integration_env, printer_files):
        """After applying all, diff should show no changes."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        diff = env["manager"].diff_all()
        for f in diff:
            assert f["status"] == "unchanged", f"Expected {f['file']} unchanged after apply"

    def test_apply_hunks_partial(self, integration_env, printer_files):
        """Apply only selected hunks from a file."""
        env = integration_env
        # Modify printer config to have multiple differences
        printer_files["0:/sys/config.g"] = "G28\nM584 X0 Y1\nM906 X800 Y800\n"
        env["manager"].sync(env["repo_url"], "3.5")

        # Get hunks for the file
        diff = env["manager"].diff_file("sys/config.g")
        assert diff["status"] == "modified"
        assert len(diff["hunks"]) > 0

        # Apply first hunk only
        result = env["manager"].apply_hunks("sys/config.g", [0])
        assert len(result["applied"]) > 0

    def test_backup_created_on_apply(self, integration_env, printer_files):
        """Applying changes should create backup entries."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        assert len(backups) >= 2  # Pre-update + post-update

    def test_restore_backup_reverts_changes(self, integration_env, printer_files):
        """Restore should revert printer to backup state."""
        env = integration_env
        original_config = printer_files["0:/sys/config.g"]

        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()
        assert printer_files["0:/sys/config.g"] != original_config

        # Get pre-update backup (the first one created)
        backups = env["manager"].get_backups()
        # Find the pre-update backup (it has the original content)
        pre_update = [b for b in backups if "Pre-update" in b["message"]]
        assert len(pre_update) > 0

        # Restore from that backup
        env["manager"].restore_backup(pre_update[0]["hash"])
        # git show strips trailing newline, so compare without it
        assert printer_files["0:/sys/config.g"].rstrip("\n") == original_config.rstrip("\n")

    def test_diff_file_detail(self, integration_env, printer_files):
        """diff_file should return detailed hunks with unified diff."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        detail = env["manager"].diff_file("sys/config.g")
        assert detail["status"] == "modified"
        assert len(detail["hunks"]) > 0
        assert detail["unifiedDiff"] != ""
        # Each hunk should have required fields
        for hunk in detail["hunks"]:
            assert "index" in hunk
            assert "header" in hunk
            assert "lines" in hunk
            assert "summary" in hunk

    def test_get_branches_after_sync(self, integration_env):
        """After sync, available branches should be listed."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        branches = env["manager"].get_branches()
        assert "main" in branches
        assert "3.5" in branches

    def test_missing_printer_file(self, integration_env, printer_files):
        """When a printer file doesn't exist, diff should show 'missing'."""
        env = integration_env
        del printer_files["0:/sys/homex.g"]

        env["manager"].sync(env["repo_url"], "3.5")
        diff = env["manager"].diff_all()
        statuses = {f["file"]: f["status"] for f in diff}
        assert statuses["sys/homex.g"] == "missing"

    def test_apply_file_single(self, integration_env, printer_files):
        """apply_file should update only the specified file."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        original_homex = printer_files["0:/sys/homex.g"]
        result = env["manager"].apply_file("sys/config.g")
        assert result == {"applied": ["sys/config.g"]}
        assert "M906 X1000" in printer_files["0:/sys/config.g"]
        assert printer_files["0:/sys/homex.g"] == original_homex

    def test_backup_download_is_zip(self, integration_env, printer_files):
        """Backup download should return valid ZIP bytes."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        assert len(backups) > 0

        archive = env["manager"].get_backup_download(backups[0]["hash"])
        assert archive[:2] == b"PK"

    def test_backup_files_lists_contents(self, integration_env, printer_files):
        """get_backup_files should list files in a backup commit."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        files = env["manager"].get_backup_files(backups[0]["hash"])
        assert "sys/config.g" in files
