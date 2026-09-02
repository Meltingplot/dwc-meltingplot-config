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

    def test_backup_file_content_returns_file(self, integration_env):
        """get_backup_file_content should return full file content."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        result = env["manager"].get_backup_file_content(backups[0]["hash"], "sys/config.g")
        assert result["status"] == "ok"
        assert result["content"] is not None
        assert len(result["content"]) > 0

    def test_backup_file_content_not_found(self, integration_env):
        """get_backup_file_content should handle missing files."""
        env = integration_env
        env["manager"].sync(env["repo_url"], "3.5")
        env["manager"].apply_all()

        backups = env["manager"].get_backups()
        result = env["manager"].get_backup_file_content(backups[0]["hash"], "nonexistent/file.g")
        assert result["status"] == "not_found"
        assert result["content"] is None


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


# --- Protected override files ---


@pytest.fixture
def protected_file_repo(tmp_path):
    """Create a reference repo containing protected override files."""
    bare = tmp_path / "protected_bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "receive.denyCurrentBranch", "ignore"],
        cwd=str(bare), check=True, capture_output=True,
    )

    clone_dir = tmp_path / "protected_setup"
    subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)

    sys_dir = clone_dir / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\n")
    # RRF's own M500 override file
    (sys_dir / "config-override.g").write_text("M307 H0 R0.5\n")

    mp_dir = sys_dir / "meltingplot"
    mp_dir.mkdir()
    (mp_dir / "dsf-config-override.g").write_text("M906 X900\n")
    (mp_dir / "global-override.g").write_text("set global.mp_z_offset = 0.0\n")
    # machine-override is a file without extension
    (mp_dir / "machine-override").write_text("M208 X300 Y300 Z400\n")

    # Filament profile with its own protected config-override.g / temps.g
    filament_dir = clone_dir / "filaments" / "PLA"
    filament_dir.mkdir(parents=True)
    (filament_dir / "config.g").write_text("M104 S210\n")
    (filament_dir / "config-override.g").write_text("M572 D0 S0.05\n")
    (filament_dir / "temps.g").write_text("set global.filament_temp_active = 210\n")

    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "config with overrides"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    return str(bare)


@pytest.fixture
def protected_env(tmp_path, protected_file_repo):
    """Integration env with protected override files."""
    printer_fs = tmp_path / "printer_sd"
    printer_fs.mkdir()
    sys_dir = printer_fs / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\n")
    (sys_dir / "config-override.g").write_text("M307 H0 R0.9 ORIGINAL\n")

    mp_dir = sys_dir / "meltingplot"
    mp_dir.mkdir()
    (mp_dir / "dsf-config-override.g").write_text("M906 X800 ORIGINAL\n")
    (mp_dir / "global-override.g").write_text("set global.mp_z_offset = 0.42 ORIGINAL\n")
    (mp_dir / "machine-override").write_text("M208 X200 Y200 Z300 ORIGINAL\n")

    filament_dir = printer_fs / "filaments" / "PLA"
    filament_dir.mkdir(parents=True)
    (filament_dir / "config.g").write_text("M104 S200\n")
    (filament_dir / "config-override.g").write_text("M572 D0 S0.09 ORIGINAL\n")
    (filament_dir / "temps.g").write_text("set global.filament_temp_active = 195 ORIGINAL\n")

    ref_dir = str(tmp_path / "reference")
    backup_dir = str(tmp_path / "backups")

    resolved = {
        "0:/sys/": str(printer_fs / "sys") + "/",
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
            "repo_url": protected_file_repo,
            "printer_fs": printer_fs,
        }


class TestProtectedFiles:
    """Integration tests for protected override files."""

    def test_diff_all_excludes_protected_files(self, protected_env):
        """Protected files should be excluded from diff_all entirely."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        diff = env["manager"].diff_all()
        files_in_diff = {f["file"] for f in diff}

        assert "sys/config.g" in files_in_diff
        assert "sys/meltingplot/dsf-config-override.g" not in files_in_diff
        assert "sys/meltingplot/global-override.g" not in files_in_diff
        assert "sys/meltingplot/machine-override" not in files_in_diff
        assert "filaments/PLA/config-override.g" not in files_in_diff
        assert "filaments/PLA/temps.g" not in files_in_diff
        assert "sys/config-override.g" not in files_in_diff
        # The filament profile's machine-generated config is still diffed
        assert "filaments/PLA/config.g" in files_in_diff

    def test_diff_file_returns_error_for_protected(self, protected_env):
        """diff_file on a protected file should return an error."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        detail = env["manager"].diff_file("sys/meltingplot/machine-override")
        assert "error" in detail

    def test_apply_all_skips_protected_files(self, protected_env):
        """apply_all should skip protected files and report them as skipped."""
        env = protected_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_all()
        assert "error" not in result

        # Protected files should be in skipped, not applied
        assert "sys/meltingplot/dsf-config-override.g" in result["skipped"]
        assert "sys/meltingplot/global-override.g" in result["skipped"]
        assert "sys/meltingplot/machine-override" in result["skipped"]
        assert "filaments/PLA/config-override.g" in result["skipped"]
        assert "filaments/PLA/temps.g" in result["skipped"]
        assert "sys/config-override.g" in result["skipped"]

        # Protected files should retain their original content
        override_content = (pfs / "sys" / "meltingplot" / "dsf-config-override.g").read_text()
        assert "ORIGINAL" in override_content

        global_content = (pfs / "sys" / "meltingplot" / "global-override.g").read_text()
        assert "ORIGINAL" in global_content

        machine_content = (pfs / "sys" / "meltingplot" / "machine-override").read_text()
        assert "ORIGINAL" in machine_content

        filament_override = (pfs / "filaments" / "PLA" / "config-override.g").read_text()
        assert "ORIGINAL" in filament_override

        filament_temps = (pfs / "filaments" / "PLA" / "temps.g").read_text()
        assert "ORIGINAL" in filament_temps

        rrf_override = (pfs / "sys" / "config-override.g").read_text()
        assert "ORIGINAL" in rrf_override

        # The filament profile's normal config is updated
        assert "filaments/PLA/config.g" in result["applied"]

    def test_apply_file_rejects_protected_file(self, protected_env):
        """apply_file on a protected file should return an error."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("sys/meltingplot/machine-override")
        assert "error" in result
        assert "Protected" in result["error"]

    def test_apply_hunks_rejects_protected_file(self, protected_env):
        """apply_hunks on a protected file should return an error."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_hunks("sys/meltingplot/dsf-config-override.g", [0])
        assert "error" in result
        assert "Protected" in result["error"]

    def test_apply_file_rejects_filament_override(self, protected_env):
        """apply_file on a filament profile's config-override.g is rejected."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("filaments/PLA/config-override.g")
        assert "error" in result
        assert "Protected" in result["error"]

    def test_apply_hunks_rejects_filament_override(self, protected_env):
        """apply_hunks on a filament profile's config-override.g is rejected."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_hunks("filaments/PLA/config-override.g", [0])
        assert "error" in result
        assert "Protected" in result["error"]

    def test_apply_file_rejects_filament_temps(self, protected_env):
        """apply_file on a filament profile's temps.g is rejected."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("filaments/PLA/temps.g")
        assert "error" in result
        assert "Protected" in result["error"]

    def test_apply_file_rejects_rrf_config_override(self, protected_env):
        """apply_file on RRF's own config-override.g is rejected."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("sys/config-override.g")
        assert "error" in result
        assert "Protected" in result["error"]

    def test_diff_file_returns_error_for_filament_override(self, protected_env):
        """diff_file on a filament profile's config-override.g is rejected."""
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        detail = env["manager"].diff_file("filaments/PLA/config-override.g")
        assert "error" in detail

    def test_normal_file_still_applies(self, protected_env):
        """Non-protected files should still be applied normally."""
        env = protected_env
        pfs = env["printer_fs"]
        # Modify the normal config so there's a diff
        (pfs / "sys" / "config.g").write_text("G28\nM584 X0 Y1 OLD\n")

        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("sys/config.g")
        assert "sys/config.g" in result["applied"]

    def test_apply_selection_skips_protected_files(self, protected_env):
        """A protected file in the selection is reported, never overwritten."""
        env = protected_env
        pfs = env["printer_fs"]
        (pfs / "sys" / "config.g").write_text("G28\nM584 X0 Y1 OLD\n")
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_selection([
            "sys/config.g",
            "sys/meltingplot/dsf-config-override.g",
        ])

        assert result["applied"] == ["sys/config.g"]
        assert result["skipped"] == ["sys/meltingplot/dsf-config-override.g"]
        assert "Protected" in result["errors"]["sys/meltingplot/dsf-config-override.g"]
        assert "ORIGINAL" in (pfs / "sys" / "meltingplot" / "dsf-config-override.g").read_text()


