"""Tests for meltingplot-config-daemon.py — dispatch and response helpers."""

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

    dsf_connections.CommandConnection = MagicMock
    dsf_connections.InterceptConnection = MagicMock
    dsf_commands_code.CodeResult = MagicMock

    class FakeHttpEndpointType:
        GET = "GET"
        POST = "POST"

    dsf_http.HttpEndpointType = FakeHttpEndpointType

    monkeypatch.setitem(sys.modules, "dsf", dsf_mod)
    monkeypatch.setitem(sys.modules, "dsf.connections", dsf_connections)
    monkeypatch.setitem(sys.modules, "dsf.commands", dsf_commands)
    monkeypatch.setitem(sys.modules, "dsf.commands.code", dsf_commands_code)
    monkeypatch.setitem(sys.modules, "dsf.http", dsf_http)


def _import_daemon():
    """Import (or reimport) the daemon module."""
    mod_name = "meltingplot-config-daemon"
    # Python doesn't like hyphens in module names, use importlib
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


class TestDispatch:
    def test_exact_route_match(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_branches.return_value = ["main", "3.5"]

        resp = daemon.dispatch(cmd, manager, "GET", "branches", None)
        body = json.loads(resp["body"])
        assert "branches" in body

    def test_prefix_route_match(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_file.return_value = {"file": "sys/config.g", "status": "unchanged", "hunks": [], "unifiedDiff": ""}

        resp = daemon.dispatch(cmd, manager, "GET", "diff/sys/config.g", None)
        assert resp["status"] == 200
        manager.diff_file.assert_called_once_with("sys/config.g")

    def test_unknown_route_returns_404(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "GET", "nonexistent", None)
        assert resp["status"] == 404

    def test_apply_file_dispatch(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_file.return_value = {"applied": ["sys/config.g"]}

        resp = daemon.dispatch(cmd, manager, "POST", "apply/sys/config.g", None)
        assert resp["status"] == 200
        manager.apply_file.assert_called_once_with("sys/config.g")

    def test_apply_hunks_dispatch(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_hunks.return_value = {"applied": [0, 2], "failed": []}

        body = json.dumps({"hunks": [0, 2]})
        resp = daemon.dispatch(cmd, manager, "POST", "apply/sys/config.g/hunks", body)
        assert resp["status"] == 200
        manager.apply_hunks.assert_called_once_with("sys/config.g", [0, 2])

    def test_apply_hunks_invalid_json(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "POST", "apply/sys/config.g/hunks", "not json")
        assert resp["status"] == 400

    def test_settings_post(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"referenceRepoUrl": "https://example.com/repo.git"})
        resp = daemon.dispatch(cmd, manager, "POST", "settings", body)
        assert resp["status"] == 200

    def test_backup_detail(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_files.return_value = ["sys/config.g"]

        resp = daemon.dispatch(cmd, manager, "GET", "backup/abc123", None)
        assert resp["status"] == 200
        body = json.loads(resp["body"])
        assert body["hash"] == "abc123"
        assert "sys/config.g" in body["files"]

    def test_backup_download(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_download.return_value = b"PK\x03\x04fake"

        resp = daemon.dispatch(cmd, manager, "GET", "backup/abc123/download", None)
        assert resp["status"] == 200
        assert resp["contentType"] == "application/zip"

    def test_restore(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.restore_backup.return_value = {"restored": ["sys/config.g"]}

        resp = daemon.dispatch(cmd, manager, "POST", "restore/abc123", None)
        assert resp["status"] == 200

    def test_status_endpoint(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_branches.return_value = ["main"]

        # get_plugin_data needs the cmd mock to return something
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

        resp = daemon.dispatch(cmd, manager, "GET", "status", None)
        assert resp["status"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "up_to_date"
        assert body["detectedFirmwareVersion"] == "3.5"


class TestRouteDecorator:
    def test_routes_registered(self):
        daemon = _import_daemon()
        routes = daemon.ROUTES
        # Check some expected routes
        assert ("GET", "status") in routes
        assert ("POST", "sync") in routes
        assert ("GET", "diff") in routes
        assert ("GET", "diff/") in routes
        assert ("POST", "apply") in routes
        assert ("POST", "apply/") in routes
        assert ("GET", "backups") in routes
        assert ("GET", "backup/") in routes
        assert ("POST", "restore/") in routes
        assert ("POST", "settings") in routes
