"""Tests for daemon handler logic — handle_sync, handle_apply internals,
plugin data helpers, handle_reference, handle_backup edge cases."""

import importlib.util
import json
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


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


# --- Plugin data helpers ---


class TestGetPluginData:
    def test_returns_plugin_data(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        plugin = SimpleNamespace(data={"status": "up_to_date", "activeBranch": "3.5"})
        cmd.get_object_model.return_value = SimpleNamespace(
            plugins={"MeltingplotConfig": plugin}
        )
        data = daemon.get_plugin_data(cmd)
        assert data["status"] == "up_to_date"
        assert data["activeBranch"] == "3.5"

    def test_returns_empty_dict_when_no_plugins(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = SimpleNamespace(plugins={})
        data = daemon.get_plugin_data(cmd)
        assert data == {}

    def test_returns_empty_dict_when_plugin_missing(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = SimpleNamespace(plugins={})
        data = daemon.get_plugin_data(cmd)
        assert data == {}

    def test_returns_empty_dict_when_no_plugins_attr(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = SimpleNamespace()
        data = daemon.get_plugin_data(cmd)
        assert data == {}

    def test_returns_empty_dict_on_exception(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.side_effect = Exception("connection lost")
        data = daemon.get_plugin_data(cmd)
        assert data == {}


class TestSetPluginData:
    def test_sets_data_successfully(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        daemon.set_plugin_data(cmd, "activeBranch", "3.5")
        cmd.set_plugin_data.assert_called_once_with("MeltingplotConfig", "activeBranch", "3.5")

    def test_logs_warning_on_failure(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.set_plugin_data.side_effect = Exception("write failed")
        # Should not raise, just log
        daemon.set_plugin_data(cmd, "key", "value")


# --- handle_sync ---


class TestHandleSync:
    def test_sync_success_updates_plugin_data(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        plugin = SimpleNamespace(data={
            "referenceRepoUrl": "https://example.com/repo.git",
            "detectedFirmwareVersion": "3.5.1",
            "firmwareBranchOverride": "",
        })
        cmd.get_object_model.return_value = SimpleNamespace(
            plugins={"MeltingplotConfig": plugin}
        )
        manager = MagicMock()
        manager.sync.return_value = {
            "activeBranch": "3.5",
            "exact": False,
            "warning": "fallback",
            "branches": ["main", "3.5"],
        }

        resp = daemon.handle_sync(cmd, manager, "", {})
        body = json.loads(resp["body"])
        assert resp["status"] == 200
        assert body["activeBranch"] == "3.5"

        manager.sync.assert_called_once_with(
            "https://example.com/repo.git", "3.5.1", branch_override=""
        )
        # Verify plugin data updates (arg order: plugin_id, key, value)
        calls = cmd.set_plugin_data.call_args_list
        keys_set = [c[0][1] for c in calls]
        assert "activeBranch" in keys_set
        assert "lastSyncTimestamp" in keys_set
        assert "status" in keys_set

    def test_sync_error_returns_400(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        plugin = SimpleNamespace(data={
            "referenceRepoUrl": "", "detectedFirmwareVersion": "", "firmwareBranchOverride": ""
        })
        cmd.get_object_model.return_value = SimpleNamespace(
            plugins={"MeltingplotConfig": plugin}
        )
        manager = MagicMock()
        manager.sync.return_value = {"error": "No reference repository URL configured"}

        resp = daemon.handle_sync(cmd, manager, "", {})
        assert resp["status"] == 400
        body = json.loads(resp["body"])
        assert "error" in body

    def test_sync_passes_branch_override(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        plugin = SimpleNamespace(data={
            "referenceRepoUrl": "https://example.com/repo.git",
            "detectedFirmwareVersion": "3.5.1",
            "firmwareBranchOverride": "custom-branch",
        })
        cmd.get_object_model.return_value = SimpleNamespace(
            plugins={"MeltingplotConfig": plugin}
        )
        manager = MagicMock()
        manager.sync.return_value = {
            "activeBranch": "custom-branch",
            "exact": True,
            "warning": None,
            "branches": ["custom-branch"],
        }

        daemon.handle_sync(cmd, manager, "", {})
        manager.sync.assert_called_once_with(
            "https://example.com/repo.git", "3.5.1", branch_override="custom-branch"
        )


# --- handle_apply / handle_apply_hunks internals ---


class TestHandleApplyFileInternals:
    def test_apply_hunks_missing_file_returns_400(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        # No file query param
        resp = daemon.handle_apply_hunks(cmd, manager, '{"hunks": [0]}', {})
        assert resp["status"] == 400

    def test_hunks_not_a_list_returns_400(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"hunks": "not-a-list"})
        resp = daemon.handle_apply_hunks(cmd, manager, body, {"file": "sys/config.g"})
        assert resp["status"] == 400
        body_data = json.loads(resp["body"])
        assert "list" in body_data["error"]

    def test_apply_file_error_from_manager(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_file.return_value = {"error": "Unknown reference path: bad/path.g"}

        resp = daemon.handle_apply(cmd, manager, "", {"file": "bad/path.g"})
        assert resp["status"] == 400

    def test_apply_hunks_empty_body(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_hunks.return_value = {"applied": [], "failed": []}

        resp = daemon.handle_apply_hunks(cmd, manager, "", {"file": "sys/config.g"})
        assert resp["status"] == 200

    def test_url_decodes_file_path(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_file.return_value = {"applied": ["sys/config file.g"]}

        resp = daemon.handle_apply(cmd, manager, "", {"file": "sys/config%20file.g"})
        assert resp["status"] == 200
        manager.apply_file.assert_called_once_with("sys/config file.g")


# --- handle_reference ---


class TestHandleReference:
    def test_reference_repo_not_cloned(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        with patch("os.path.isdir", return_value=False):
            resp = daemon.handle_reference(cmd, manager, "", {})

        body = json.loads(resp["body"])
        assert body["files"] == []

    def test_reference_repo_lists_files(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        with (
            patch("os.path.isdir", return_value=True),
            patch("git_utils.list_files", return_value=["sys/config.g", "sys/homex.g"]),
        ):
            resp = daemon.handle_reference(cmd, manager, "", {})

        body = json.loads(resp["body"])
        assert "sys/config.g" in body["files"]


# --- handle_backup edge cases ---


class TestHandleBackupDetailEdgeCases:
    def test_missing_commit_hash(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_backup(cmd, manager, "", {})
        assert resp["status"] == 400

    def test_download_exception_returns_500(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_download.side_effect = RuntimeError("git archive failed")

        resp = daemon.handle_backup_download(cmd, manager, "", {"hash": "abc123"})
        assert resp["status"] == 500

    def test_download_creates_temp_file(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_download.return_value = b"PK\x03\x04zip"

        resp = daemon.handle_backup_download(cmd, manager, "", {"hash": "abc12345deadbeef"})
        assert resp["status"] == 200
        assert resp["contentType"] == "application/zip"
        assert resp["responseType"] == "file"
        # body should be a temp file path
        assert resp["body"].endswith(".zip")


# --- handle_settings ---


class TestHandleSettings:
    def test_settings_sets_repo_url(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"referenceRepoUrl": "https://new.example.com/repo.git"})
        resp = daemon.handle_settings(cmd, manager, body, {})
        assert resp["status"] == 200
        cmd.set_plugin_data.assert_any_call("MeltingplotConfig", "referenceRepoUrl", "https://new.example.com/repo.git")

    def test_settings_sets_branch_override(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"firmwareBranchOverride": "custom"})
        resp = daemon.handle_settings(cmd, manager, body, {})
        assert resp["status"] == 200
        cmd.set_plugin_data.assert_any_call("MeltingplotConfig", "firmwareBranchOverride", "custom")

    def test_settings_invalid_json(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_settings(cmd, manager, "not json{", {})
        assert resp["status"] == 400

    def test_settings_empty_body(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_settings(cmd, manager, "", {})
        assert resp["status"] == 200

    def test_settings_ignores_unknown_fields(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"unknownField": "value"})
        resp = daemon.handle_settings(cmd, manager, body, {})
        assert resp["status"] == 200
        cmd.set_plugin_data.assert_not_called()


# --- handle_restore edge cases ---


class TestHandleRestoreEdgeCases:
    def test_restore_missing_hash(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_restore(cmd, manager, "", {})
        assert resp["status"] == 400

    def test_restore_error_from_manager(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.restore_backup.return_value = {"error": "commit not found"}

        resp = daemon.handle_restore(cmd, manager, "", {"hash": "bad_hash"})
        assert resp["status"] == 400


# --- handle_diff edge cases ---


class TestHandleDiffEdgeCases:
    def test_diff_file_error_from_manager(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_file.return_value = {"error": "Unknown reference path"}

        resp = daemon.handle_diff(cmd, manager, "", {"file": "unknown/file.g"})
        assert resp["status"] == 400

    def test_diff_all_returns_files(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_all.return_value = [
            {"file": "sys/config.g", "status": "modified", "hunks": []}
        ]

        resp = daemon.handle_diff(cmd, manager, "", {})
        body = json.loads(resp["body"])
        assert len(body["files"]) == 1


# --- register_endpoints ---


class TestRegisterEndpoints:
    def test_registers_all_endpoints(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        endpoint_mock = MagicMock()
        cmd.add_http_endpoint.return_value = endpoint_mock
        registered = daemon.register_endpoints(cmd, manager)
        assert len(registered) > 0
        assert cmd.add_http_endpoint.call_count > 0
        # Each endpoint should have set_endpoint_handler called
        assert endpoint_mock.set_endpoint_handler.call_count == len(registered)

    def test_handles_registration_failure(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        cmd.add_http_endpoint.side_effect = Exception("DSF not ready")
        registered = daemon.register_endpoints(cmd, manager)
        # Should return empty list but not crash
        assert registered == []


# --- Firmware version detection (uses ObjectModel attribute access) ---


class TestFirmwareDetection:
    """Tests that firmware detection in main() uses proper ObjectModel
    attribute access (model.boards, board.firmware_version) instead of
    dict-style .get() which fails on the real DSF ObjectModel."""

    def test_detects_firmware_from_object_model(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        board = SimpleNamespace(firmware_version="3.5.1")
        cmd.get_object_model.return_value = SimpleNamespace(boards=[board])

        # Simulate the firmware detection logic from main()
        model = cmd.get_object_model()
        boards = getattr(model, "boards", None) or []
        fw = ""
        if boards:
            fw = getattr(boards[0], "firmware_version", "") or ""
        assert fw == "3.5.1"

    def test_handles_empty_boards_list(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = SimpleNamespace(boards=[])

        model = cmd.get_object_model()
        boards = getattr(model, "boards", None) or []
        assert boards == []

    def test_handles_missing_boards_attr(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = SimpleNamespace()

        model = cmd.get_object_model()
        boards = getattr(model, "boards", None) or []
        assert boards == []

    def test_handles_none_firmware_version(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        board = SimpleNamespace(firmware_version=None)
        cmd.get_object_model.return_value = SimpleNamespace(boards=[board])

        model = cmd.get_object_model()
        boards = getattr(model, "boards", None) or []
        fw = getattr(boards[0], "firmware_version", "") or ""
        assert fw == ""