@pytest.fixture
def protected_missing_env(tmp_path, protected_file_repo):
    """Integration env where the protected override files do not exist yet.

    This is the state of a printer that has never seen a given filament
    profile: the reference repo ships ``config-override.g`` / ``temps.g``
    but the printer has no copy to protect.
    """
    printer_fs = tmp_path / "printer_sd"
    printer_fs.mkdir()
    sys_dir = printer_fs / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\n")
    # No sys/config-override.g, no sys/meltingplot/ at all

    # Filament directory exists but the profile has never been synced
    (printer_fs / "filaments").mkdir()

    ref_dir = str(tmp_path / "reference")
    backup_dir = str(tmp_path / "backups")

    resolved = {
        "0:/sys/": str(printer_fs / "sys") + "/",
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
            "repo_url": protected_file_repo,
            "printer_fs": printer_fs,
        }


class TestProtectedFilesMissingOnPrinter:
    """Protected files absent on the printer must still be created."""

    def test_diff_all_includes_missing_protected_files(self, protected_missing_env):
        env = protected_missing_env
        env["manager"].sync(env["repo_url"], "1.0")

        diff = env["manager"].diff_all()
        by_file = {f["file"]: f for f in diff}

        assert by_file["filaments/PLA/config-override.g"]["status"] == "missing"
        assert by_file["filaments/PLA/temps.g"]["status"] == "missing"
        assert by_file["sys/config-override.g"]["status"] == "missing"
        assert by_file["sys/meltingplot/machine-override"]["status"] == "missing"

    def test_diff_file_works_for_missing_protected_file(self, protected_missing_env):
        env = protected_missing_env
        env["manager"].sync(env["repo_url"], "1.0")

        detail = env["manager"].diff_file("filaments/PLA/config-override.g")
        assert "error" not in detail
        assert detail["status"] == "missing"
        assert len(detail["hunks"]) > 0

    def test_apply_file_creates_missing_protected_file(self, protected_missing_env):
        env = protected_missing_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_file("filaments/PLA/config-override.g")
        assert "error" not in result
        assert "filaments/PLA/config-override.g" in result["applied"]

        created = pfs / "filaments" / "PLA" / "config-override.g"
        assert created.read_text() == "M572 D0 S0.05\n"

    def test_apply_all_creates_missing_protected_files(self, protected_missing_env):
        env = protected_missing_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "1.0")

        result = env["manager"].apply_all()
        assert "error" not in result
        assert result.get("skipped", []) == []

        assert "filaments/PLA/config-override.g" in result["applied"]
        assert "filaments/PLA/temps.g" in result["applied"]
        assert "sys/config-override.g" in result["applied"]
        assert "sys/meltingplot/machine-override" in result["applied"]
        assert "sys/meltingplot/global-override.g" in result["applied"]

        assert (pfs / "filaments" / "PLA" / "config-override.g").read_text() == "M572 D0 S0.05\n"
        assert (pfs / "filaments" / "PLA" / "temps.g").exists()
        assert (pfs / "sys" / "config-override.g").read_text() == "M307 H0 R0.5\n"
        assert (pfs / "sys" / "meltingplot" / "global-override.g").exists()

    def test_created_file_is_protected_afterwards(self, protected_missing_env):
        """Once created, the file is protected from further updates."""
        env = protected_missing_env
        pfs = env["printer_fs"]
        env["manager"].sync(env["repo_url"], "1.0")
        env["manager"].apply_file("filaments/PLA/config-override.g")

        # User tunes the freshly created file
        target = pfs / "filaments" / "PLA" / "config-override.g"
        target.write_text("M572 D0 S0.11 TUNED\n")

        result = env["manager"].apply_file("filaments/PLA/config-override.g")
        assert "error" in result
        assert "Protected" in result["error"]

        assert env["manager"].apply_all().get("skipped") == [
            "filaments/PLA/config-override.g"
        ]
        assert target.read_text() == "M572 D0 S0.11 TUNED\n"

    def test_list_reference_files_includes_missing_protected(self, protected_missing_env):
        env = protected_missing_env
        env["manager"].sync(env["repo_url"], "1.0")

        files = env["manager"].list_reference_files()
        assert "filaments/PLA/config-override.g" in files
        assert "sys/config-override.g" in files

    def test_list_reference_files_excludes_existing_protected(self, protected_env):
        env = protected_env
        env["manager"].sync(env["repo_url"], "1.0")

        files = env["manager"].list_reference_files()
        assert "sys/config.g" in files
        assert "filaments/PLA/config-override.g" not in files
        assert "sys/config-override.g" not in files
        assert "sys/meltingplot/global-override.g" not in files


