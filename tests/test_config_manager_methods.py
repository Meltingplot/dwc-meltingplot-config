"""Tests for ConfigManager class methods — sync, diff, apply, backup, restore."""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from config_manager import ConfigManager, REFERENCE_DIR, BACKUP_DIR


# --- Fixtures ---


@pytest.fixture
def printer_fs(tmp_path):
    """Create a temporary printer filesystem (simulates /opt/dsf/sd/)."""
    root = tmp_path / "printer_sd"
    root.mkdir()
    return root


@pytest.fixture
def mock_dsf():
    """Create a mock DSF connection (used for non-file operations)."""
    return MagicMock()


@pytest.fixture
def manager(mock_dsf, printer_fs):
    """Create a ConfigManager with resolved_dirs pointing to temp filesystem."""
    resolved = {
        "0:/sys/": str(printer_fs / "sys") + "/",
        "0:/macros/": str(printer_fs / "macros") + "/",
        "0:/filaments/": str(printer_fs / "filaments") + "/",
    }
    with patch("config_manager.init_backup_repo"):
        mgr = ConfigManager(
            dsf_command_connection=mock_dsf,
            resolved_dirs=resolved,
        )
    return mgr


def _write_printer_file(printer_fs, rel_path, content):
    """Helper to create a file in the printer filesystem."""
    full = printer_fs / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


# --- File I/O ---


class TestFileIO:
    def test_read_printer_file_success(self, manager, printer_fs):
        _write_printer_file(printer_fs, "sys/config.g", "G28\n")
        result = manager._read_printer_file("0:/sys/config.g")
        assert result == "G28\n"

    def test_read_printer_file_not_found_returns_none(self, manager):
        result = manager._read_printer_file("0:/sys/config.g")
        assert result is None

    def test_read_printer_file_unresolvable_returns_none(self):
        with patch("config_manager.init_backup_repo"):
            mgr = ConfigManager(resolved_dirs={})
        result = mgr._read_printer_file("0:/sys/config.g")
        assert result is None

    def test_write_printer_file_success(self, manager, printer_fs):
        manager._write_printer_file("0:/sys/config.g", "G28\n")
        written = (printer_fs / "sys" / "config.g").read_text()
        assert written == "G28\n"

    def test_write_printer_file_creates_dirs(self, manager, printer_fs):
        manager._write_printer_file("0:/sys/subdir/config.g", "G28\n")
        written = (printer_fs / "sys" / "subdir" / "config.g").read_text()
        assert written == "G28\n"

    def test_write_printer_file_unresolvable_raises(self):
        with patch("config_manager.init_backup_repo"):
            mgr = ConfigManager(resolved_dirs={})
        with pytest.raises(RuntimeError, match="Cannot resolve"):
            mgr._write_printer_file("0:/sys/config.g", "content")

    def test_read_reference_file_success(self, manager, tmp_path):
        ref_file = tmp_path / "test.g"
        ref_file.write_text("G28\nM584\n", encoding="utf-8")
        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager._read_reference_file("test.g")
        assert result == "G28\nM584\n"

    def test_read_reference_file_not_found(self, manager):
        with patch("config_manager.REFERENCE_DIR", "/nonexistent"):
            result = manager._read_reference_file("no_such_file.g")
        assert result is None


# --- Sync ---


