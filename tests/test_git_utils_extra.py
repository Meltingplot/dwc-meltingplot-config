"""Tests for git_utils.py — pull, _run error handling, and edge cases."""

import os
import subprocess

import pytest

import git_utils


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary bare git repo with a local clone."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "receive.denyCurrentBranch", "ignore"],
        cwd=str(bare), check=True, capture_output=True,
    )

    clone_dir = tmp_path / "clone"
    subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "gpg.format", "openpgp"], cwd=str(clone_dir), check=True, capture_output=True)

    sys_dir = clone_dir / "sys"
    sys_dir.mkdir()
    (sys_dir / "config.g").write_text("G28\n")
    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

    return {"bare": str(bare), "clone": str(clone_dir)}


# --- pull() ---


class TestPull:
    def test_pull_succeeds(self, tmp_repo):
        """Pull on a clean, up-to-date repo should succeed."""
        git_utils.pull(tmp_repo["clone"])

    def test_pull_gets_new_changes(self, tmp_repo, tmp_path):
        """Pull should bring in new commits pushed from another clone."""
        # Create a second clone, make a commit, push
        clone2 = str(tmp_path / "clone2")
        subprocess.run(["git", "clone", tmp_repo["bare"], clone2], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=clone2, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=clone2, check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=clone2, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=clone2, check=True, capture_output=True)
        sys_dir2 = os.path.join(clone2, "sys")
        os.makedirs(sys_dir2, exist_ok=True)
        config_file = os.path.join(sys_dir2, "config.g")
        with open(config_file, "w") as f:
            f.write("G28\nM584 X0\n")
        subprocess.run(["git", "add", "-A"], cwd=clone2, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "update"], cwd=clone2, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone2, check=True, capture_output=True)

        # Now pull in original clone
        git_utils.fetch(tmp_repo["clone"])
        git_utils.pull(tmp_repo["clone"])

        # Verify new content
        config_path = os.path.join(tmp_repo["clone"], "sys", "config.g")
        with open(config_path) as f:
            content = f.read()
        assert "M584 X0" in content


# --- _run() error handling ---


class TestRunErrors:
    def test_run_raises_on_nonzero_exit(self, tmp_path):
        """_run should raise RuntimeError when git command fails."""
        # tmp_path exists but is not a git repo, so git log fails
        with pytest.raises(RuntimeError, match="failed"):
            git_utils._run(["log", "--max-count=1"], cwd=str(tmp_path))

    def test_run_raises_on_invalid_command(self, tmp_path):
        """_run should raise RuntimeError for invalid git subcommand."""
        with pytest.raises(RuntimeError):
            git_utils._run(["not-a-real-command"], cwd=str(tmp_path))

    def test_run_includes_stderr_in_error(self, tmp_path):
        """Error message should include stderr output."""
        try:
            git_utils._run(["log", "--max-count=1"], cwd=str(tmp_path))
            pytest.fail("Expected RuntimeError")
        except RuntimeError as e:
            error_msg = str(e)
            assert "git log failed" in error_msg


# --- backup_archive error ---


class TestBackupArchiveError:
    def test_archive_invalid_commit_raises(self, tmp_path):
        """Archive with invalid commit hash should raise RuntimeError."""
        backup_dir = str(tmp_path / "backup")
        git_utils.init_backup_repo(backup_dir)

        # Write a file and commit so repo is not empty
        sys_dir = os.path.join(backup_dir, "sys")
        os.makedirs(sys_dir)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        git_utils.backup_commit(backup_dir, "initial")

        with pytest.raises(RuntimeError, match="git archive failed"):
            git_utils.backup_archive(backup_dir, "0000000000000000000000000000000000000000")


# --- backup_log edge cases ---


class TestBackupLogEdgeCases:
    def test_backup_log_max_count(self, tmp_path):
        """backup_log respects max_count parameter."""
        backup_dir = str(tmp_path / "backup")
        git_utils.init_backup_repo(backup_dir)

        sys_dir = os.path.join(backup_dir, "sys")
        os.makedirs(sys_dir)

        # Create 5 commits
        for i in range(5):
            with open(os.path.join(sys_dir, "config.g"), "w") as f:
                f.write(f"version {i}\n")
            git_utils.backup_commit(backup_dir, f"commit {i}")

        log = git_utils.backup_log(backup_dir, max_count=3)
        assert len(log) == 3

    def test_backup_log_returns_newest_first(self, tmp_path):
        """backup_log should return commits in reverse chronological order."""
        backup_dir = str(tmp_path / "backup")
        git_utils.init_backup_repo(backup_dir)

        sys_dir = os.path.join(backup_dir, "sys")
        os.makedirs(sys_dir)

        for i in range(3):
            with open(os.path.join(sys_dir, "config.g"), "w") as f:
                f.write(f"version {i}\n")
            git_utils.backup_commit(backup_dir, f"commit {i}")

        log = git_utils.backup_log(backup_dir)
        assert log[0]["message"] == "commit 2"
        assert log[2]["message"] == "commit 0"

    def test_backup_log_empty_repo_with_git_dir(self, tmp_path):
        """backup_log on repo with no commits returns empty list."""
        backup_dir = str(tmp_path / "backup")
        git_utils.init_backup_repo(backup_dir)
        log = git_utils.backup_log(backup_dir)
        assert log == []


# --- find_closest_branch edge cases ---


class TestFindClosestBranchExtra:
    def test_fallback_to_master(self, tmp_path):
        """When no version match and no 'main' branch, falls back to 'master'."""
        bare = tmp_path / "bare.git"
        bare.mkdir()
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

        clone_dir = tmp_path / "clone"
        subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)

        (clone_dir / "file.txt").write_text("content")
        subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "master"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "master"], cwd=str(clone_dir), check=True, capture_output=True)

        branch, exact = git_utils.find_closest_branch(str(clone_dir), "9.9.9")
        assert branch == "master"
        assert exact is False

    def test_single_version_component(self, tmp_path):
        """Version with single component (e.g., '3') tries exact then falls back."""
        bare = tmp_path / "bare.git"
        bare.mkdir()
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

        clone_dir = tmp_path / "clone"
        subprocess.run(["git", "clone", str(bare), str(clone_dir)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(clone_dir), check=True, capture_output=True)

        (clone_dir / "file.txt").write_text("content")
        subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_dir), check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone_dir), check=True, capture_output=True)

        branch, exact = git_utils.find_closest_branch(str(clone_dir), "3")
        assert branch == "main"
        assert exact is False