# --- Partial apply (mixed file / hunk selection) ---


@pytest.fixture
def selection_repo(tmp_path):
    """Reference repo with a multi-hunk config plus two single-hunk files."""
    bare = tmp_path / "selection_bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    clone_dir = tmp_path / "selection_setup"
    subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)

    sys_dir = clone_dir / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text(REFERENCE_CONFIG_G)
    (sys_dir / "homeall.g").write_text("G91\nG1 H1 Z5 F600\nG90\n")
    (sys_dir / "onlyinref.g").write_text("; created by the reference\nM98\n")

    macros_dir = clone_dir / "macros"
    macros_dir.mkdir()
    (macros_dir / "start.g").write_text("T0\nM116\nG29\n")

    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "reference config"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    return str(bare)


# A config long enough that two edits far apart produce two separate hunks
# (difflib uses 3 lines of context).
REFERENCE_CONFIG_G = """; Reference config
M111 S0
M550 P"printer"
M552 S1
G21
G90
M83
M569 P0 S1
M569 P1 S1
M584 X0 Y1 Z2
M350 X16 Y16 Z16 I1
M92 X80 Y80 Z400
M566 X900 Y900 Z12
M203 X6000 Y6000 Z300
M201 X500 Y500 Z20
M906 X1000 Y1000 Z1000 I30
M84 S30
M140 H0
M143 S280
T0
"""