class TestSync:
    def test_sync_no_repo_url(self, manager):
        result = manager.sync("", "3.5.1")
        assert "error" in result
        assert "URL" in result["error"]

    def test_sync_no_firmware_version_and_no_override(self, manager):
        with patch("config_manager.clone"), patch("config_manager.fetch"):
            result = manager.sync("https://example.com/repo.git", "")
        assert "error" in result
        assert "firmware version" in result["error"].lower() or "branch override" in result["error"].lower()

    def test_sync_exact_branch_match(self, manager):
        with (
            patch("config_manager.clone") as mock_clone,
            patch("config_manager.fetch") as mock_fetch,
            patch("config_manager.find_closest_branch", return_value=("3.5.1", True)),
            patch("config_manager.checkout") as mock_checkout,
            patch("config_manager.pull") as mock_pull,
            patch("config_manager.list_remote_branches", return_value=["main", "3.5", "3.5.1"]),
        ):
            result = manager.sync("https://example.com/repo.git", "3.5.1")

        mock_clone.assert_called_once_with("https://example.com/repo.git", REFERENCE_DIR)
        mock_fetch.assert_called_once_with(REFERENCE_DIR)
        mock_checkout.assert_called_once_with(REFERENCE_DIR, "3.5.1")
        mock_pull.assert_called_once_with(REFERENCE_DIR)
        assert result["activeBranch"] == "3.5.1"
        assert result["exact"] is True
        assert result["warning"] is None
        assert "branches" in result

    def test_sync_fallback_branch_has_warning(self, manager):
        with (
            patch("config_manager.clone"),
            patch("config_manager.fetch"),
            patch("config_manager.find_closest_branch", return_value=("3.5", False)),
            patch("config_manager.checkout"),
            patch("config_manager.pull"),
            patch("config_manager.list_remote_branches", return_value=["main", "3.5"]),
        ):
            result = manager.sync("https://example.com/repo.git", "3.5.2")

        assert result["activeBranch"] == "3.5"
        assert result["exact"] is False
        assert result["warning"] is not None
        assert "3.5.2" in result["warning"]
        assert "3.5" in result["warning"]

    def test_sync_no_matching_branch(self, manager):
        with (
            patch("config_manager.clone"),
            patch("config_manager.fetch"),
            patch("config_manager.find_closest_branch", return_value=(None, False)),
            patch("config_manager.list_remote_branches", return_value=["main"]),
        ):
            result = manager.sync("https://example.com/repo.git", "9.9.9")

        assert "error" in result
        assert "branches" in result

    def test_sync_branch_override_takes_precedence(self, manager):
        with (
            patch("config_manager.clone"),
            patch("config_manager.fetch"),
            patch("config_manager.find_closest_branch", return_value=("custom", True)) as mock_find,
            patch("config_manager.checkout"),
            patch("config_manager.pull"),
            patch("config_manager.list_remote_branches", return_value=["main", "custom"]),
        ):
            result = manager.sync("https://example.com/repo.git", "3.5.1", branch_override="custom")

        # find_closest_branch should be called with the override, not firmware version
        mock_find.assert_called_once_with(REFERENCE_DIR, "custom")
        assert result["activeBranch"] == "custom"


class TestGetBranches:
    def test_get_branches_when_repo_exists(self, manager, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_remote_branches", return_value=["main", "3.5"]),
        ):
            result = manager.get_branches()
        assert result == ["main", "3.5"]

    def test_get_branches_when_repo_not_cloned(self, manager):
        with patch("config_manager.REFERENCE_DIR", "/nonexistent"):
            result = manager.get_branches()
        assert result == []


class TestGetActiveBranch:
    def test_get_active_branch_when_repo_exists(self, manager, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.current_branch", return_value="3.5"),
        ):
            result = manager.get_active_branch()
        assert result == "3.5"

    def test_get_active_branch_when_repo_not_cloned(self, manager):
        with patch("config_manager.REFERENCE_DIR", "/nonexistent"):
            result = manager.get_active_branch()
        assert result == ""


# --- Diffing ---


