"""Core logic for the Meltingplot Config plugin: sync, diff, apply, hunks."""

import difflib
import logging
import os
import re
from datetime import datetime, timezone

from git_utils import (
    backup_archive,
    backup_changed_files,
    backup_checkout,
    backup_commit,
    backup_delete,
    backup_file_content,
    backup_files_at,
    backup_log,
    checkout,
    clone,
    current_branch,
    fetch,
    find_closest_branch,
    init_backup_repo,
    list_files,
    list_remote_branches,
    pull,
)

logger = logging.getLogger("MeltingplotConfig")

# Persistent data directory — lives on the SD card so it survives plugin
# upgrades (DSF wipes the plugin directory during upgrade/reinstall).
# Placed directly under /opt/dsf/sd/ (not under sys/) to avoid being
# visible in the DWC file browser.
DATA_DIR = "/opt/dsf/sd/MeltingplotConfig"
REFERENCE_DIR = os.path.join(DATA_DIR, "reference")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

# Directories backed up via the worktree-based backup repo.
# Only these top-level printer directories are tracked; everything else
# (gcodes, firmware, www, menu) is excluded by not being staged.
BACKUP_INCLUDED_DIRS = ("sys/", "macros/", "filaments/")

# Files that must never be overwritten by reference config updates.
# These contain machine-specific overrides (calibration data, user
# customisations) that would be lost if replaced with reference defaults.
# Matched by exact ref_path.
PROTECTED_FILES = (
    "sys/meltingplot/machine-override",
    "sys/meltingplot/dsf-config-override.g",
)

# Default directory mapping (fallback when DSF object model is unavailable).
# In production, the daemon reads model.directories and builds this dynamically.
DEFAULT_DIRECTORY_MAP = {
    "sys/": "0:/sys/",
    "macros/": "0:/macros/",
    "filaments/": "0:/filaments/",
    "firmware/": "0:/firmware/",
    "gcodes/": "0:/gcodes/",
    "menu/": "0:/menu/",
    "www/": "0:/www/",
}


