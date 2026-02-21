"""Git operations wrapper for the Meltingplot Config plugin."""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger("MeltingplotConfig")

# Resolve the full path to the git binary at import time.
# DSF plugin processes run in a virtualenv whose PATH may not include
# /usr/bin, so a bare "git" lookup can fail with FileNotFoundError.
GIT_BIN = shutil.which("git")
if GIT_BIN is None:
    for _candidate in ("/usr/bin/git", "/usr/local/bin/git", "/bin/git"):
        if os.path.isfile(_candidate) and os.access(_candidate, os.X_OK):
            GIT_BIN = _candidate
            break
if GIT_BIN is None:
    GIT_BIN = "git"  # last resort — will fail with a clear error at runtime
    logger.warning("Could not locate git binary; commands will likely fail")


def _run(args, cwd=None, git_dir=None):
    """Run a git command and return stdout.

    If *git_dir* is given, ``--git-dir <git_dir>`` is prepended so that
    git finds the repository even when *cwd* is not inside it.
    """
    cmd = [GIT_BIN]
    if git_dir:
        cmd.extend(["--git-dir", git_dir])
    cmd.extend(args)
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"git binary not found at '{GIT_BIN}'. "
            "Ensure git is installed (apt install git)."
        ) from None
    if result.returncode != 0:
        raise RuntimeError(
            f"git {args[0]} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


# --- Reference repository operations ---


def clone(repo_url, dest_path):
    """Clone a reference repository."""
    if os.path.isdir(os.path.join(dest_path, ".git")):
        logger.debug("Reference repo already cloned at %s", dest_path)
        return
    os.makedirs(dest_path, exist_ok=True)
    _run(["clone", repo_url, dest_path])
    logger.info("Cloned reference repository")


def fetch(repo_path):
    """Fetch latest from remote."""
    _run(["fetch", "--all", "--prune"], cwd=repo_path)


def checkout(repo_path, branch):
    """Checkout a specific branch."""
    _run(["checkout", branch], cwd=repo_path)
    logger.info("Switched to branch %s", branch)


def pull(repo_path):
    """Pull latest changes for current branch."""
    _run(["pull", "--ff-only"], cwd=repo_path)


def list_remote_branches(repo_path):
    """List remote branch names (without 'origin/' prefix)."""
    output = _run(["branch", "-r", "--format=%(refname:short)"], cwd=repo_path)
    branches = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("origin/") and not line.endswith("/HEAD"):
            branches.append(line.removeprefix("origin/"))
    return sorted(branches)


def current_branch(repo_path):
    """Get the name of the currently checked-out branch."""
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)


def list_files(repo_path):
    """List all tracked files in the working tree."""
    output = _run(["ls-files"], cwd=repo_path)
    return [f for f in output.splitlines() if f.strip()]


def find_closest_branch(repo_path, version):
    """Find the branch that best matches the given firmware version.

    Strategy: try exact match first, then progressively strip trailing
    version components (e.g., 3.5.1 -> 3.5 -> 3).
    Returns (branch_name, is_exact_match).
    """
    branches = list_remote_branches(repo_path)
    if not branches:
        return None, False

    if version in branches:
        return version, True

    parts = version.split(".")
    while parts:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in branches:
            return candidate, False

    if "main" in branches:
        return "main", False
    if "master" in branches:
        return "master", False

    return branches[0], False


def _backup_cwd(backup_path):
    """Return ``(cwd, git_dir)`` for running git in a backup repo.

    When ``core.worktree`` is configured **and** *backup_path* is nested
    inside the worktree, relative pathspecs (e.g. ``sys``, ``.``) are
    resolved by git from the current working directory — not the worktree
    root.  This causes ``git add -- sys`` to fail with *pathspec did not
    match* because git looks for ``<cwd>/sys`` instead of
    ``<worktree>/sys``.

    To fix this we run git from the worktree root and pass ``--git-dir``
    explicitly so it still finds the repository.  When there is no
    separate worktree, we fall back to the old behaviour.
    """
    git_dir = os.path.join(backup_path, ".git")
    try:
        worktree = _run(["config", "core.worktree"], cwd=backup_path)
    except RuntimeError:
        return backup_path, None
    if worktree:
        return worktree, git_dir
    return backup_path, None