# Same file as on the printer: differs in line 2 (first hunk) and in the
# M906 line (second hunk).
PRINTER_CONFIG_G = (
    REFERENCE_CONFIG_G
    .replace("M111 S0", "M111 S1")
    .replace("M906 X1000 Y1000 Z1000 I30", "M906 X800 Y800 Z800 I30")
)


@pytest.fixture
def selection_env(tmp_path, selection_repo):
    """Printer filesystem that differs from the reference in several files."""
    printer_fs = tmp_path / "selection_sd"
    (printer_fs / "sys").mkdir(parents=True)
    (printer_fs / "macros").mkdir()
    (printer_fs / "filaments").mkdir()

    (printer_fs / "sys" / "config.g").write_text(PRINTER_CONFIG_G)
    (printer_fs / "sys" / "homeall.g").write_text("G91\nG1 H1 Z10 F600\nG90\n")
    (printer_fs / "macros" / "start.g").write_text("T0\nM116\n")
    # sys/onlyinref.g deliberately absent -> status "missing"

    ref_dir = str(tmp_path / "selection_reference")
    backup_dir = str(tmp_path / "selection_backups")

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
        manager.sync(selection_repo, "1.0")
        yield {
            "manager": manager,
            "repo_url": selection_repo,
            "printer_fs": printer_fs,
        }


