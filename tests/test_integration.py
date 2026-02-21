"""Integration tests — full sync -> diff -> apply -> backup -> restore round-trip.

Uses real git repos (temp directories) and a real temp filesystem to exercise
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
def printer_fs(tmp_path):
    """Create a temp printer filesystem with initial config files."""
    root = tmp_path / "printer_sd"
    root.mkdir()

    sys_dir = root / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\nM906 X800 Y800\n")
    (sys_dir / "homex.g").write_text("G91\nG1 H1 X-300 F3000\n")

    macros_dir = root / "macros"
    macros_dir.mkdir()
    (macros_dir / "print_start.g").write_text("T0\nM116\n")

    filaments_dir = root / "filaments"
    filaments_dir.mkdir()

    return root


@pytest.fixture
def integration_env(tmp_path, reference_repo, printer_fs):
    """Set up complete integration environment with patched paths."""
    ref_dir = str(tmp_path / "reference")
    backup_dir = str(tmp_path / "backups")

    resolved = {
        "0:/sys/": str(printer_fs / "sys") + "/",
        "0:/macros/": str(printer_fs / "macros") + "/",
        "0:/filaments/": str(printer_fs / "filaments") + "/",
    }

    with (
        patch("config_manager.REFERENCE_DIR", ref_dir),
        patch("config_manager.BACKUP_DIR", backup_dir),
    ):
        manager = ConfigManager(
            dsf_command_connection=MagicMock(),
            resolved_dirs=resolved,
        )
        yield {
            "manager": manager,
            "ref_dir": ref_dir,
            "backup_dir": backup_dir,
            "repo_url": reference_repo,
            "printer_fs": printer_fs,
        }


def _read_printer(printer_fs, rel_path):
    """Read a file from the printer filesystem."""
    return (printer_fs / rel_path).read_text()


class TestSyncDiffApplyRoundTrip:
    def test_sync_then_diff_shows_no_changes(self, integration_env):
        """After syncing main, printer files match reference -> no changes."""
        env = integration_env
        result = env["manager"].sync(env["repo_url"], "1.0")  # Falls back to main
        assert "error" not in result
        assert result["activeBranch"] == "main"

        diff = env["manager"].diff_all()
        for f in diff:
            assert f["status"] == "unchanged", f"Expected {f['file']} unchanged"

    def test_sync_different_branch_shows_diff(self, integration_env):
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

    def test_apply_all_updates_printer(self, integration_env):
        """apply_all should update printer files to match reference."""
        env = integration_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "3.5")
        result = env["manager"].apply_all()
        assert "error" not in result
        assert "sys/config.g" in result["applied"]

        # Printer should now have 3.5 content
        assert "M906 X1000 Y1000" in _read_printer(pfs, "sys/config.g")

    def test_apply_all_then_diff_shows_no_changes(self, integration_env):
        """After applying all, diff should show no changes."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        diff = env["manager"].diff_all()
        for f in diff:
            assert f["status"] == "unchanged", f"Expected {f['file']} unchanged after apply"

    def test_apply_hunks_partial(self, integration_env):
        """Apply only selected hunks from a file."""
        env = integration_env
        pfs = env["printer_fs"]
        # Ensure printer has main content
        (pfs / "sys" / "config.g").write_text("G28\nM584 X0 Y1\nM906 X800 Y800\n")
        env["manager"].sync(env["repo_url"], "3.5")

        # Get hunks for the file
        diff = env["manager"].diff_file("sys/config.g")
        assert diff["status"] == "modified"
        assert len(diff["hunks"]) > 0

        # Apply first hunk only
        result = env["manager"].apply_hunks("sys/config.g", [0])
        assert len(result["applied"]) > 0

    def test_backup_created_on_apply(self, integration_env):
        """Applying changes should create backup entries."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        assert len(backups) >= 2  # Pre-update + post-update

    def test_restore_backup_reverts_changes(self, integration_env):
        """Restore should revert printer to backup state."""
        env = integration_env
        pfs = env["printer_fs"]
        original_config = _read_printer(pfs, "sys/config.g")

        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()
        assert _read_printer(pfs, "sys/config.g") != original_config

        # Get pre-update backup (the first one created)
        backups = env["manager"].get_backups()
        # Find the pre-update backup (it has the original content)
        pre_update = [b for b in backups if "Pre-update" in b["message"]]
        assert len(pre_update) > 0

        # Restore from that backup
        env["manager"].restore_backup(pre_update[0]["hash"])
        # git show strips trailing newline, so compare without it
        assert _read_printer(pfs, "sys/config.g").rstrip("\n") == original_config.rstrip("\n")

    def test_diff_file_detail(self, integration_env):
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

    def test_missing_printer_file(self, integration_env):
        """When a printer file doesn't exist, diff should show 'missing'."""
        env = integration_env
        pfs = env["printer_fs"]
        # Delete the printer file
        (pfs / "sys" / "homex.g").unlink()

        env["manager"].sync(env["repo_url"], "3.5")
        diff = env["manager"].diff_all()
        statuses = {f["file"]: f["status"] for f in diff}
        assert statuses["sys/homex.g"] == "missing"

    def test_apply_file_single(self, integration_env):
        """apply_file should update only the specified file."""
        env = integration_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "3.5")

        original_homex = _read_printer(pfs, "sys/homex.g")
        result = env["manager"].apply_file("sys/config.g")
        assert result == {"applied": ["sys/config.g"]}
        assert "M906 X1000" in _read_printer(pfs, "sys/config.g")
        assert _read_printer(pfs, "sys/homex.g") == original_homex

    def test_backup_download_is_zip(self, integration_env):
        """Backup download should return valid ZIP bytes."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        assert len(backups) > 0

        archive = env["manager"].get_backup_download(backups[0]["hash"])
        assert archive[:2] == b"PK"

    def test_backup_files_lists_contents(self, integration_env):
        """get_backup_files should list files in a backup commit."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        files = env["manager"].get_backup_files(backups[0]["hash"])
        assert "sys/config.g" in files


