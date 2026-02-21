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

    def test_changed_files_at_commit(self, backup_repo):
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        commit1 = git_utils.backup_commit(backup_repo, "first")
        # Root commit: all files are "changed" (added)
        changed = git_utils.backup_changed_files(backup_repo, commit1)
        assert "sys/config.g" in changed

        # Modify a file and add another
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\nM906 X800\n")
        with open(os.path.join(sys_dir, "homex.g"), "w") as f:
            f.write("G1 X0\n")
        commit2 = git_utils.backup_commit(backup_repo, "second")
        changed2 = git_utils.backup_changed_files(backup_repo, commit2)
        assert "sys/config.g" in changed2
        assert "sys/homex.g" in changed2

    def test_changed_files_only_modified(self, backup_repo):
        """Only files changed in the specific commit are returned."""
        sys_dir = os.path.join(backup_repo, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\n")
        with open(os.path.join(sys_dir, "homex.g"), "w") as f:
            f.write("G1 X0\n")
        git_utils.backup_commit(backup_repo, "initial")

        # Only modify config.g
        with open(os.path.join(sys_dir, "config.g"), "w") as f:
            f.write("G28\nM906 X800\n")
        commit2 = git_utils.backup_commit(backup_repo, "update config only")
        changed = git_utils.backup_changed_files(backup_repo, commit2)
        assert "sys/config.g" in changed
        assert "sys/homex.g" not in changed

    def test_empty_log(self, tmp_path):
        empty = str(tmp_path / "nonexistent")
        assert git_utils.backup_log(empty) == []


class TestBackupRepoWorktree:
    """Backup repo with core.worktree pointing at a separate directory."""

    @pytest.fixture
    def worktree_env(self, tmp_path):
        """Create a backup repo with a separate worktree directory."""
        worktree = tmp_path / "printer_sd"
        worktree.mkdir()
        (worktree / "sys").mkdir()
        (worktree / "sys" / "config.g").write_text("G28\n")
        (worktree / "macros").mkdir()
        (worktree / "macros" / "start.g").write_text("T0\n")

        backup_dir = tmp_path / "backups"
        git_utils.init_backup_repo(str(backup_dir), worktree=str(worktree))
        return {"backup": str(backup_dir), "worktree": str(worktree)}

    def test_init_sets_worktree(self, worktree_env):
        result = subprocess.run(
            ["git", "config", "core.worktree"],
            cwd=worktree_env["backup"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == worktree_env["worktree"]

    def test_commit_with_paths(self, worktree_env):
        commit = git_utils.backup_commit(
            worktree_env["backup"], "first backup", paths=["sys", "macros"]
        )
        assert commit is not None
        files = git_utils.backup_files_at(worktree_env["backup"], commit)
        assert "sys/config.g" in files
        assert "macros/start.g" in files

    def test_commit_selective_paths(self, worktree_env):
        """Only the specified paths are staged."""
        commit = git_utils.backup_commit(
            worktree_env["backup"], "sys only", paths=["sys"]
        )
        assert commit is not None
        files = git_utils.backup_files_at(worktree_env["backup"], commit)
        assert "sys/config.g" in files
        assert "macros/start.g" not in files

    def test_worktree_tracks_changes(self, worktree_env):
        """Changes in the worktree directory are detected by the backup repo."""
        git_utils.backup_commit(
            worktree_env["backup"], "initial", paths=["sys", "macros"]
        )
        # Modify a file in the worktree
        wt = worktree_env["worktree"]
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("G28\nM906 X800\n")
        commit = git_utils.backup_commit(
            worktree_env["backup"], "updated", paths=["sys"]
        )
        assert commit is not None
        content = git_utils.backup_file_content(
            worktree_env["backup"], commit, "sys/config.g"
        )
        assert "M906 X800" in content

    def test_changed_files_with_worktree(self, worktree_env):
        """backup_changed_files works with separate worktree."""
        commit = git_utils.backup_commit(
            worktree_env["backup"], "initial", paths=["sys", "macros"]
        )
        changed = git_utils.backup_changed_files(worktree_env["backup"], commit)
        assert "sys/config.g" in changed
        assert "macros/start.g" in changed

        # Modify only one file
        wt = worktree_env["worktree"]
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("G28\nM906 X800\n")
        commit2 = git_utils.backup_commit(
            worktree_env["backup"], "update sys", paths=["sys", "macros"]
        )
        changed2 = git_utils.backup_changed_files(worktree_env["backup"], commit2)
        assert "sys/config.g" in changed2
        assert "macros/start.g" not in changed2

    def test_init_idempotent_updates_worktree(self, worktree_env):
        """Re-init on existing repo updates core.worktree."""
        new_wt = worktree_env["worktree"] + "_new"
        os.makedirs(new_wt, exist_ok=True)
        git_utils.init_backup_repo(worktree_env["backup"], worktree=new_wt)
        result = subprocess.run(
            ["git", "config", "core.worktree"],
            cwd=worktree_env["backup"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == new_wt

    def test_backup_includes_subfolders(self, worktree_env):
        """Files in subdirectories are tracked."""
        wt = worktree_env["worktree"]
        os.makedirs(os.path.join(wt, "sys", "sub"), exist_ok=True)
        with open(os.path.join(wt, "sys", "sub", "deep.g"), "w") as f:
            f.write("M999\n")
        commit = git_utils.backup_commit(
            worktree_env["backup"], "deep", paths=["sys"]
        )
        files = git_utils.backup_files_at(worktree_env["backup"], commit)
        assert "sys/sub/deep.g" in files


class TestBackupNestedWorktree:
    """Regression: backup repo nested inside its own worktree.

    In production the layout is:
        worktree  = /opt/dsf/sd
        backup    = /opt/dsf/sd/MeltingplotConfig/backups

    When backup_path is a child of the worktree, git resolves relative
    pathspecs from cwd (the backup dir), not the worktree root.  This
    caused 'git add -- sys' to fail with 'pathspec did not match'.
    """

    @pytest.fixture
    def nested_env(self, tmp_path):
        """Mimic the production layout: backup dir inside the worktree."""
        worktree = tmp_path / "sd"
        worktree.mkdir()
        (worktree / "sys").mkdir()
        (worktree / "sys" / "config.g").write_text("G28\n")
        (worktree / "macros").mkdir()
        (worktree / "macros" / "start.g").write_text("T0\n")

        # Backup dir is a child of the worktree — this is the production layout
        backup_dir = worktree / "MeltingplotConfig" / "backups"
        git_utils.init_backup_repo(str(backup_dir), worktree=str(worktree))
        return {"backup": str(backup_dir), "worktree": str(worktree)}

    def test_commit_with_paths(self, nested_env):
        """git add with relative paths succeeds when backup is inside worktree."""
        commit = git_utils.backup_commit(
            nested_env["backup"], "backup", paths=["sys", "macros"]
        )
        assert commit is not None
        files = git_utils.backup_files_at(nested_env["backup"], commit)
        assert "sys/config.g" in files
        assert "macros/start.g" in files

    def test_commit_selective_paths(self, nested_env):
        """Only the specified paths are staged."""
        commit = git_utils.backup_commit(
            nested_env["backup"], "sys only", paths=["sys"]
        )
        assert commit is not None
        files = git_utils.backup_files_at(nested_env["backup"], commit)
        assert "sys/config.g" in files
        assert "macros/start.g" not in files

    def test_checkout_restores_all(self, nested_env):
        """backup_checkout without paths restores the full commit."""
        wt = nested_env["worktree"]
        commit = git_utils.backup_commit(
            nested_env["backup"], "snap", paths=["sys"]
        )
        # Modify file
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("changed\n")

        git_utils.backup_checkout(nested_env["backup"], commit)
        assert open(os.path.join(wt, "sys", "config.g")).read() == "G28\n"

    def test_checkout_with_paths(self, nested_env):
        """backup_checkout with explicit paths restores only those paths."""
        wt = nested_env["worktree"]
        git_utils.backup_commit(
            nested_env["backup"], "snap", paths=["sys", "macros"]
        )
        # Modify both
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("new sys\n")
        with open(os.path.join(wt, "macros", "start.g"), "w") as f:
            f.write("new macro\n")

        # Get the snapshot and restore only sys
        log = git_utils.backup_log(nested_env["backup"])
        git_utils.backup_checkout(
            nested_env["backup"], log[0]["hash"], paths=["sys"]
        )
        assert open(os.path.join(wt, "sys", "config.g")).read() == "G28\n"
        assert open(os.path.join(wt, "macros", "start.g")).read() == "new macro\n"

    def test_worktree_tracks_changes(self, nested_env):
        """Successive commits detect worktree changes."""
        git_utils.backup_commit(
            nested_env["backup"], "initial", paths=["sys"]
        )
        wt = nested_env["worktree"]
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("G28\nM906 X800\n")
        commit = git_utils.backup_commit(
            nested_env["backup"], "updated", paths=["sys"]
        )
        assert commit is not None
        content = git_utils.backup_file_content(
            nested_env["backup"], commit, "sys/config.g"
        )
        assert "M906 X800" in content


class TestBackupCheckout:
    """Tests for backup_checkout — restoring files from a commit."""

    @pytest.fixture
    def checkout_env(self, tmp_path):
        worktree = tmp_path / "printer_sd"
        worktree.mkdir()
        (worktree / "sys").mkdir()
        (worktree / "sys" / "config.g").write_text("original\n")

        backup_dir = tmp_path / "backups"
        git_utils.init_backup_repo(str(backup_dir), worktree=str(worktree))
        commit = git_utils.backup_commit(
            str(backup_dir), "snapshot", paths=["sys"]
        )
        return {
            "backup": str(backup_dir),
            "worktree": str(worktree),
            "snapshot_hash": commit,
        }

    def test_checkout_restores_file(self, checkout_env):
        wt = checkout_env["worktree"]
        # Modify file after snapshot
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("changed\n")
        assert "changed" in open(os.path.join(wt, "sys", "config.g")).read()

        git_utils.backup_checkout(
            checkout_env["backup"], checkout_env["snapshot_hash"]
        )
        assert open(os.path.join(wt, "sys", "config.g")).read() == "original\n"

    def test_checkout_with_paths(self, checkout_env):
        wt = checkout_env["worktree"]
        # Add a second dir and commit
        os.makedirs(os.path.join(wt, "macros"), exist_ok=True)
        with open(os.path.join(wt, "macros", "start.g"), "w") as f:
            f.write("T0\n")
        git_utils.backup_commit(
            checkout_env["backup"], "with macros", paths=["sys", "macros"]
        )
        # Modify both
        with open(os.path.join(wt, "sys", "config.g"), "w") as f:
            f.write("new sys\n")
        with open(os.path.join(wt, "macros", "start.g"), "w") as f:
            f.write("new macro\n")

        # Checkout only the snapshot (which has only sys/)
        git_utils.backup_checkout(
            checkout_env["backup"], checkout_env["snapshot_hash"], paths=["sys"]
        )
        # sys restored, macros untouched
        assert open(os.path.join(wt, "sys", "config.g")).read() == "original\n"
        assert open(os.path.join(wt, "macros", "start.g")).read() == "new macro\n"


class TestBackupDelete:
    """Tests for backup_delete — removing backup commits."""

    @pytest.fixture
    def delete_env(self, tmp_path):
        worktree = tmp_path / "printer_sd"
        worktree.mkdir()
        (worktree / "sys").mkdir()
        (worktree / "sys" / "config.g").write_text("v1\n")

        backup_dir = tmp_path / "backups"
        git_utils.init_backup_repo(str(backup_dir), worktree=str(worktree))
        c1 = git_utils.backup_commit(str(backup_dir), "first", paths=["sys"])

        (worktree / "sys" / "config.g").write_text("v2\n")
        c2 = git_utils.backup_commit(str(backup_dir), "second", paths=["sys"])

        (worktree / "sys" / "config.g").write_text("v3\n")
        c3 = git_utils.backup_commit(str(backup_dir), "third", paths=["sys"])

        return {
            "backup": str(backup_dir),
            "worktree": str(worktree),
            "commits": [c1, c2, c3],
        }

    def test_delete_head_commit(self, delete_env):
        """Deleting HEAD removes the most recent commit."""
        commits = delete_env["commits"]
        git_utils.backup_delete(delete_env["backup"], commits[2])

        log = git_utils.backup_log(delete_env["backup"])
        hashes = [e["hash"] for e in log]
        assert commits[2] not in hashes
        assert commits[1] in hashes
        assert commits[0] in hashes

    def test_delete_middle_commit(self, delete_env):
        """Deleting a non-HEAD commit rebases descendants."""
        commits = delete_env["commits"]
        git_utils.backup_delete(delete_env["backup"], commits[1])

        log = git_utils.backup_log(delete_env["backup"])
        hashes = [e["hash"] for e in log]
        assert commits[1] not in hashes
        # Root commit should still exist
        assert commits[0] in hashes
        # Should have 2 commits remaining
        assert len(log) == 2

    def test_delete_only_commit_raises(self, tmp_path):
        """Cannot delete the only backup commit."""
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / "sys").mkdir()
        (worktree / "sys" / "config.g").write_text("v1\n")

        backup_dir = tmp_path / "backups"
        git_utils.init_backup_repo(str(backup_dir), worktree=str(worktree))
        c = git_utils.backup_commit(str(backup_dir), "only", paths=["sys"])

        with pytest.raises(RuntimeError, match="Cannot delete the only backup"):
            git_utils.backup_delete(str(backup_dir), c)

    def test_delete_root_with_descendants_raises(self, delete_env):
        """Cannot delete the oldest backup while newer ones exist."""
        commits = delete_env["commits"]
        with pytest.raises(RuntimeError, match="Cannot delete the oldest backup"):
            git_utils.backup_delete(delete_env["backup"], commits[0])

    def test_delete_preserves_remaining_history(self, delete_env):
        """After deleting HEAD, the remaining log messages are intact."""
        commits = delete_env["commits"]
        git_utils.backup_delete(delete_env["backup"], commits[2])

        log = git_utils.backup_log(delete_env["backup"])
        messages = [e["message"] for e in log]
        assert "second" in messages
        assert "first" in messages
        assert "third" not in messages
