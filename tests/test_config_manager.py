"""Tests for config_manager.py — diff engine, hunk parsing, hunk apply."""

import pytest

from config_manager import (
    BACKUP_INCLUDED_DIRS,
    PROTECTED_EXACT_PATHS,
    PROTECTED_PATH_PREFIXES,
    ConfigManager,
    _apply_single_hunk,
    _hunk_summary,
    _parse_hunk_header,
    is_protected,
)


# --- Hunk header parsing ---


class TestParseHunkHeader:
    def test_standard_header(self):
        result = _parse_hunk_header("@@ -10,7 +10,7 @@")
        assert result == {
            "old_start": 10,
            "old_count": 7,
            "new_start": 10,
            "new_count": 7,
        }

    def test_single_line(self):
        result = _parse_hunk_header("@@ -1 +1 @@")
        assert result == {
            "old_start": 1,
            "old_count": 1,
            "new_start": 1,
            "new_count": 1,
        }

    def test_with_trailing_context(self):
        result = _parse_hunk_header("@@ -5,3 +5,4 @@ some context")
        assert result["old_start"] == 5
        assert result["old_count"] == 3
        assert result["new_start"] == 5
        assert result["new_count"] == 4

    def test_add_lines(self):
        result = _parse_hunk_header("@@ -1,3 +1,5 @@")
        assert result["old_count"] == 3
        assert result["new_count"] == 5

    def test_remove_lines(self):
        result = _parse_hunk_header("@@ -1,5 +1,3 @@")
        assert result["old_count"] == 5
        assert result["new_count"] == 3

    def test_invalid_header(self):
        assert _parse_hunk_header("not a header") is None
        assert _parse_hunk_header("") is None


# --- Hunk summary ---


class TestHunkSummary:
    def test_single_line(self):
        hunk = {"header": "@@ -5,1 +5,1 @@", "lines": []}
        assert _hunk_summary(hunk) == "Line 5"

    def test_multi_line(self):
        hunk = {"header": "@@ -10,7 +10,7 @@", "lines": []}
        assert _hunk_summary(hunk) == "Lines 10-16"

    def test_invalid_header(self):
        hunk = {"header": "garbage", "lines": []}
        assert _hunk_summary(hunk) == ""


# --- Applying single hunks ---


class TestApplySingleHunk:
    def test_simple_replacement(self):
        """Replace one line in the middle of a file."""
        lines = ["line1\n", "old_value\n", "line3\n"]
        hunk = {
            "header": "@@ -1,3 +1,3 @@",
            "lines": [
                " line1",
                "-old_value",
                "+new_value",
                " line3",
            ],
        }
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 0)
        assert success is True
        assert offset == 0
        assert new_lines == ["line1\n", "new_value\n", "line3\n"]

    def test_add_line(self):
        """Add a new line (net +1)."""
        lines = ["line1\n", "line2\n"]
        hunk = {
            "header": "@@ -1,2 +1,3 @@",
            "lines": [
                " line1",
                "+inserted",
                " line2",
            ],
        }
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 0)
        assert success is True
        assert offset == 1
        assert len(new_lines) == 3
        assert new_lines[1] == "inserted\n"

    def test_remove_line(self):
        """Remove a line (net -1)."""
        lines = ["line1\n", "to_remove\n", "line3\n"]
        hunk = {
            "header": "@@ -1,3 +1,2 @@",
            "lines": [
                " line1",
                "-to_remove",
                " line3",
            ],
        }
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 0)
        assert success is True
        assert offset == -1
        assert len(new_lines) == 2

    def test_context_mismatch_fails(self):
        """If context doesn't match, the hunk should fail."""
        lines = ["different_line\n", "line2\n"]
        hunk = {
            "header": "@@ -1,2 +1,2 @@",
            "lines": [
                " expected_line",
                "-line2",
                "+new_line2",
            ],
        }
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 0)
        assert success is False
        assert new_lines == lines  # unchanged
        assert offset == 0

    def test_offset_shifts_start(self):
        """An offset from a previous hunk shifts the start position."""
        # Scenario: a previous hunk inserted a line, so offset=1.
        # This hunk targets old_start=2, so start = (2-1) + 1 = 2
        # lines[2] should be "old\n" which matches the hunk's remove line.
        lines = ["a\n", "b\n", "old\n", "d\n"]
        hunk = {
            "header": "@@ -2,1 +2,1 @@",
            "lines": [
                "-old",
                "+new",
            ],
        }
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 1)
        assert success is True
        assert new_lines[2] == "new\n"

    def test_hunk_beyond_file_end_fails(self):
        """Hunk that extends past file length should fail."""
        lines = ["a\n"]
        hunk = {
            "header": "@@ -1,3 +1,3 @@",
            "lines": [" a", " b", " c"],
        }
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 0)
        assert success is False

    def test_invalid_header_fails(self):
        lines = ["a\n"]
        hunk = {"header": "garbage", "lines": []}
        success, new_lines, offset = _apply_single_hunk(lines, hunk, 0)
        assert success is False