class TestDiffAll:
    def test_diff_all_repo_not_cloned(self, manager):
        with patch("config_manager.REFERENCE_DIR", "/nonexistent"):
            result = manager.diff_all()
        assert result == []

    def test_diff_all_unchanged_file(self, manager, printer_fs, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")

        _write_printer_file(printer_fs, "sys/config.g", "G28\n")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["sys/config.g"]),
        ):
            result = manager.diff_all()

        assert len(result) == 1
        assert result[0]["status"] == "unchanged"
        assert result[0]["file"] == "sys/config.g"
        assert result[0]["printerPath"] == "0:/sys/config.g"

    def test_diff_all_missing_file(self, manager, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")

        # No printer file created -> missing
        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["sys/config.g"]),
        ):
            result = manager.diff_all()

        assert len(result) == 1
        assert result[0]["status"] == "missing"

    def test_diff_all_modified_file(self, manager, printer_fs, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\nnew_line\n", encoding="utf-8")

        _write_printer_file(printer_fs, "sys/config.g", "G28\nold_line\n")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["sys/config.g"]),
        ):
            result = manager.diff_all()

        assert len(result) == 1
        assert result[0]["status"] == "modified"
        assert len(result[0]["hunks"]) > 0

    def test_diff_all_skips_unmanaged_paths(self, manager, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["README.md", "unknown/file.txt"]),
        ):
            result = manager.diff_all()

        assert result == []

    def test_diff_all_mixed_statuses(self, manager, printer_fs, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")
        (sys_dir / "homex.g").write_text("G28 X\n", encoding="utf-8")

        # config.g exists on printer with matching content; homex.g does not
        _write_printer_file(printer_fs, "sys/config.g", "G28\n")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["sys/config.g", "sys/homex.g"]),
        ):
            result = manager.diff_all()

        statuses = {r["file"]: r["status"] for r in result}
        assert statuses["sys/config.g"] == "unchanged"
        assert statuses["sys/homex.g"] == "missing"


