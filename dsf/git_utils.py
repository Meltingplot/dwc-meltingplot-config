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


def init_backup_repo(backup_path):
    """Initialize the backup git repository if it doesn't exist."""
    if os.path.isdir(os.path.join(backup_path, ".git")):
        return
    os.makedirs(backup_path, exist_ok=True)
    _run(["init"], cwd=backup_path)
    _run(["config", "user.email", "meltingplot-config@localhost"], cwd=backup_path)
    _run(["config", "user.name", "MeltingplotConfig"], cwd=backup_path)
    _run(["config", "commit.gpgsign", "false"], cwd=backup_path)
    logger.info("Initialized backup repo at %s", backup_path)


def backup_commit(backup_path, message):
    """Stage all changes in the backup repo and commit."""
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