# --- Computing hunks from diffs ---


class TestComputeHunks:
    def test_single_hunk(self):
        current = "line1\nold_line\nline3\n"
        reference = "line1\nnew_line\nline3\n"
        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) == 1
        assert hunks[0]["index"] == 0
        assert hunks[0]["header"].startswith("@@")
        assert any("-old_line" in line for line in hunks[0]["lines"])
        assert any("+new_line" in line for line in hunks[0]["lines"])

    def test_multiple_hunks(self):
        # Create files with changes far apart so difflib produces 2 hunks
        current_lines = [f"line{i}\n" for i in range(30)]
        reference_lines = list(current_lines)
        reference_lines[2] = "CHANGED_A\n"
        reference_lines[27] = "CHANGED_B\n"
        current = "".join(current_lines)
        reference = "".join(reference_lines)
        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 2
        assert hunks[0]["index"] == 0
        assert hunks[1]["index"] == 1

    def test_no_changes(self):
        content = "line1\nline2\n"
        hunks = ConfigManager._compute_hunks("test.g", content, content)
        assert len(hunks) == 0

    def test_hunk_summaries(self):
        current = "line1\nold\nline3\n"
        reference = "line1\nnew\nline3\n"
        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) == 1
        assert hunks[0]["summary"] != ""
        assert "Line" in hunks[0]["summary"]


# --- Path conversion ---


class TestRefToPrinterPath:
    def _make_manager(self):
        return ConfigManager.__new__(ConfigManager)

    def test_sys_path(self):
        mgr = self._make_manager()
        mgr._dir_map = {"sys/": "0:/sys/"}
        assert mgr._ref_to_printer_path("sys/config.g") == "0:/sys/config.g"

    def test_macros_path(self):
        mgr = self._make_manager()
        mgr._dir_map = {"macros/": "0:/macros/"}
        assert mgr._ref_to_printer_path("macros/print_start.g") == "0:/macros/print_start.g"

    def test_filaments_path(self):
        mgr = self._make_manager()
        mgr._dir_map = {"filaments/": "0:/filaments/"}
        assert mgr._ref_to_printer_path("filaments/PLA/config.g") == "0:/filaments/PLA/config.g"

    def test_unknown_path(self):
        mgr = self._make_manager()
        mgr._dir_map = {"sys/": "0:/sys/"}
        assert mgr._ref_to_printer_path("unknown/file.g") is None

    def test_nested_sys(self):
        mgr = self._make_manager()
        mgr._dir_map = {"sys/": "0:/sys/"}
        assert mgr._ref_to_printer_path("sys/sub/deep.g") == "0:/sys/sub/deep.g"

    def test_custom_directory_map(self):
        """Directory map from DSF object model can have non-default mappings."""
        mgr = self._make_manager()
        mgr._dir_map = {"gcodes/": "0:/gcodes/", "www/": "0:/www/"}
        assert mgr._ref_to_printer_path("gcodes/job.gcode") == "0:/gcodes/job.gcode"
        assert mgr._ref_to_printer_path("www/index.html") == "0:/www/index.html"
        assert mgr._ref_to_printer_path("sys/config.g") is None