# --- Backup repository operations ---


def init_backup_repo(backup_path, worktree=None):
    """Initialize the backup git repository if it doesn't exist.

    If *worktree* is given, ``core.worktree`` is configured so the repo
    tracks files in-place at the given directory rather than inside
    *backup_path*.  The worktree setting is always (re-)applied on an
    existing repo so that it stays in sync after a daemon restart.
    """
    already_exists = os.path.isdir(os.path.join(backup_path, ".git"))
    if not already_exists:
        os.makedirs(backup_path, exist_ok=True)
        _run(["init"], cwd=backup_path)
        _run(["config", "user.email", "meltingplot-config@localhost"], cwd=backup_path)
        _run(["config", "user.name", "MeltingplotConfig"], cwd=backup_path)
        _run(["config", "commit.gpgsign", "false"], cwd=backup_path)
        logger.debug("Initialized backup repo at %s", backup_path)

    # Always (re-)apply worktree so path changes between restarts are picked up.
    if worktree:
        _run(["config", "core.worktree", worktree], cwd=backup_path)
        logger.debug("Backup repo worktree set to %s", worktree)


def backup_commit(backup_path, message, paths=None, force=False):
    """Stage changes in the backup repo and commit.

    If *paths* is given (a list of directory/file names relative to the
    worktree root), only those paths are staged.  Otherwise all changes
    are staged (``git add -A``).

    If *force* is True, a commit is created even when there are no
    staged changes (``--allow-empty``).  This is used for full backups
    which should always produce a commit.
    """
    cwd, git_dir = _backup_cwd(backup_path)
    if paths:
        _run(["add", "-A", "--"] + list(paths), cwd=cwd, git_dir=git_dir)
    else:
        _run(["add", "-A"], cwd=cwd, git_dir=git_dir)
    # Check if there's anything to commit
    diff_cmd = [GIT_BIN]
    if git_dir:
        diff_cmd.extend(["--git-dir", git_dir])
    diff_cmd.extend(["diff", "--cached", "--quiet"])
    result = subprocess.run(
        diff_cmd,
        cwd=cwd,
        capture_output=True,
    )
    if result.returncode == 0 and not force:
        logger.debug("No changes to commit in backup repo")
        return None
    commit_cmd = ["commit", "-m", message]
    if result.returncode == 0:
        commit_cmd.append("--allow-empty")
    _run(commit_cmd, cwd=cwd, git_dir=git_dir)
    commit_hash = _run(["rev-parse", "HEAD"], cwd=cwd, git_dir=git_dir)
    # Strip the timestamp suffix (after " — ") for cleaner console output;
    # the full message is preserved in the git commit itself.
    display_msg = message.split(" \u2014 ")[0] if " \u2014 " in message else message
    logger.info("Backup: %s", display_msg)
    return commit_hash


def backup_checkout(backup_path, commit_hash, paths=None):
    """Checkout files from a backup commit into the worktree.

    If *paths* is given (relative to worktree), only those paths are
    restored.  Otherwise the full commit is checked out.
    """
    cwd, git_dir = _backup_cwd(backup_path)
    if paths:
        _run(["checkout", commit_hash, "--"] + list(paths), cwd=cwd, git_dir=git_dir)
    else:
        _run(["checkout", commit_hash, "--", "."], cwd=cwd, git_dir=git_dir)
    logger.info("Restored backup %s", commit_hash[:8])