class TestManualBackup:
    def test_manual_backup_creates_entry(self, integration_env):
        """Manual backup should create a new backup commit."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        result = env["manager"].create_manual_backup()
        assert "error" not in result
        assert result["backup"] is not None
        assert "Manual backup" in result["backup"]["message"]

    def test_manual_backup_with_custom_message(self, integration_env):
        """Manual backup with a custom message should use that message."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        result = env["manager"].create_manual_backup("Before firmware update")
        assert "error" not in result
        assert "Before firmware update" in result["backup"]["message"]

    def test_manual_backup_without_reference_repo(self, integration_env):
        """Manual backup works without a cloned reference repo — backups
        are independent, tracking the printer filesystem via the worktree."""
        env = integration_env
        # Don't sync — no reference repo, but backup still works
        result = env["manager"].create_manual_backup()
        assert "error" not in result
        assert result["backup"] is not None

    def test_manual_backup_appears_in_history(self, integration_env):
        """Manual backup should appear in backup history."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        env["manager"].create_manual_backup("Test snapshot")
        backups = env["manager"].get_backups()
        messages = [b["message"] for b in backups]
        assert any("Test snapshot" in m for m in messages)

    def test_manual_backup_is_downloadable(self, integration_env):
        """Manual backup should be downloadable as a ZIP."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")

        result = env["manager"].create_manual_backup()
        backup_hash = result["backup"]["hash"]
        archive = env["manager"].get_backup_download(backup_hash)
        assert archive[:2] == b"PK"


class TestGcodeExclusion:
    def test_gcodes_excluded_from_backup(self, integration_env):
        """Gcode files should not appear in backups — only BACKUP_INCLUDED_DIRS
        (sys/, macros/, filaments/) are staged via the worktree."""
        env = integration_env
        pfs = env["printer_fs"]

        # Create gcodes directory on the printer filesystem
        gcodes_printer = pfs / "gcodes"
        gcodes_printer.mkdir(exist_ok=True)
        (gcodes_printer / "test.gcode").write_text("G28\nG1 X100\n")

        # Create a manual backup (no sync needed — backups are independent)
        result = env["manager"].create_manual_backup("test gcode exclusion")
        assert "error" not in result
        backup_hash = result["backup"]["hash"]

        # Verify gcode files are NOT in the backup
        files = env["manager"].get_backup_files(backup_hash)
        gcode_files = [f for f in files if f.startswith("gcodes/")]
        assert len(gcode_files) == 0

        # But config files should still be there
        assert "sys/config.g" in files