# --- Integration: diff + apply hunks round-trip ---


class TestDiffApplyRoundTrip:
    """Test that computing hunks and applying them produces the expected result."""

    def test_apply_all_hunks_produces_reference(self):
        """Applying all hunks to current should produce the reference content."""
        current = "line1\nold_A\nline3\nline4\nold_B\nline6\n"
        reference = "line1\nnew_A\nline3\nline4\nnew_B\nline6\n"

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) > 0

        result_lines = current.splitlines(keepends=True)
        offset = 0
        for hunk in hunks:
            success, result_lines, offset = _apply_single_hunk(result_lines, hunk, offset)
            assert success is True

        result = "".join(result_lines)
        assert result == reference

    def test_apply_subset_of_hunks(self):
        """Applying only some hunks should produce a partial merge."""
        current_lines = [f"line{i}\n" for i in range(30)]
        reference_lines = list(current_lines)
        reference_lines[2] = "CHANGED_A\n"
        reference_lines[27] = "CHANGED_B\n"
        current = "".join(current_lines)
        reference = "".join(reference_lines)

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 2

        # Apply only the first hunk
        result_lines = current.splitlines(keepends=True)
        success, result_lines, _ = _apply_single_hunk(result_lines, hunks[0], 0)
        assert success is True

        result = "".join(result_lines)
        # First change applied, second not
        assert "CHANGED_A\n" in result
        assert "CHANGED_B\n" not in result


# --- Backup exclusion ---


class TestBackupIncludedDirs:
    def test_sys_included(self):
        assert "sys/" in BACKUP_INCLUDED_DIRS

    def test_macros_included(self):
        assert "macros/" in BACKUP_INCLUDED_DIRS

    def test_filaments_included(self):
        assert "filaments/" in BACKUP_INCLUDED_DIRS

    def test_gcodes_not_included(self):
        assert "gcodes/" not in BACKUP_INCLUDED_DIRS

    def test_firmware_not_included(self):
        assert "firmware/" not in BACKUP_INCLUDED_DIRS


# --- Multi-hunk offset accumulation tests ---