class TestDiffFile:
    def test_diff_file_unknown_path(self, manager):
        result = manager.diff_file("unknown/file.g")
        assert "error" in result

    def test_diff_file_not_in_reference(self, manager, tmp_path):
        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.diff_file("sys/nonexistent.g")
        assert result["status"] == "not_in_reference"

    def test_diff_file_missing_on_printer(self, manager, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")

        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.diff_file("sys/config.g")

        assert result["status"] == "missing"
        assert result["hunks"] == []
        assert result["unifiedDiff"] == ""

    def test_diff_file_unchanged(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")
        _write_printer_file(printer_fs, "sys/config.g", "G28\n")

        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.diff_file("sys/config.g")

        assert result["status"] == "unchanged"
        assert result["hunks"] == []

    def test_diff_file_modified(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\nnew_line\n", encoding="utf-8")
        _write_printer_file(printer_fs, "sys/config.g", "G28\nold_line\n")

        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.diff_file("sys/config.g")

        assert result["status"] == "modified"
        assert len(result["hunks"]) > 0
        assert result["unifiedDiff"] != ""
        assert "old_line" in result["unifiedDiff"]
        assert "new_line" in result["unifiedDiff"]


# --- Applying ---


class TestApplyAll:
    def test_apply_all_repo_not_cloned(self, manager):
        with patch("config_manager.REFERENCE_DIR", "/nonexistent"):
            result = manager.apply_all()
        assert "error" in result

    def test_apply_all_writes_all_managed_files(self, manager, printer_fs, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")
        (sys_dir / "homex.g").write_text("G28 X\n", encoding="utf-8")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["sys/config.g", "sys/homex.g"]),
            patch.object(manager, "_create_backup"),
            patch.object(manager, "get_active_branch", return_value="3.5"),
        ):
            result = manager.apply_all()

        assert "applied" in result
        assert "sys/config.g" in result["applied"]
        assert "sys/homex.g" in result["applied"]
        assert (printer_fs / "sys" / "config.g").read_text() == "G28\n"
        assert (printer_fs / "sys" / "homex.g").read_text() == "G28 X\n"

    def test_apply_all_skips_unmanaged_files(self, manager, printer_fs, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=["README.md"]),
            patch.object(manager, "_create_backup"),
            patch.object(manager, "get_active_branch", return_value="main"),
        ):
            result = manager.apply_all()

        assert result["applied"] == []
        # No files written to printer fs
        assert not (printer_fs / "sys").exists()

    def test_apply_all_creates_backups(self, manager, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.list_files", return_value=[]),
            patch.object(manager, "_create_backup") as mock_backup,
            patch.object(manager, "get_active_branch", return_value="main"),
        ):
            manager.apply_all()

        # Should create pre-update and post-update backups
        assert mock_backup.call_count == 2
        assert "Pre-update" in mock_backup.call_args_list[0][0][0]


class TestApplyFile:
    def test_apply_file_unknown_path(self, manager):
        result = manager.apply_file("unknown/file.g")
        assert "error" in result

    def test_apply_file_not_in_reference(self, manager, tmp_path):
        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.apply_file("sys/nonexistent.g")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_apply_file_success(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\nnew\n", encoding="utf-8")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch.object(manager, "_create_backup"),
        ):
            result = manager.apply_file("sys/config.g")

        assert result == {"applied": ["sys/config.g"]}
        assert (printer_fs / "sys" / "config.g").read_text() == "G28\nnew\n"

    def test_apply_file_creates_backups(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch.object(manager, "_create_backup") as mock_backup,
        ):
            manager.apply_file("sys/config.g")

        assert mock_backup.call_count == 2


class TestApplyHunks:
    def test_apply_hunks_unknown_path(self, manager):
        result = manager.apply_hunks("unknown/file.g", [0])
        assert "error" in result

    def test_apply_hunks_reference_not_found(self, manager, tmp_path):
        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.apply_hunks("sys/nonexistent.g", [0])
        assert "error" in result

    def test_apply_hunks_printer_file_not_found(self, manager, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\n", encoding="utf-8")

        # No printer file -> error
        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.apply_hunks("sys/config.g", [0])
        assert "error" in result

    def test_apply_hunks_no_valid_hunks(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\nnew\n", encoding="utf-8")
        _write_printer_file(printer_fs, "sys/config.g", "G28\nold\n")

        with patch("config_manager.REFERENCE_DIR", str(tmp_path)):
            result = manager.apply_hunks("sys/config.g", [999])
        assert "error" in result

    def test_apply_hunks_success(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\nnew_line\n", encoding="utf-8")
        _write_printer_file(printer_fs, "sys/config.g", "G28\nold_line\n")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch.object(manager, "_create_backup"),
        ):
            result = manager.apply_hunks("sys/config.g", [0])

        assert 0 in result["applied"]
        assert result["failed"] == []
        # Verify the written content has the new line
        written = (printer_fs / "sys" / "config.g").read_text()
        assert "new_line" in written

    def test_apply_hunks_partial_failure(self, manager, printer_fs, tmp_path):
        """Test that when one hunk fails context match, it's reported as failed."""
        from config_manager import _apply_single_hunk as real_apply

        current_lines = [f"line{i}\n" for i in range(30)]
        reference_lines = list(current_lines)
        reference_lines[2] = "CHANGED_A\n"
        reference_lines[27] = "CHANGED_B\n"
        current_content = "".join(current_lines)
        reference_content = "".join(reference_lines)

        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text(reference_content, encoding="utf-8")
        _write_printer_file(printer_fs, "sys/config.g", current_content)

        call_count = 0

        def apply_first_fail_second(lines, hunk, offset):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return False, lines, offset
            return real_apply(lines, hunk, offset)

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch.object(manager, "_create_backup"),
            patch("config_manager._apply_single_hunk", side_effect=apply_first_fail_second),
        ):
            result = manager.apply_hunks("sys/config.g", [0, 1])

        assert 0 in result["applied"]
        assert 1 in result["failed"]

    def test_apply_hunks_creates_backups(self, manager, printer_fs, tmp_path):
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("G28\nnew\n", encoding="utf-8")
        _write_printer_file(printer_fs, "sys/config.g", "G28\nold\n")

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch.object(manager, "_create_backup") as mock_backup,
        ):
            manager.apply_hunks("sys/config.g", [0])

        assert mock_backup.call_count == 2


# --- Backups ---


class TestCreateBackup:
    def test_create_backup_skips_if_no_repo(self, manager):
        with patch("config_manager.REFERENCE_DIR", "/nonexistent"):
            # Should not raise
            manager._create_backup("test")

    def test_create_backup_copies_printer_files(self, manager, printer_fs, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sys_dir = tmp_path / "sys"
        sys_dir.mkdir()
        (sys_dir / "config.g").write_text("ref content", encoding="utf-8")

        _write_printer_file(printer_fs, "sys/config.g", "printer content")

        backup_dir = tmp_path / "backups"

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.BACKUP_DIR", str(backup_dir)),
            patch("config_manager.list_files", return_value=["sys/config.g"]),
            patch("config_manager.backup_commit") as mock_commit,
        ):
            manager._create_backup("test backup")

        # File should be written to backup dir
        backup_file = backup_dir / "sys" / "config.g"
        assert backup_file.exists()
        assert backup_file.read_text() == "printer content"
        mock_commit.assert_called_once()

    def test_create_backup_skips_unreadable_files(self, manager, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # No printer file -> skipped
        backup_dir = tmp_path / "backups"

        with (
            patch("config_manager.REFERENCE_DIR", str(tmp_path)),
            patch("config_manager.BACKUP_DIR", str(backup_dir)),
            patch("config_manager.list_files", return_value=["sys/config.g"]),
            patch("config_manager.backup_commit"),
        ):
            manager._create_backup("test")

        # No file should be written since printer content was None
        assert not (backup_dir / "sys" / "config.g").exists()


class TestBackupDelegation:
    def test_get_backups(self, manager):
        with patch("config_manager.backup_log", return_value=[{"hash": "abc"}]) as mock_log:
            result = manager.get_backups(max_count=10)
        mock_log.assert_called_once_with(BACKUP_DIR, max_count=10)
        assert result == [{"hash": "abc"}]

    def test_get_backup_files(self, manager):
        with patch("config_manager.backup_files_at", return_value=["sys/config.g"]) as mock_files:
            result = manager.get_backup_files("abc123")
        mock_files.assert_called_once_with(BACKUP_DIR, "abc123")
        assert result == ["sys/config.g"]

    def test_get_backup_download(self, manager):
        with patch("config_manager.backup_archive", return_value=b"PK\x03\x04") as mock_archive:
            result = manager.get_backup_download("abc123")
        mock_archive.assert_called_once_with(BACKUP_DIR, "abc123")
        assert result == b"PK\x03\x04"


class TestRestoreBackup:
    def test_restore_backup_writes_files(self, manager, printer_fs):
        with (
            patch.object(manager, "_create_backup"),
            patch("config_manager.backup_files_at", return_value=["sys/config.g", "sys/homex.g"]),
            patch("config_manager.backup_file_content", side_effect=["G28\n", "G28 X\n"]),
        ):
            result = manager.restore_backup("abc123")

        assert "sys/config.g" in result["restored"]
        assert "sys/homex.g" in result["restored"]
        assert (printer_fs / "sys" / "config.g").read_text() == "G28\n"
        assert (printer_fs / "sys" / "homex.g").read_text() == "G28 X\n"

    def test_restore_backup_creates_safety_backups(self, manager):
        with (
            patch.object(manager, "_create_backup") as mock_backup,
            patch("config_manager.backup_files_at", return_value=[]),
        ):
            manager.restore_backup("abc123")

        # Pre-restore and post-restore backups
        assert mock_backup.call_count == 2
        assert "Pre-restore" in mock_backup.call_args_list[0][0][0]

    def test_restore_backup_skips_unmanaged_paths(self, manager, printer_fs):
        with (
            patch.object(manager, "_create_backup"),
            patch("config_manager.backup_files_at", return_value=["README.md"]),
            patch("config_manager.backup_file_content", return_value="content"),
        ):
            result = manager.restore_backup("abc123")

        assert result["restored"] == []
        assert not (printer_fs / "sys").exists()
