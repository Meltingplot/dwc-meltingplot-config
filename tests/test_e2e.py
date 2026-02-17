"""End-to-end tests — daemon handlers wired to real ConfigManager.

Tests the complete backend chain without mocking ConfigManager:
  daemon handler → config_manager → git_utils → real filesystem

Only the DSF CommandConnection is mocked (it isn't available outside the SBC).
Everything else is real: git repos, temp filesystems, diff engine, hunk apply.
"""

import importlib.util
import json
import os
import subprocess
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from config_manager import ConfigManager


# ---------------------------------------------------------------------------
# DSF module mocks (required because dsf-python isn't installed in test env)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_dsf_modules(monkeypatch):
    """Mock the dsf library modules so the daemon can be imported."""
    dsf_mod = types.ModuleType("dsf")
    dsf_connections = types.ModuleType("dsf.connections")
    dsf_commands = types.ModuleType("dsf.commands")
    dsf_commands_code = types.ModuleType("dsf.commands.code")
    dsf_http = types.ModuleType("dsf.http")
    dsf_object_model = types.ModuleType("dsf.object_model")

    dsf_connections.CommandConnection = MagicMock
    dsf_connections.InterceptConnection = MagicMock
    dsf_commands_code.CodeResult = MagicMock

    class FakeHttpEndpointType:
        GET = "GET"
        POST = "POST"

    class FakeHttpResponseType:
        StatusCode = "StatusCode"
        PlainText = "PlainText"
        JSON = "JSON"
        File = "File"
        URI = "URI"

    dsf_http.HttpEndpointConnection = MagicMock
    dsf_http.HttpResponseType = FakeHttpResponseType
    dsf_object_model.HttpEndpointType = FakeHttpEndpointType

    monkeypatch.setitem(sys.modules, "dsf", dsf_mod)
    monkeypatch.setitem(sys.modules, "dsf.connections", dsf_connections)
    monkeypatch.setitem(sys.modules, "dsf.commands", dsf_commands)
    monkeypatch.setitem(sys.modules, "dsf.commands.code", dsf_commands_code)
    monkeypatch.setitem(sys.modules, "dsf.http", dsf_http)
    monkeypatch.setitem(sys.modules, "dsf.object_model", dsf_object_model)


def _import_daemon():
    """Import (or reimport) the daemon module."""
    spec = importlib.util.spec_from_file_location(
        "daemon_mod",
        os.path.join(os.path.dirname(__file__), "..", "dsf", "meltingplot-config-daemon.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures — real git repos and temp filesystem
# ---------------------------------------------------------------------------

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

    # 3.5 branch: higher motor current
    subprocess.run(["git", "checkout", "-b", "3.5"], cwd=str(clone_dir), check=True, capture_output=True)
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\nM906 X1000 Y1000\n")
    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "version 3.5 - higher current"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "3.5"], cwd=str(clone_dir), check=True, capture_output=True)

    # 3.6 branch: new macro + updated current
    subprocess.run(["git", "checkout", "-b", "3.6"], cwd=str(clone_dir), check=True, capture_output=True)
    (sys_dir / "config.g").write_text("G28\nM584 X0 Y1\nM906 X1200 Y1200\n")
    (macros_dir / "heat_bed.g").write_text("M140 S60\nM116 P0\n")
    subprocess.run(["git", "add", "-A"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "version 3.6 - higher current + heat macro"], cwd=str(clone_dir), check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "3.6"], cwd=str(clone_dir), check=True, capture_output=True)

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
def e2e_env(tmp_path, reference_repo, printer_fs):
    """Wire daemon handlers to a real ConfigManager with real git + filesystem."""
    ref_dir = str(tmp_path / "reference")
    backup_dir = str(tmp_path / "backups")

    resolved = {
        "0:/sys/": str(printer_fs / "sys") + "/",
        "0:/macros/": str(printer_fs / "macros") + "/",
        "0:/filaments/": str(printer_fs / "filaments") + "/",
    }

    # Mock cmd with plugin data storage that handlers can read/write
    plugin_data = {
        "status": "not_configured",
        "detectedFirmwareVersion": "3.5",
        "activeBranch": "",
        "referenceRepoUrl": reference_repo,
        "lastSyncTimestamp": "",
        "firmwareBranchOverride": "",
    }
    cmd = MagicMock()
    cmd.get_object_model.return_value = SimpleNamespace(
        plugins={"MeltingplotConfig": SimpleNamespace(data=plugin_data)}
    )

    def _set_plugin_data(plugin_id, key, value):
        plugin_data[key] = value
    cmd.set_plugin_data.side_effect = _set_plugin_data

    daemon = _import_daemon()

    with (
        patch("config_manager.REFERENCE_DIR", ref_dir),
        patch("config_manager.BACKUP_DIR", backup_dir),
        patch("config_manager.PLUGIN_DIR", str(tmp_path)),
    ):
        manager = ConfigManager(
            dsf_command_connection=cmd,
            resolved_dirs=resolved,
        )
        yield {
            "daemon": daemon,
            "cmd": cmd,
            "manager": manager,
            "plugin_data": plugin_data,
            "repo_url": reference_repo,
            "printer_fs": printer_fs,
        }