# --- Special character file path tests ---


@pytest.fixture
def special_char_repo(tmp_path):
    """Create a reference repo with files containing special characters in names."""
    bare = tmp_path / "special_bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "receive.denyCurrentBranch", "ignore"],
        cwd=str(bare), check=True, capture_output=True,
    )

    clone_dir = tmp_path / "special_setup"
    subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)

    sys_dir = clone_dir / "sys"
    sys_dir.mkdir()
    # File with space in name
    (sys_dir / "my config.g").write_text("G28\nM584 X0\n")
    # File with hyphen and underscore
    (sys_dir / "home-x_axis.g").write_text("G91\nG1 H1 X-300\n")

    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "files with special chars"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    return str(bare)


@pytest.fixture
def special_char_env(tmp_path, special_char_repo):
    """Set up integration env with special character file names."""
    printer_fs = tmp_path / "printer_sd"
    printer_fs.mkdir()
    sys_dir = printer_fs / "sys"
    sys_dir.mkdir()

    # Create printer files with different content (to get diffs)
    (sys_dir / "my config.g").write_text("G28\nM584 X1\n")
    (sys_dir / "home-x_axis.g").write_text("G91\nG1 H1 X-200\n")

    ref_dir = str(tmp_path / "reference")
    backup_dir = str(tmp_path / "backups")

    resolved = {
        "0:/sys/": str(printer_fs / "sys") + "/",
    }

    with (
        patch("config_manager.REFERENCE_DIR", ref_dir),
        patch("config_manager.BACKUP_DIR", backup_dir),
    ):
        manager = ConfigManager(
            dsf_command_connection=MagicMock(),
            resolved_dirs=resolved,
        )
        yield {
            "manager": manager,
            "repo_url": special_char_repo,
            "printer_fs": printer_fs,
        }


class TestSpecialCharacterFilePaths:
    """Integration tests for files with spaces, hyphens, and special characters."""

    def test_sync_lists_special_char_files(self, special_char_env):
        env = special_char_env
        result = env["manager"].sync(env["repo_url"], "1.0")
        assert "error" not in result

    def test_diff_with_spaces_in_filename(self, special_char_env):
        env = special_char_env
        env["manager"].sync(env["repo_url"], "1.0")

        diff = env["manager"].diff_all()
        files = {f["file"]: f["status"] for f in diff}
        assert "sys/my config.g" in files
        assert files["sys/my config.g"] == "modified"

    def test_diff_file_with_space(self, special_char_env):
        env = special_char_env
        env["manager"].sync(env["repo_url"], "1.0")

        detail = env["manager"].diff_file("sys/my config.g")
        assert detail["status"] == "modified"
        assert len(detail["hunks"]) > 0

    def test_apply_file_with_space(self, special_char_env):
        env = special_char_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("sys/my config.g")
        assert result == {"applied": ["sys/my config.g"]}
        assert "M584 X0" in (pfs / "sys" / "my config.g").read_text()

    def test_apply_all_with_special_chars(self, special_char_env):
        env = special_char_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_all()
        assert "sys/my config.g" in result["applied"]
        assert "sys/home-x_axis.g" in result["applied"]

    def test_backup_restore_with_special_chars(self, special_char_env):
        env = special_char_env
        pfs = env["printer_fs"]
        original = (pfs / "sys" / "my config.g").read_text()

        env["manager"].sync(env["repo_url"], "1.0")
        env["manager"].apply_all()
        assert (pfs / "sys" / "my config.g").read_text() != original

        backups = env["manager"].get_backups()
        pre_update = [b for b in backups if "Pre-update" in b["message"]]
        assert len(pre_update) > 0

        env["manager"].restore_backup(pre_update[0]["hash"])
        restored = (pfs / "sys" / "my config.g").read_text().rstrip("\n")
        assert restored == original.rstrip("\n")

    def test_apply_hunks_with_special_chars(self, special_char_env):
        env = special_char_env
        env["manager"].sync(env["repo_url"], "1.0")

        detail = env["manager"].diff_file("sys/my config.g")
        assert detail["status"] == "modified"

        result = env["manager"].apply_hunks("sys/my config.g", [0])
        assert 0 in result["applied"]