class TestMultiHunkOffsetAccumulation:
    """Tests for offset tracking across multiple hunks with mixed add/delete."""

    def test_three_hunks_with_additions(self):
        """Apply three hunks that each add a line, accumulating offset."""
        current_lines = [f"line{i}\n" for i in range(40)]
        reference_lines = list(current_lines)
        # Insert a new line after positions 5, 20, and 35
        reference_lines.insert(5, "ADDED_A\n")
        reference_lines.insert(21, "ADDED_B\n")   # shifted by prior insert
        reference_lines.insert(37, "ADDED_C\n")   # shifted by 2 prior inserts

        current = "".join(current_lines)
        reference = "".join(reference_lines)

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 3

        result_lines = current.splitlines(keepends=True)
        offset = 0
        for hunk in hunks:
            success, result_lines, offset = _apply_single_hunk(result_lines, hunk, offset)
            assert success is True

        result = "".join(result_lines)
        assert result == reference

    def test_three_hunks_with_deletions(self):
        """Apply three hunks that each delete a line, accumulating negative offset."""
        current_lines = [f"line{i}\n" for i in range(40)]
        reference_lines = list(current_lines)
        # Remove lines at positions 5, 20, 35 (working backwards to keep indices stable)
        del reference_lines[35]
        del reference_lines[20]
        del reference_lines[5]

        current = "".join(current_lines)
        reference = "".join(reference_lines)

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 3

        result_lines = current.splitlines(keepends=True)
        offset = 0
        for hunk in hunks:
            success, result_lines, offset = _apply_single_hunk(result_lines, hunk, offset)
            assert success is True

        result = "".join(result_lines)
        assert result == reference

    def test_mixed_additions_and_deletions(self):
        """Apply hunks with mixed adds and deletes, verifying offset correctness."""
        current_lines = [f"line{i}\n" for i in range(40)]
        reference_lines = list(current_lines)
        # First change: replace line5 with two lines (net +1)
        reference_lines[5] = "REPLACED_A1\n"
        reference_lines.insert(6, "REPLACED_A2\n")
        # Second change (indices shifted +1): delete line25 -> now at 26 (net -1)
        del reference_lines[26]
        # Third change: replace line35 -> now at 35 (net 0)
        reference_lines[35] = "REPLACED_C\n"

        current = "".join(current_lines)
        reference = "".join(reference_lines)

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 3

        result_lines = current.splitlines(keepends=True)
        offset = 0
        for hunk in hunks:
            success, result_lines, offset = _apply_single_hunk(result_lines, hunk, offset)
            assert success is True

        result = "".join(result_lines)
        assert result == reference

    def test_hunk_at_file_end(self):
        """Apply a hunk that modifies the last lines of a file."""
        current = "line1\nline2\nline3\nold_end\n"
        reference = "line1\nline2\nline3\nnew_end\nextra\n"

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 1

        result_lines = current.splitlines(keepends=True)
        offset = 0
        for hunk in hunks:
            success, result_lines, offset = _apply_single_hunk(result_lines, hunk, offset)
            assert success is True

        result = "".join(result_lines)
        assert result == reference

    def test_many_hunks_large_file(self):
        """Stress test: apply many hunks across a large file."""
        current_lines = [f"line{i}\n" for i in range(200)]
        reference_lines = list(current_lines)
        # Modify every 20th line
        for i in range(0, 200, 20):
            reference_lines[i] = f"CHANGED_{i}\n"

        current = "".join(current_lines)
        reference = "".join(reference_lines)

        hunks = ConfigManager._compute_hunks("test.g", current, reference)
        assert len(hunks) >= 5  # At least 5 separate hunks

        result_lines = current.splitlines(keepends=True)
        offset = 0
        for hunk in hunks:
            success, result_lines, offset = _apply_single_hunk(result_lines, hunk, offset)
            assert success is True

        result = "".join(result_lines)
        assert result == reference


# --- Protected files ---


class TestIsProtected:
    """Tests for the is_protected() helper."""

    def test_machine_override_file(self):
        assert is_protected("sys/meltingplot/machine-override.g") is True

    def test_machine_override_directory(self):
        assert is_protected("sys/meltingplot/machine-override/some-file.g") is True

    def test_machine_override_exact(self):
        assert is_protected("sys/meltingplot/machine-override") is True

    def test_dsf_config_override_exact_path(self):
        assert is_protected("sys/meltingplot/dsf-config-override.g") is True

    def test_dsf_config_override_wrong_directory_not_protected(self):
        """Only the exact path sys/meltingplot/dsf-config-override.g is protected."""
        assert is_protected("sys/dsf-config-override.g") is False

    def test_normal_config_not_protected(self):
        assert is_protected("sys/config.g") is False

    def test_macros_not_protected(self):
        assert is_protected("macros/print_start.g") is False

    def test_filaments_not_protected(self):
        assert is_protected("filaments/PLA/config.g") is False

    def test_similar_name_not_protected(self):
        """A file that merely contains 'override' is not protected."""
        assert is_protected("sys/my-override-settings.g") is False

    def test_similar_prefix_not_protected(self):
        """Files in sys/meltingplot/ that don't match the prefix are fine."""
        assert is_protected("sys/meltingplot/other-file.g") is False

    def test_constants_are_tuples(self):
        assert isinstance(PROTECTED_PATH_PREFIXES, tuple)
        assert isinstance(PROTECTED_EXACT_PATHS, tuple)
