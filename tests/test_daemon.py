"""Tests for meltingplot-config-daemon.py — handlers and response helpers."""

import importlib
import json
import sys
import types
from unittest.mock import MagicMock

import pytest

# The daemon imports dsf.* which isn't available in test. We need to mock
# those modules before importing the daemon.


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
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "daemon_mod",
        os.path.join(os.path.dirname(__file__), "..", "dsf", "meltingplot-config-daemon.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestResponseHelpers:
    def test_json_response(self):
        daemon = _import_daemon()
        resp = daemon.json_response({"key": "value"})
        assert resp["status"] == 200
        assert resp["contentType"] == "application/json"
        body = json.loads(resp["body"])
        assert body["key"] == "value"

    def test_json_response_custom_status(self):
        daemon = _import_daemon()
        resp = daemon.json_response({"ok": True}, status=201)
        assert resp["status"] == 201

    def test_error_response(self):
        daemon = _import_daemon()
        resp = daemon.error_response("something failed")
        assert resp["status"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "something failed"

    def test_error_response_custom_status(self):
        daemon = _import_daemon()
        resp = daemon.error_response("not found", status=404)
        assert resp["status"] == 404


class TestHandlers:
    def test_status(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_branches.return_value = ["main"]

        cmd.get_object_model.return_value = {
            "plugins": {
                "MeltingplotConfig": {
                    "sbcData": {
                        "status": "up_to_date",
                        "detectedFirmwareVersion": "3.5",
                        "activeBranch": "3.5",
                        "referenceRepoUrl": "https://example.com",
                        "lastSyncTimestamp": "2026-01-01T00:00:00",
                    }
                }
            }
        }

        resp = daemon.handle_status(cmd, manager, "", {})
        assert resp["status"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "up_to_date"
        assert body["detectedFirmwareVersion"] == "3.5"

    def test_branches(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_branches.return_value = ["main", "3.5"]

        resp = daemon.handle_branches(cmd, manager, "", {})
        body = json.loads(resp["body"])
        assert "branches" in body

    def test_diff_all(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_all.return_value = [{"file": "sys/config.g", "status": "modified"}]

        # No file query param → diff all
        resp = daemon.handle_diff(cmd, manager, "", {})
        assert resp["status"] == 200
        body = json.loads(resp["body"])
        assert "files" in body
        manager.diff_all.assert_called_once()

    def test_diff_single_file(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_file.return_value = {
            "file": "sys/config.g", "status": "unchanged", "hunks": [], "unifiedDiff": ""
        }

        # With file query param → diff single file
        resp = daemon.handle_diff(cmd, manager, "", {"file": "sys/config.g"})
        assert resp["status"] == 200
        manager.diff_file.assert_called_once_with("sys/config.g")

    def test_apply_all(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_all.return_value = {"applied": ["sys/config.g"]}

        # No file param → apply all
        resp = daemon.handle_apply(cmd, manager, "", {})
        assert resp["status"] == 200
        manager.apply_all.assert_called_once()

    def test_apply_single_file(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_file.return_value = {"applied": ["sys/config.g"]}

        # With file param → apply single file
        resp = daemon.handle_apply(cmd, manager, "", {"file": "sys/config.g"})
        assert resp["status"] == 200
        manager.apply_file.assert_called_once_with("sys/config.g")

    def test_apply_hunks(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_hunks.return_value = {"applied": [0, 2], "failed": []}

        body = json.dumps({"hunks": [0, 2]})
        resp = daemon.handle_apply_hunks(cmd, manager, body, {"file": "sys/config.g"})
        assert resp["status"] == 200
        manager.apply_hunks.assert_called_once_with("sys/config.g", [0, 2])

    def test_apply_hunks_missing_file(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_apply_hunks(cmd, manager, '{"hunks": [0]}', {})
        assert resp["status"] == 400

    def test_apply_hunks_invalid_json(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_apply_hunks(cmd, manager, "not json", {"file": "sys/config.g"})
        assert resp["status"] == 400

    def test_settings_post(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"referenceRepoUrl": "https://example.com/repo.git"})
        resp = daemon.handle_settings(cmd, manager, body, {})
        assert resp["status"] == 200

    def test_backup_detail(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_files.return_value = ["sys/config.g"]

        resp = daemon.handle_backup(cmd, manager, "", {"hash": "abc123"})
        assert resp["status"] == 200
        body = json.loads(resp["body"])
        assert body["hash"] == "abc123"
        assert "sys/config.g" in body["files"]

    def test_backup_detail_missing_hash(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_backup(cmd, manager, "", {})
        assert resp["status"] == 400

    def test_backup_download(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_download.return_value = b"PK\x03\x04fake"

        resp = daemon.handle_backup_download(cmd, manager, "", {"hash": "abc123"})
        assert resp["status"] == 200
        assert resp["contentType"] == "application/zip"
        assert resp["responseType"] == "file"

    def test_restore(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.restore_backup.return_value = {"restored": ["sys/config.g"]}

        resp = daemon.handle_restore(cmd, manager, "", {"hash": "abc123"})
        assert resp["status"] == 200

    def test_restore_missing_hash(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.handle_restore(cmd, manager, "", {})
        assert resp["status"] == 400


class TestEndpointRegistry:
    def test_endpoints_registered(self):
        daemon = _import_daemon()
        endpoints = daemon.ENDPOINTS
        # Check expected endpoints
        assert ("GET", "status") in endpoints
        assert ("POST", "sync") in endpoints
        assert ("GET", "diff") in endpoints
        assert ("GET", "branches") in endpoints
        assert ("GET", "reference") in endpoints
        assert ("GET", "backups") in endpoints
        assert ("POST", "apply") in endpoints
        assert ("POST", "applyHunks") in endpoints
        assert ("GET", "backup") in endpoints
        assert ("GET", "backupDownload") in endpoints
        assert ("POST", "restore") in endpoints
        assert ("POST", "settings") in endpoints

    def test_all_endpoints_are_callable(self):
        daemon = _import_daemon()
        for key, handler in daemon.ENDPOINTS.items():
            assert callable(handler), f"Handler for {key} is not callable"