def _body(resp):
    """Parse the JSON body from a daemon response."""
    return json.loads(resp["body"])


# ---------------------------------------------------------------------------
# Tests — full handler → ConfigManager → git → filesystem chain
# ---------------------------------------------------------------------------

class TestE2EStatusFlow:
    """Test the status endpoint with real plugin data."""

    def test_initial_status(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        resp = d.handle_status(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        assert body["status"] == "not_configured"
        assert body["detectedFirmwareVersion"] == "3.5"
        assert body["branches"] == []

    def test_status_after_sync(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})
        resp = d.handle_status(cmd, mgr, "", {})
        body = _body(resp)
        assert body["status"] == "up_to_date"
        assert body["activeBranch"] == "3.5"
        assert "main" in body["branches"]
        assert "3.5" in body["branches"]
        assert body["lastSyncTimestamp"] != ""


class TestE2ESyncDiffApplyFlow:
    """Full flow: sync → diff → apply → verify."""

    def test_sync_returns_branch_and_updates_plugin_data(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        resp = d.handle_sync(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        assert body["activeBranch"] == "3.5"
        assert body["exact"] is True
        # Plugin data should be updated via set_plugin_data
        assert e2e_env["plugin_data"]["activeBranch"] == "3.5"
        assert e2e_env["plugin_data"]["status"] == "up_to_date"

    def test_diff_all_after_sync_shows_modified(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_diff(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        files = body["files"]
        statuses = {f["file"]: f["status"] for f in files}
        assert statuses["sys/config.g"] == "modified"
        assert statuses.get("sys/homex.g") == "unchanged"
        assert statuses.get("macros/print_start.g") == "unchanged"

    def test_diff_file_returns_hunks_with_lines(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_diff(cmd, mgr, "", {"file": "sys/config.g"})
        assert resp["status"] == 200
        body = _body(resp)
        assert body["status"] == "modified"
        assert body["file"] == "sys/config.g"
        assert len(body["hunks"]) > 0
        # Full detail: each hunk has lines and summary
        for hunk in body["hunks"]:
            assert "index" in hunk
            assert "header" in hunk
            assert "lines" in hunk
            assert isinstance(hunk["lines"], list)
            assert len(hunk["lines"]) > 0
            assert "summary" in hunk
        # Has unified diff
        assert body["unifiedDiff"] != ""
        assert "@@" in body["unifiedDiff"]

    def test_diff_all_hunks_are_summary_only(self, e2e_env):
        """diff_all should return summary hunks (no lines) — the frontend
        must fetch detail separately via diff?file=."""
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_diff(cmd, mgr, "", {})
        body = _body(resp)
        modified = [f for f in body["files"] if f["status"] == "modified"]
        assert len(modified) > 0
        for f in modified:
            for hunk in f["hunks"]:
                assert "index" in hunk
                assert "header" in hunk
                # Summary hunks must NOT have lines
                assert "lines" not in hunk

    def test_apply_all_updates_filesystem(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        pfs = e2e_env["printer_fs"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_apply(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        assert "sys/config.g" in body["applied"]

        # Filesystem should have 3.5 content
        config = (pfs / "sys" / "config.g").read_text()
        assert "M906 X1000 Y1000" in config

    def test_diff_empty_after_apply(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})
        d.handle_apply(cmd, mgr, "", {})

        resp = d.handle_diff(cmd, mgr, "", {})
        body = _body(resp)
        for f in body["files"]:
            assert f["status"] == "unchanged", f"Expected {f['file']} unchanged after apply"

    def test_apply_single_file_only_changes_that_file(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        pfs = e2e_env["printer_fs"]
        d.handle_sync(cmd, mgr, "", {})

        original_homex = (pfs / "sys" / "homex.g").read_text()
        resp = d.handle_apply(cmd, mgr, "", {"file": "sys/config.g"})
        assert resp["status"] == 200
        body = _body(resp)
        assert body["applied"] == ["sys/config.g"]

        # config.g updated, homex.g unchanged
        assert "M906 X1000" in (pfs / "sys" / "config.g").read_text()
        assert (pfs / "sys" / "homex.g").read_text() == original_homex


class TestE2EHunkApplyFlow:
    """Partial hunk application through handlers."""

    def test_apply_hunks_partial(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        # Get hunk detail
        diff_resp = d.handle_diff(cmd, mgr, "", {"file": "sys/config.g"})
        diff_body = _body(diff_resp)
        assert len(diff_body["hunks"]) > 0

        # Apply first hunk
        body = json.dumps({"hunks": [0]})
        resp = d.handle_apply_hunks(cmd, mgr, body, {"file": "sys/config.g"})
        assert resp["status"] == 200
        result = _body(resp)
        assert 0 in result["applied"]

    def test_apply_hunks_invalid_json(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        resp = d.handle_apply_hunks(cmd, mgr, "not json", {"file": "sys/config.g"})
        assert resp["status"] == 400

    def test_apply_hunks_missing_file(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        body = json.dumps({"hunks": [0]})
        resp = d.handle_apply_hunks(cmd, mgr, body, {})
        assert resp["status"] == 400


class TestE2EBackupRestoreFlow:
    """Full backup/restore cycle through handlers."""

    def test_backups_created_on_apply(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})
        d.handle_apply(cmd, mgr, "", {})

        resp = d.handle_backups(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        assert len(body["backups"]) >= 2  # pre-update + post-update

        # Each backup has expected fields
        for b in body["backups"]:
            assert "hash" in b
            assert "message" in b
            assert "timestamp" in b

    def test_backup_detail_lists_files(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})
        d.handle_apply(cmd, mgr, "", {})

        backups = _body(d.handle_backups(cmd, mgr, "", {}))["backups"]
        resp = d.handle_backup(cmd, mgr, "", {"hash": backups[0]["hash"]})
        assert resp["status"] == 200
        body = _body(resp)
        assert "sys/config.g" in body["files"]

    def test_backup_download_returns_zip(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})
        d.handle_apply(cmd, mgr, "", {})

        backups = _body(d.handle_backups(cmd, mgr, "", {}))["backups"]
        resp = d.handle_backup_download(cmd, mgr, "", {"hash": backups[0]["hash"]})
        assert resp["status"] == 200
        assert resp["contentType"] == "application/zip"
        assert resp["responseType"] == "file"
        # Body is a temp file path
        assert os.path.isfile(resp["body"])

    def test_restore_reverts_filesystem(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        pfs = e2e_env["printer_fs"]
        original = (pfs / "sys" / "config.g").read_text()

        d.handle_sync(cmd, mgr, "", {})
        d.handle_apply(cmd, mgr, "", {})
        assert (pfs / "sys" / "config.g").read_text() != original

        # Find pre-update backup
        backups = _body(d.handle_backups(cmd, mgr, "", {}))["backups"]
        pre_update = [b for b in backups if "Pre-update" in b["message"]]
        assert len(pre_update) > 0

        resp = d.handle_restore(cmd, mgr, "", {"hash": pre_update[0]["hash"]})
        assert resp["status"] == 200
        assert (pfs / "sys" / "config.g").read_text().rstrip("\n") == original.rstrip("\n")


class TestE2ESettingsFlow:
    """Settings update through handler with real plugin data."""

    def test_settings_update_plugin_data(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        body = json.dumps({
            "referenceRepoUrl": "https://new-repo.example.com/config.git",
            "firmwareBranchOverride": "custom-branch",
        })
        resp = d.handle_settings(cmd, mgr, body, {})
        assert resp["status"] == 200

        # Verify cmd.set_plugin_data was called
        cmd.set_plugin_data.assert_any_call(
            "MeltingplotConfig", "referenceRepoUrl", "https://new-repo.example.com/config.git"
        )
        cmd.set_plugin_data.assert_any_call(
            "MeltingplotConfig", "firmwareBranchOverride", "custom-branch"
        )


class TestE2EBranchSwitchFlow:
    """Test switching between branches through the full chain."""

    def test_sync_to_different_branch_via_override(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        pfs = e2e_env["printer_fs"]

        # Override plugin data to use 3.6 branch
        e2e_env["plugin_data"]["firmwareBranchOverride"] = "3.6"

        resp = d.handle_sync(cmd, mgr, "", {})
        body = _body(resp)
        assert body["activeBranch"] == "3.6"

        # Diff should show modified config + missing heat_bed macro
        diff = _body(d.handle_diff(cmd, mgr, "", {}))
        statuses = {f["file"]: f["status"] for f in diff["files"]}
        assert statuses["sys/config.g"] == "modified"
        assert statuses.get("macros/heat_bed.g") == "missing"

        # Apply everything
        d.handle_apply(cmd, mgr, "", {})
        config = (pfs / "sys" / "config.g").read_text()
        assert "M906 X1200 Y1200" in config
        # New macro file should be created
        assert (pfs / "macros" / "heat_bed.g").exists()
        assert "M140 S60" in (pfs / "macros" / "heat_bed.g").read_text()

    def test_branches_lists_all_after_sync(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_branches(cmd, mgr, "", {})
        body = _body(resp)
        assert "main" in body["branches"]
        assert "3.5" in body["branches"]
        assert "3.6" in body["branches"]


class TestE2EReferenceFiles:
    """Test reference file listing through handlers."""

    def test_reference_empty_before_sync(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        resp = d.handle_reference(cmd, mgr, "", {})
        body = _body(resp)
        assert body["files"] == []

    def test_reference_lists_files_after_sync(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_reference(cmd, mgr, "", {})
        body = _body(resp)
        assert "sys/config.g" in body["files"]
        assert "sys/homex.g" in body["files"]
        assert "macros/print_start.g" in body["files"]


class TestE2EManualBackupFlow:
    """Manual backup through handlers."""

    def test_manual_backup_creates_entry(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_manual_backup(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        assert body["backup"] is not None
        assert "Manual backup" in body["backup"]["message"]

    def test_manual_backup_with_custom_message(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        msg = json.dumps({"message": "Before firmware update"})
        resp = d.handle_manual_backup(cmd, mgr, msg, {})
        assert resp["status"] == 200
        body = _body(resp)
        assert "Before firmware update" in body["backup"]["message"]

    def test_manual_backup_without_sync_succeeds(self, e2e_env):
        """Manual backup works without sync — backups track the printer
        filesystem directly via the worktree, independent of the reference repo."""
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        # Don't sync first — backup should still work
        resp = d.handle_manual_backup(cmd, mgr, "", {})
        assert resp["status"] == 200
        body = _body(resp)
        assert body["backup"] is not None

    def test_manual_backup_appears_in_backups_list(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})
        d.handle_manual_backup(cmd, mgr, "", {})

        resp = d.handle_backups(cmd, mgr, "", {})
        body = _body(resp)
        messages = [b["message"] for b in body["backups"]]
        assert any("Manual backup" in m for m in messages)

    def test_manual_backup_is_downloadable(self, e2e_env):
        d, cmd, mgr = e2e_env["daemon"], e2e_env["cmd"], e2e_env["manager"]
        d.handle_sync(cmd, mgr, "", {})

        resp = d.handle_manual_backup(cmd, mgr, "", {})
        backup_hash = _body(resp)["backup"]["hash"]

        dl_resp = d.handle_backup_download(cmd, mgr, "", {"hash": backup_hash})
        assert dl_resp["status"] == 200
        assert dl_resp["contentType"] == "application/zip"
        assert dl_resp["responseType"] == "file"
        assert os.path.isfile(dl_resp["body"])
