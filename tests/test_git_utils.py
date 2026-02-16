"""Tests for git_utils.py — git operations wrapper."""

import os
import subprocess
import tempfile

import pytest

import git_utils


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary bare git repo with branches, and a local clone."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    # Allow pushes to HEAD on bare repo
    subprocess.run(["git", "config", "receive.denyCurrentBranch", "ignore"], cwd=str(bare), check=True, capture_output=True)

    # Clone it, add a file, push to main
    clone_dir = tmp_path / "clone"
    subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "gpg.format", "openpgp"], cwd=str(clone_dir), check=True, capture_output=True)

    # Create sys/ directory with a config file
    sys_dir = clone_dir / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1 Z2\n")
    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(clone_dir), check=True, capture_output=True)
    # Ensure branch is named 'main' regardless of git default
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    # Create version branches
    for branch in ["3.5", "3.5.0", "3.5.1"]:
        subprocess.run(["git", "checkout", "-b", branch], cwd=str(clone_dir), check=True, capture_output=True)
        (sys_dir / "config.g").write_text(f"G28\nM584 X0 Y1 Z2\n; version {branch}\n")
        subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"version {branch}"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", branch], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    return {"bare": str(bare), "clone": str(clone_dir)}


@pytest.fixture
def backup_repo(tmp_path):
    """Create a temporary backup git repo."""
    backup_dir = tmp_path / "backups"
    git_utils.init_backup_repo(str(backup_dir))
    return str(backup_dir)


class TestCloneAndFetch:
    def test_clone_creates_repo(self, tmp_repo, tmp_path):
        dest = str(tmp_path / "new_clone")
        git_utils.clone(tmp_repo["bare"], dest)
        assert os.path.isdir(os.path.join(dest, ".git"))

    def test_clone_skips_if_exists(self, tmp_repo):
        # Cloning again should not fail
        git_utils.clone(tmp_repo["bare"], tmp_repo["clone"])

    def test_fetch_succeeds(self, tmp_repo):
        git_utils.fetch(tmp_repo["clone"])


class TestBranches:
    def test_list_remote_branches(self, tmp_repo):
        branches = git_utils.list_remote_branches(tmp_repo["clone"])
        assert "main" in branches
        assert "3.5" in branches
        assert "3.5.0" in branches
        assert "3.5.1" in branches

    def test_current_branch(self, tmp_repo):
        branch = git_utils.current_branch(tmp_repo["clone"])
        assert branch == "main"

    def test_checkout(self, tmp_repo):
        git_utils.checkout(tmp_repo["clone"], "3.5.0")
        assert git_utils.current_branch(tmp_repo["clone"]) == "3.5.0"


class TestFindClosestBranch:
    def test_exact_match(self, tmp_repo):
        branch, exact = git_utils.find_closest_branch(tmp_repo["clone"], "3.5.1")
        assert branch == "3.5.1"
        assert exact is True

    def test_fallback_to_minor(self, tmp_repo):
        branch, exact = git_utils.find_closest_branch(tmp_repo["clone"], "3.5.2")
        assert branch == "3.5"
        assert exact is False

    def test_fallback_to_main(self, tmp_repo):
        branch, exact = git_utils.find_closest_branch(tmp_repo["clone"], "9.9.9")
        assert branch == "main"
        assert exact is False

    def test_no_branches(self, tmp_path):
        """Empty repo with no remote branches returns None."""
        repo = str(tmp_path / "empty")
        os.makedirs(repo)
        subprocess.run(["git", "init", repo], check=True, capture_output=True)
        branch, exact = git_utils.find_closest_branch(repo, "1.0")
        assert branch is None
        assert exact is False


class TestListFiles:
    def test_lists_tracked_files(self, tmp_repo):
        files = git_utils.list_files(tmp_repo["clone"])
        assert "sys/config.g" in files


class TestBackupRepo:
    def test_init_creates_repo(self, backup_repo):
        assert os.path.isdir(os.path.join(backup_repo, ".git"))

    def test_init_idempotent(self, backup_repo):
        git_utils.init_backup_repo(backup_repo)
        assert os.path.isdir(os.path.join(backup_repo, ".git"))

    def test_commit_and_log(self, backup_repo):
        # Write a file and commit
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        commit_hash = git_utils.backup_commit(backup_repo, "test backup")
        assert commit_hash is not None
        assert len(commit_hash) == 40

        log = git_utils.backup_log(backup_repo)
        assert len(log) == 1
        assert log[0]["message"] == "test backup"
        assert log[0]["hash"] == commit_hash
        assert log[0]["filesChanged"] == 1

    def test_commit_no_changes(self, backup_repo):
        # First make at least one commit so HEAD exists
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        git_utils.backup_commit(backup_repo, "initial")
        # Second commit with no changes
        result = git_utils.backup_commit(backup_repo, "no-op")
        assert result is None

    def test_files_at_commit(self, backup_repo):
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        commit_hash = git_utils.backup_commit(backup_repo, "snapshot")
        files = git_utils.backup_files_at(backup_repo, commit_hash)
        assert "sys/config.g" in files

    def test_file_content_at_commit(self, backup_repo):
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\nM584 X0\n")
        commit_hash = git_utils.backup_commit(backup_repo, "snapshot")
        content = git_utils.backup_file_content(backup_repo, commit_hash, "sys/config.g")
        assert content == "G28\nM584 X0"

    def test_archive(self, backup_repo):
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        commit_hash = git_utils.backup_commit(backup_repo, "archive test")
        archive_bytes = git_utils.backup_archive(backup_repo, commit_hash)
        # ZIP files start with PK
        assert archive_bytes[:2] == b"PK"

    def test_empty_log(self, tmp_path):
        empty = str(tmp_path / "nonexistent")
        assert git_utils.backup_log(empty) == []