def backup_log(backup_path, max_count=50):
    """Get the backup commit log.

    Returns list of dicts with hash, message, timestamp, filesChanged,
    and isFullBackup.  Full backups (marked with ``[full]`` in the
    commit message) report the total file count instead of only the
    changed-file count, and the ``[full]`` tag is stripped from the
    returned message.
    """
    if not os.path.isdir(os.path.join(backup_path, ".git")):
        return []
    try:
        output = _run(
            [
                "log",
                f"--max-count={max_count}",
                "--format=%H|%s|%aI|%h",
            ],
            cwd=backup_path,
        )
    except RuntimeError:
        return []
    entries = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        full_hash, message, timestamp, short_hash = parts
        is_full = "[full]" in message
        if is_full:
            # Strip [full] tag from displayed message
            message = message.replace(" [full]", "").replace("[full] ", "").replace("[full]", "")
            # Count total files in the snapshot (not just changed)
            try:
                tree = _run(
                    ["ls-tree", "-r", "--name-only", full_hash],
                    cwd=backup_path,
                )
                files_changed = len([f for f in tree.splitlines() if f.strip()])
            except RuntimeError:
                files_changed = 0
        else:
            # Count files changed in this commit
            try:
                stat = _run(
                    ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", full_hash],
                    cwd=backup_path,
                )
                files_changed = len([f for f in stat.splitlines() if f.strip()])
            except RuntimeError:
                files_changed = 0
        entries.append(
            {
                "hash": full_hash,
                "message": message,
                "timestamp": timestamp,
                "filesChanged": files_changed,
                "isFullBackup": is_full,
            }
        )
    return entries


def backup_files_at(backup_path, commit_hash):
    """List files present at a specific backup commit."""
    cwd, git_dir = _backup_cwd(backup_path)
    output = _run(["ls-tree", "-r", "--name-only", commit_hash], cwd=cwd, git_dir=git_dir)
    return [f for f in output.splitlines() if f.strip()]


def backup_changed_files(backup_path, commit_hash):
    """List files changed in a specific backup commit.

    Uses ``git diff-tree --root`` so the root commit (no parent) reports
    all its files as newly added.
    """
    cwd, git_dir = _backup_cwd(backup_path)
    output = _run(
        ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit_hash],
        cwd=cwd, git_dir=git_dir,
    )
    return [f for f in output.splitlines() if f.strip()]


def backup_file_content(backup_path, commit_hash, file_path):
    """Read the content of a file at a specific backup commit."""
    return _run(["show", f"{commit_hash}:{file_path}"], cwd=backup_path)


def backup_archive(backup_path, commit_hash):
    """Create a ZIP archive of a backup commit. Returns bytes."""
    cwd, git_dir = _backup_cwd(backup_path)
    cmd = [GIT_BIN]
    if git_dir:
        cmd.extend(["--git-dir", git_dir])
    cmd.extend(["archive", "--format=zip", commit_hash])
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git archive failed: {result.stderr.decode().strip()}")
    return result.stdout


def backup_delete(backup_path, commit_hash):
    """Delete a specific backup commit from the history.

    - If the commit is HEAD: ``git reset --hard HEAD~1``
    - If the commit is in the middle: ``git rebase --onto <parent> <hash>``
    - If the commit is the only one or the root with descendants: error.
    """
    head = _run(["rev-parse", "HEAD"], cwd=backup_path)

    # Check if this commit has a parent.
    try:
        _run(["rev-parse", f"{commit_hash}^"], cwd=backup_path)
        has_parent = True
    except RuntimeError:
        has_parent = False

    is_head = head == commit_hash or head.startswith(commit_hash) or commit_hash.startswith(head)

    if is_head:
        if not has_parent:
            raise RuntimeError("Cannot delete the only backup")
        _run(["reset", "--hard", "HEAD~1"], cwd=backup_path)
        logger.info("Deleted backup %s", commit_hash[:8])
    else:
        if not has_parent:
            raise RuntimeError(
                "Cannot delete the oldest backup while newer ones exist. "
                "Delete newer backups first."
            )
        _run(
            ["rebase", "--onto", f"{commit_hash}^", commit_hash, "-X", "theirs"],
            cwd=backup_path,
        )
        logger.info("Deleted backup %s", commit_hash[:8])