class TestApplySelection:
    """Partial apply: keep some files/hunks, leave the rest untouched."""

    def test_fixture_produces_two_hunks_for_config(self, selection_env):
        """Sanity check: the config diff really has two separate hunks."""
        detail = selection_env["manager"].diff_file("sys/config.g")
        assert detail["status"] == "modified"
        assert len(detail["hunks"]) == 2

    def test_excluded_file_is_left_untouched(self, selection_env):
        """A file absent from the selection keeps its printer content."""
        env = selection_env
        pfs = env["printer_fs"]
        before = _read_printer(pfs, "macros/start.g")

        result = env["manager"].apply_selection(["sys/config.g", "sys/homeall.g"])

        assert "error" not in result
        assert set(result["applied"]) == {"sys/config.g", "sys/homeall.g"}
        assert _read_printer(pfs, "macros/start.g") == before
        assert _read_printer(pfs, "sys/config.g") == REFERENCE_CONFIG_G

    def test_excluded_hunk_is_left_untouched(self, selection_env):
        """Only the selected hunk of a file is applied."""
        env = selection_env
        pfs = env["printer_fs"]

        result = env["manager"].apply_selection([{"file": "sys/config.g", "hunks": [0]}])

        assert result["applied"] == ["sys/config.g"]
        assert result["partial"]["sys/config.g"] == {"applied": [0], "failed": []}

        content = _read_printer(pfs, "sys/config.g")
        assert "M111 S0" in content          # first hunk applied
        assert "M906 X800 Y800 Z800" in content  # second hunk skipped

    def test_mixed_whole_file_and_hunk_selection(self, selection_env):
        """Whole files and per-hunk entries can be combined in one call."""
        env = selection_env
        pfs = env["printer_fs"]
        start_before = _read_printer(pfs, "macros/start.g")

        result = env["manager"].apply_selection([
            {"file": "sys/config.g", "hunks": [1]},
            {"file": "sys/homeall.g"},
        ])

        assert set(result["applied"]) == {"sys/config.g", "sys/homeall.g"}
        config = _read_printer(pfs, "sys/config.g")
        assert "M111 S1" in config                 # first hunk skipped
        assert "M906 X1000 Y1000 Z1000" in config  # second hunk applied
        assert _read_printer(pfs, "sys/homeall.g") == "G91\nG1 H1 Z5 F600\nG90\n"
        assert _read_printer(pfs, "macros/start.g") == start_before

    def test_missing_file_is_created_whole(self, selection_env):
        """A file that only exists in the reference is written in full."""
        env = selection_env
        pfs = env["printer_fs"]

        result = env["manager"].apply_selection([{"file": "sys/onlyinref.g", "hunks": [0]}])

        assert result["applied"] == ["sys/onlyinref.g"]
        assert _read_printer(pfs, "sys/onlyinref.g") == "; created by the reference\nM98\n"

    def test_creates_single_backup_pair(self, selection_env):
        """One partial apply yields one restore point, not one per file."""
        env = selection_env
        before = len(env["manager"].get_backups())

        env["manager"].apply_selection([
            {"file": "sys/config.g", "hunks": [0]},
            {"file": "sys/homeall.g"},
        ])

        backups = env["manager"].get_backups()
        assert len(backups) - before == 2
        assert any("Partially applied reference" in b["message"] for b in backups)

    def test_diff_after_partial_apply_still_shows_remaining_change(self, selection_env):
        """The deselected hunk is still reported as an outstanding change."""
        env = selection_env
        env["manager"].apply_selection([{"file": "sys/config.g", "hunks": [0]}])

        detail = env["manager"].diff_file("sys/config.g")
        assert detail["status"] == "modified"
        assert len(detail["hunks"]) == 1

    def test_unknown_path_is_skipped_with_reason(self, selection_env):
        env = selection_env
        result = env["manager"].apply_selection(["nowhere/nope.g", "sys/homeall.g"])

        assert result["applied"] == ["sys/homeall.g"]
        assert result["skipped"] == ["nowhere/nope.g"]
        assert "Unknown reference path" in result["errors"]["nowhere/nope.g"]

    def test_missing_reference_file_is_skipped(self, selection_env):
        env = selection_env
        result = env["manager"].apply_selection(["sys/does-not-exist.g"])

        assert result["applied"] == []
        assert result["skipped"] == ["sys/does-not-exist.g"]
        assert "Reference file not found" in result["errors"]["sys/does-not-exist.g"]

    def test_invalid_hunk_index_is_skipped(self, selection_env):
        env = selection_env
        pfs = env["printer_fs"]
        before = _read_printer(pfs, "sys/config.g")

        result = env["manager"].apply_selection([{"file": "sys/config.g", "hunks": [99]}])

        assert result["applied"] == []
        assert result["skipped"] == ["sys/config.g"]
        assert _read_printer(pfs, "sys/config.g") == before

    def test_empty_selection_is_an_error(self, selection_env):
        assert "error" in selection_env["manager"].apply_selection([])

    def test_malformed_selection_is_an_error(self, selection_env):
        manager = selection_env["manager"]
        assert "error" in manager.apply_selection("sys/config.g")
        assert "error" in manager.apply_selection([{"hunks": [0]}])
        assert "error" in manager.apply_selection([{"file": "sys/config.g", "hunks": "0"}])
        assert "error" in manager.apply_selection([{"file": "sys/config.g", "hunks": ["0"]}])
        assert "error" in manager.apply_selection([42])