class ConfigManager:
    """Manages reference sync, diffing, applying, and backups."""

    # Default resolved directory mapping (SBC standard layout).
    DEFAULT_RESOLVED_DIRS = {
        "0:/sys/": "/opt/dsf/sd/sys/",
        "0:/macros/": "/opt/dsf/sd/macros/",
        "0:/filaments/": "/opt/dsf/sd/filaments/",
        "0:/firmware/": "/opt/dsf/sd/firmware/",
        "0:/gcodes/": "/opt/dsf/sd/gcodes/",
        "0:/menu/": "/opt/dsf/sd/menu/",
        "0:/www/": "/opt/dsf/sd/www/",
    }

    def __init__(self, dsf_command_connection=None, directory_map=None, resolved_dirs=None):
        self._dsf = dsf_command_connection
        self._dir_map = directory_map if directory_map is not None else DEFAULT_DIRECTORY_MAP
        self._resolved_dirs = resolved_dirs if resolved_dirs is not None else self.DEFAULT_RESOLVED_DIRS
        # Derive the git worktree root and the relative directory names that
        # should be tracked in backups, using the resolved filesystem paths
        # from the DSF object model.
        self._worktree, self._backup_paths = self._compute_backup_worktree()
        init_backup_repo(BACKUP_DIR, worktree=self._worktree)

    def _compute_backup_worktree(self):
        """Derive the git worktree root and relative backup paths.

        Uses the resolved filesystem paths from the DSF object model to
        find a common parent directory that can serve as the git worktree.
        Only directories listed in ``BACKUP_INCLUDED_DIRS`` are considered.

        Returns ``(worktree_root, [relative_dir_names])`` or ``(None, [])``
        if the directories cannot be resolved.
        """
        fs_paths = []
        for ref_prefix in BACKUP_INCLUDED_DIRS:
            printer_path = self._dir_map.get(ref_prefix)
            if not printer_path:
                continue
            fs_path = self._resolved_dirs.get(printer_path)
            if fs_path:
                fs_paths.append(fs_path.rstrip("/"))

        if not fs_paths:
            return None, []

        # Use the parent of each directory so the common root is always a
        # proper parent — e.g. for ["/sd/sys"] the root is "/sd" (not
        # "/sd/sys" which would make the relative path ".").
        parents = list({os.path.dirname(fp) for fp in fs_paths})
        common = parents[0] if len(parents) == 1 else os.path.commonpath(parents)
        rel_paths = [os.path.relpath(fp, common) for fp in fs_paths]
        return common, rel_paths

    # --- File I/O via resolved filesystem paths ---

    def _printer_to_fs_path(self, printer_path):
        """Convert a virtual printer path to a real filesystem path.

        Uses resolved_dirs (populated at startup via DSF resolve_path)
        to map e.g. '0:/sys/config.g' -> '/opt/dsf/sd/sys/config.g'.
        """
        for printer_prefix, fs_prefix in self._resolved_dirs.items():
            if printer_path.startswith(printer_prefix):
                return fs_prefix + printer_path[len(printer_prefix):]
        return None

    def _read_printer_file(self, printer_path):
        """Read a file from the printer filesystem."""
        fs_path = self._printer_to_fs_path(printer_path)
        if fs_path is None:
            logger.debug("Cannot resolve printer path: %s", printer_path)
            return None
        try:
            with open(fs_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except (FileNotFoundError, IOError) as exc:
            logger.debug("Cannot read %s (%s): %s", printer_path, fs_path, exc)
            return None

    def _write_printer_file(self, printer_path, content):
        """Write a file to the printer filesystem."""
        fs_path = self._printer_to_fs_path(printer_path)
        if fs_path is None:
            raise RuntimeError(f"Cannot resolve printer path: {printer_path}")
        os.makedirs(os.path.dirname(fs_path), exist_ok=True)
        with open(fs_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _read_reference_file(self, rel_path):
        """Read a file from the local reference repository."""
        full_path = os.path.join(REFERENCE_DIR, rel_path)
        if not os.path.isfile(full_path):
            return None
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _ref_to_printer_path(self, ref_path):
        """Convert a reference repo path to a printer path.

        e.g., 'sys/config.g' -> '0:/sys/config.g'

        The mapping is built from the DSF object model's directories
        property at startup, or falls back to DEFAULT_DIRECTORY_MAP.
        """
        for ref_prefix, printer_prefix in self._dir_map.items():
            if ref_path.startswith(ref_prefix):
                return printer_prefix + ref_path[len(ref_prefix):]
        return None

    # --- Sync ---

    def sync(self, repo_url, firmware_version, branch_override=""):
        """Sync the reference repository and select the correct branch.

        Returns a status dict.
        """
        if not repo_url:
            return {"error": "No reference repository URL configured"}

        clone(repo_url, REFERENCE_DIR)
        fetch(REFERENCE_DIR)

        target_branch = branch_override or firmware_version
        if not target_branch:
            return {"error": "No firmware version detected and no branch override set"}

        branch, exact = find_closest_branch(REFERENCE_DIR, target_branch)
        if branch is None:
            return {
                "error": f"No matching branch found for '{target_branch}'",
                "branches": list_remote_branches(REFERENCE_DIR),
            }

        checkout(REFERENCE_DIR, branch)
        pull(REFERENCE_DIR)

        warning = None
        if not exact:
            warning = (
                f"Exact branch '{target_branch}' not found, "
                f"using closest match '{branch}'"
            )

        return {
            "activeBranch": branch,
            "exact": exact,
            "warning": warning,
            "branches": list_remote_branches(REFERENCE_DIR),
        }

    def get_branches(self):
        """List available remote branches."""
        if not os.path.isdir(os.path.join(REFERENCE_DIR, ".git")):
            return []
        return list_remote_branches(REFERENCE_DIR)

    def get_active_branch(self):
        """Get the currently checked-out branch."""
        if not os.path.isdir(os.path.join(REFERENCE_DIR, ".git")):
            return ""
        return current_branch(REFERENCE_DIR)

    # --- Diffing ---

    def diff_all(self):
        """Compare all reference files against current printer files.

        Returns a list of file diffs.
        """
        if not os.path.isdir(os.path.join(REFERENCE_DIR, ".git")):
            return []

        ref_files = list_files(REFERENCE_DIR)
        results = []

        for ref_path in ref_files:
            printer_path = self._ref_to_printer_path(ref_path)
            if printer_path is None:
                continue

            if is_protected(ref_path):
                continue

            ref_content = self._read_reference_file(ref_path)
            printer_content = self._read_printer_file(printer_path)

            if printer_content is None:
                # New file: compute summary hunks so the frontend shows a count
                hunks = self._compute_hunks(ref_path, "", ref_content)
                results.append(
                    {
                        "file": ref_path,
                        "printerPath": printer_path,
                        "status": "missing",
                        "hunks": [
                            {"index": h["index"], "header": h["header"]}
                            for h in hunks
                        ],
                    }
                )
            elif ref_content == printer_content:
                results.append(
                    {
                        "file": ref_path,
                        "printerPath": printer_path,
                        "status": "unchanged",
                        "hunks": [],
                    }
                )
            else:
                hunks = self._compute_hunks(ref_path, printer_content, ref_content)
                results.append(
                    {
                        "file": ref_path,
                        "printerPath": printer_path,
                        "status": "modified",
                        "hunks": [
                            {"index": h["index"], "header": h["header"]}
                            for h in hunks
                        ],
                    }
                )

        return results

    def diff_file(self, ref_path):
        """Get detailed diff for a single file, with indexed hunks.

        Returns the full diff response format specified in the plan.
        """
        printer_path = self._ref_to_printer_path(ref_path)
        if printer_path is None:
            return {"error": f"Unknown reference path: {ref_path}"}

        if is_protected(ref_path):
            return {"error": f"Protected file: {ref_path}"}

        ref_content = self._read_reference_file(ref_path)
        printer_content = self._read_printer_file(printer_path)

        if ref_content is None:
            return {"file": ref_path, "status": "not_in_reference"}

        if printer_content is None:
            # New file: show the entire reference content as additions
            hunks = self._compute_hunks(ref_path, "", ref_content)
            unified = difflib.unified_diff(
                [],
                ref_content.splitlines(keepends=True),
                fromfile=f"a/{ref_path}",
                tofile=f"b/{ref_path}",
            )
            return {
                "file": ref_path,
                "status": "missing",
                "hunks": hunks,
                "unifiedDiff": "".join(unified),
            }

        if ref_content == printer_content:
            return {
                "file": ref_path,
                "status": "unchanged",
                "hunks": [],
                "unifiedDiff": "",
            }

        hunks = self._compute_hunks(ref_path, printer_content, ref_content)
        unified = difflib.unified_diff(
            printer_content.splitlines(keepends=True),
            ref_content.splitlines(keepends=True),
            fromfile=f"a/{ref_path}",
            tofile=f"b/{ref_path}",
        )

        return {
            "file": ref_path,
            "status": "modified",
            "hunks": hunks,
            "unifiedDiff": "".join(unified),
        }

    @staticmethod
    def _compute_hunks(ref_path, current_content, reference_content):
        """Parse a unified diff into indexed hunks with summaries."""
        diff_lines = list(
            difflib.unified_diff(
                current_content.splitlines(keepends=True),
                reference_content.splitlines(keepends=True),
                fromfile=f"a/{ref_path}",
                tofile=f"b/{ref_path}",
                n=3,
            )
        )

        hunks = []
        current_hunk = None
        hunk_index = 0

        for line in diff_lines:
            if line.startswith("@@"):
                if current_hunk is not None:
                    current_hunk["summary"] = _hunk_summary(current_hunk)
                    hunks.append(current_hunk)
                current_hunk = {
                    "index": hunk_index,
                    "header": line.rstrip("\n"),
                    "lines": [],
                    "summary": "",
                }
                hunk_index += 1
            elif current_hunk is not None:
                current_hunk["lines"].append(line.rstrip("\n"))

        if current_hunk is not None:
            current_hunk["summary"] = _hunk_summary(current_hunk)
            hunks.append(current_hunk)

        return hunks

    # --- Applying ---

    def apply_all(self):
        """Apply all reference config files to the printer (with backup)."""
        if not os.path.isdir(os.path.join(REFERENCE_DIR, ".git")):
            return {"error": "Reference repository not cloned"}

        self._create_backup("Pre-update backup")
        ref_files = list_files(REFERENCE_DIR)
        applied = []
        skipped = []

        for ref_path in ref_files:
            printer_path = self._ref_to_printer_path(ref_path)
            if printer_path is None:
                continue
            if is_protected(ref_path):
                skipped.append(ref_path)
                continue
            ref_content = self._read_reference_file(ref_path)
            if ref_content is not None:
                self._write_printer_file(printer_path, ref_content)
                applied.append(ref_path)

        branch = self.get_active_branch()
        self._create_backup(f"Applied reference {branch}")
        result = {"applied": applied}
        if skipped:
            result["skipped"] = skipped
        return result

    def apply_file(self, ref_path):
        """Apply a single reference file to the printer (with backup)."""
        if is_protected(ref_path):
            return {"error": f"Protected file cannot be overwritten: {ref_path}"}

        printer_path = self._ref_to_printer_path(ref_path)
        if printer_path is None:
            return {"error": f"Unknown reference path: {ref_path}"}

        ref_content = self._read_reference_file(ref_path)
        if ref_content is None:
            return {"error": f"Reference file not found: {ref_path}"}

        self._create_backup(f"Pre-update backup for {ref_path}")
        self._write_printer_file(printer_path, ref_content)
        self._create_backup(f"Applied {ref_path}")
        return {"applied": [ref_path]}

    def apply_hunks(self, ref_path, hunk_indices):
        """Apply selected hunks from a file diff (with backup).

        Returns dict with 'applied' and 'failed' hunk indices.
        """
        if is_protected(ref_path):
            return {"error": f"Protected file cannot be overwritten: {ref_path}"}

        printer_path = self._ref_to_printer_path(ref_path)
        if printer_path is None:
            return {"error": f"Unknown reference path: {ref_path}"}

        ref_content = self._read_reference_file(ref_path)
        printer_content = self._read_printer_file(printer_path)
        if ref_content is None:
            return {"error": f"Reference file not found: {ref_path}"}
        if printer_content is None:
            return {"error": f"Printer file not found: {printer_path}"}

        hunks = self._compute_hunks(ref_path, printer_content, ref_content)
        selected = [h for h in hunks if h["index"] in hunk_indices]
        if not selected:
            return {"error": "No valid hunks selected", "applied": [], "failed": []}

        self._create_backup(f"Pre-update backup for {ref_path} (partial)")

        result_lines = printer_content.splitlines(keepends=True)
        applied = []
        failed = []
        offset = 0

        for hunk in selected:
            success, result_lines, new_offset = _apply_single_hunk(
                result_lines, hunk, offset
            )
            if success:
                applied.append(hunk["index"])
                offset = new_offset
            else:
                failed.append(hunk["index"])

        new_content = "".join(result_lines)
        self._write_printer_file(printer_path, new_content)

        desc = f"Applied {len(applied)} hunk(s) to {ref_path}"
        if failed:
            desc += f" ({len(failed)} failed)"
        self._create_backup(desc)

        return {"applied": applied, "failed": failed}

    # --- Backups ---

    def _create_backup(self, message, force=False):
        """Commit the current printer config state via the worktree.

        The backup repo's ``core.worktree`` points at the printer's SD-card
        root (derived from the DSF object model at startup).  Only the
        directories listed in ``BACKUP_INCLUDED_DIRS`` (sys/, macros/,
        filaments/) are staged, so gcodes and other large directories are
        never tracked.

        If *force* is True, a commit is created even when nothing has
        changed (used for full/manual backups).
        """
        if not self._worktree or not self._backup_paths:
            return
        # Only stage directories that actually exist on the filesystem.
        existing = [
            p for p in self._backup_paths
            if os.path.isdir(os.path.join(self._worktree, p))
        ]
        if not existing:
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        backup_commit(BACKUP_DIR, f"{message} \u2014 {now}", paths=existing,
                      force=force)

    def create_manual_backup(self, message=""):
        """Create a manual (full) backup of the current printer config.

        Manual backups are always full backups — they are created even
        when nothing has changed and are tagged with ``[full]`` so the
        history shows the complete file list instead of only changed files.

        Returns a dict with the backup entry, or an error.
        """
        if not self._worktree or not self._backup_paths:
            return {"error": "Backup directories not configured"}

        label = message.strip() if message else "Manual backup"
        self._create_backup(f"{label} [full]", force=True)

        # Return the latest backup entry
        backups = self.get_backups(max_count=1)
        if backups:
            return {"backup": backups[0]}
        return {"backup": None}

    def get_backups(self, max_count=50):
        """Get backup history."""
        return backup_log(BACKUP_DIR, max_count=max_count)

    def get_backup_files(self, commit_hash):
        """List files in a specific backup."""
        return backup_files_at(BACKUP_DIR, commit_hash)

    def get_backup_changed_files(self, commit_hash):
        """List files changed in a specific backup commit."""
        return backup_changed_files(BACKUP_DIR, commit_hash)

    def get_backup_file_diff(self, commit_hash, file_path):
        """Get diff details for a specific file in a backup commit.

        Compares the file at *commit_hash* against its parent commit.
        Returns a dict with ``file``, ``status``, and ``hunks`` (full
        detail hunks with lines and summary).
        """
        new_content = None
        old_content = None

        try:
            new_content = backup_file_content(BACKUP_DIR, commit_hash, file_path)
        except RuntimeError:
            pass

        try:
            old_content = backup_file_content(
                BACKUP_DIR, f"{commit_hash}^", file_path
            )
        except RuntimeError:
            pass

        if new_content is None and old_content is None:
            return {"file": file_path, "status": "unknown", "hunks": []}

        if old_content is None:
            # File was added in this commit
            hunks = self._compute_hunks(file_path, "", new_content)
            return {"file": file_path, "status": "added", "hunks": hunks}

        if new_content is None:
            # File was deleted in this commit
            hunks = self._compute_hunks(file_path, old_content, "")
            return {"file": file_path, "status": "deleted", "hunks": hunks}

        if old_content == new_content:
            return {"file": file_path, "status": "unchanged", "hunks": []}

        hunks = self._compute_hunks(file_path, old_content, new_content)
        return {"file": file_path, "status": "modified", "hunks": hunks}

    def get_backup_download(self, commit_hash):
        """Get a ZIP archive of a backup. Returns bytes."""
        return backup_archive(BACKUP_DIR, commit_hash)

    def restore_backup(self, commit_hash):
        """Restore printer config from a backup commit.

        Creates a pre-restore backup first (safety net), then checks out
        the requested commit's files directly into the worktree, and
        finally records a post-restore backup.
        """
        self._create_backup("Pre-restore backup")
        files = backup_files_at(BACKUP_DIR, commit_hash)
        backup_checkout(BACKUP_DIR, commit_hash)
        self._create_backup(f"Restored from backup {commit_hash[:8]}")
        return {"restored": files}

    def delete_backup(self, commit_hash):
        """Delete a specific backup commit from the history."""
        backup_delete(BACKUP_DIR, commit_hash)
        return {"deleted": commit_hash}


# --- Protected file helpers ---


def is_protected(ref_path):
    """Check whether a reference path is protected from overwrites.

    Protected files contain machine-specific calibration or user
    overrides that must never be replaced by reference config updates.
    """
    return ref_path in PROTECTED_FILES


# --- Hunk patching helpers ---

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_hunk_header(header):
    """Parse @@ line numbers from a hunk header."""
    m = _HUNK_HEADER_RE.match(header)
    if not m:
        return None
    return {
        "old_start": int(m.group(1)),
        "old_count": int(m.group(2)) if m.group(2) else 1,
        "new_start": int(m.group(3)),
        "new_count": int(m.group(4)) if m.group(4) else 1,
    }


def _apply_single_hunk(lines, hunk, offset):
    """Apply a single hunk to a list of lines.

    Args:
        lines: Current file lines (with newlines).
        hunk: Hunk dict with header and lines.
        offset: Line offset accumulated from previously applied hunks.

    Returns:
        (success, new_lines, new_offset)
    """
    parsed = _parse_hunk_header(hunk["header"])
    if parsed is None:
        return False, lines, offset

    # old_start is 1-based in diff output
    start = parsed["old_start"] - 1 + offset

    # Split hunk lines into context/remove/add
    old_lines = []
    new_lines = []
    for line in hunk["lines"]:
        if line.startswith("-"):
            old_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        else:
            # No-newline-at-end marker or other, treat as context
            old_lines.append(line)
            new_lines.append(line)

    # Verify context matches
    end = start + len(old_lines)
    if end > len(lines):
        return False, lines, offset

    actual = [l.rstrip("\n") for l in lines[start:end]]
    expected = [l.rstrip("\n") for l in old_lines]
    if actual != expected:
        return False, lines, offset

    # Apply: replace old lines with new lines
    new_file_lines = (
        lines[:start]
        + [l + "\n" for l in new_lines]
        + lines[end:]
    )
    new_offset = offset + len(new_lines) - len(old_lines)
    return True, new_file_lines, new_offset


def _hunk_summary(hunk):
    """Generate a human-readable summary for a hunk."""
    parsed = _parse_hunk_header(hunk["header"])
    if parsed is None:
        return ""
    start = parsed["old_start"]
    end = start + parsed["old_count"] - 1
    if start == end:
        return f"Line {start}"
    return f"Lines {start}-{end}"
