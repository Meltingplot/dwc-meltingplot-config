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


def _run(args, cwd=None):
    """Run a git command and return stdout."""
    cmd = [GIT_BIN] + args
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
        logger.info("Reference repo already cloned at %s", dest_path)
        return
    os.makedirs(dest_path, exist_ok=True)
    _run(["clone", repo_url, dest_path])
    logger.info("Cloned %s into %s", repo_url, dest_path)


def fetch(repo_path):
    """Fetch latest from remote."""
    _run(["fetch", "--all", "--prune"], cwd=repo_path)


def checkout(repo_path, branch):
    """Checkout a specific branch."""
    _run(["checkout", branch], cwd=repo_path)
    logger.info("Checked out branch %s", branch)


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
        logger.info("Initialized backup repo at %s", backup_path)

    # Always (re-)apply worktree so path changes between restarts are picked up.
    if worktree:
        _run(["config", "core.worktree", worktree], cwd=backup_path)
        logger.info("Backup repo worktree set to %s", worktree)


def backup_commit(backup_path, message, paths=None):
    """Stage changes in the backup repo and commit.

    If *paths* is given (a list of directory/file names relative to the
    worktree root), only those paths are staged.  Otherwise all changes
    are staged (``git add -A``).
    """
    if paths:
        _run(["add", "-A", "--"] + list(paths), cwd=backup_path)
    else:
        _run(["add", "-A"], cwd=backup_path)
    # Check if there's anything to commit
    result = subprocess.run(
        [GIT_BIN, "diff", "--cached", "--quiet"],
        cwd=backup_path,
        capture_output=True,
    )
    if result.returncode == 0:
        logger.info("No changes to commit in backup repo")
        return None
    output = _run(["commit", "-m", message], cwd=backup_path)
    commit_hash = _run(["rev-parse", "HEAD"], cwd=backup_path)
    logger.info("Backup commit: %s (%s)", commit_hash[:8], message)
    return commit_hash


def backup_checkout(backup_path, commit_hash, paths=None):
    """Checkout files from a backup commit into the worktree.

    If *paths* is given (relative to worktree), only those paths are
    restored.  Otherwise the full commit is checked out.
    """
    if paths:
        _run(["checkout", commit_hash, "--"] + list(paths), cwd=backup_path)
    else:
        _run(["checkout", commit_hash, "--", "."], cwd=backup_path)
    logger.info("Checked out backup %s", commit_hash[:8])


def backup_log(backup_path, max_count=50):
    """Get the backup commit log.

    Returns list of dicts with hash, message, timestamp, filesChanged.
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
            }
        )
    return entries


def backup_files_at(backup_path, commit_hash):
    """List files present at a specific backup commit."""
    output = _run(["ls-tree", "-r", "--name-only", commit_hash], cwd=backup_path)
    return [f for f in output.splitlines() if f.strip()]


def backup_file_content(backup_path, commit_hash, file_path):
    """Read the content of a file at a specific backup commit."""
    return _run(["show", f"{commit_hash}:{file_path}"], cwd=backup_path)


def backup_archive(backup_path, commit_hash):
    """Create a ZIP archive of a backup commit. Returns bytes."""
    cmd = [GIT_BIN, "archive", "--format=zip", commit_hash]
    result = subprocess.run(
        cmd,
        cwd=backup_path,
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
        logger.info("Deleted backup (HEAD reset): %s", commit_hash[:8])
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
        logger.info("Deleted backup (rebased): %s", commit_hash[:8])
