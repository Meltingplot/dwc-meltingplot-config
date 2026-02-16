"""Tests for daemon handler logic — handle_sync, handle_apply_file internals,
plugin data helpers, handle_reference, handle_backup_detail edge cases."""

import importlib.util
import json
import os
import sys
import types
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
    spec = importlib.util.spec_from_file_location(
        "daemon_mod",
        os.path.join(os.path.dirname(__file__), "..", "dsf", "meltingplot-config-daemon.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- Plugin data helpers ---


class TestGetPluginData:
    def test_returns_sbc_data(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = {
            "plugins": {
                "MeltingplotConfig": {
                    "sbcData": {"status": "up_to_date", "activeBranch": "3.5"}
                }
            }
        }
        data = daemon.get_plugin_data(cmd)
        assert data["status"] == "up_to_date"
        assert data["activeBranch"] == "3.5"

    def test_returns_empty_dict_when_no_plugins(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = {}
        data = daemon.get_plugin_data(cmd)
        assert data == {}

    def test_returns_empty_dict_when_plugin_missing(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = {"plugins": {}}
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
        cmd.set_plugin_data.assert_called_once_with("activeBranch", "3.5", "MeltingplotConfig")

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
        cmd.get_object_model.return_value = {
            "plugins": {
                "MeltingplotConfig": {
                    "sbcData": {
                        "referenceRepoUrl": "https://example.com/repo.git",
                        "detectedFirmwareVersion": "3.5.1",
                        "firmwareBranchOverride": "",
                    }
                }
            }
        }
        manager = MagicMock()
        manager.sync.return_value = {
            "activeBranch": "3.5",
            "exact": False,
            "warning": "fallback",
            "branches": ["main", "3.5"],
        }

        resp = daemon.dispatch(cmd, manager, "POST", "sync", None)
        body = json.loads(resp["body"])
        assert resp["status"] == 200
        assert body["activeBranch"] == "3.5"

        manager.sync.assert_called_once_with(
            "https://example.com/repo.git", "3.5.1", branch_override=""
        )
        # Verify plugin data updates
        calls = cmd.set_plugin_data.call_args_list
        keys_set = [c[0][0] for c in calls]
        assert "activeBranch" in keys_set
        assert "lastSyncTimestamp" in keys_set
        assert "status" in keys_set

    def test_sync_error_returns_400(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = {
            "plugins": {
                "MeltingplotConfig": {
                    "sbcData": {"referenceRepoUrl": "", "detectedFirmwareVersion": "", "firmwareBranchOverride": ""}
                }
            }
        }
        manager = MagicMock()
        manager.sync.return_value = {"error": "No reference repository URL configured"}

        resp = daemon.dispatch(cmd, manager, "POST", "sync", None)
        assert resp["status"] == 400
        body = json.loads(resp["body"])
        assert "error" in body

    def test_sync_passes_branch_override(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.return_value = {
            "plugins": {
                "MeltingplotConfig": {
                    "sbcData": {
                        "referenceRepoUrl": "https://example.com/repo.git",
                        "detectedFirmwareVersion": "3.5.1",
                        "firmwareBranchOverride": "custom-branch",
                    }
                }
            }
        }
        manager = MagicMock()
        manager.sync.return_value = {
            "activeBranch": "custom-branch",
            "exact": True,
            "warning": None,
            "branches": ["custom-branch"],
        }

        daemon.dispatch(cmd, manager, "POST", "sync", None)
        manager.sync.assert_called_once_with(
            "https://example.com/repo.git", "3.5.1", branch_override="custom-branch"
        )


# --- handle_apply_file internals ---


class TestHandleApplyFileInternals:
    def test_missing_path_returns_400(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "POST", "apply/", None)
        assert resp["status"] == 400

    def test_hunks_not_a_list_returns_400(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"hunks": "not-a-list"})
        resp = daemon.dispatch(cmd, manager, "POST", "apply/sys/config.g/hunks", body)
        assert resp["status"] == 400
        body_data = json.loads(resp["body"])
        assert "list" in body_data["error"]

    def test_apply_file_error_from_manager(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_file.return_value = {"error": "Unknown reference path: bad/path.g"}

        resp = daemon.dispatch(cmd, manager, "POST", "apply/bad/path.g", None)
        assert resp["status"] == 400

    def test_apply_hunks_empty_body(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_hunks.return_value = {"applied": [], "failed": []}

        resp = daemon.dispatch(cmd, manager, "POST", "apply/sys/config.g/hunks", "")
        assert resp["status"] == 200

    def test_url_decodes_file_path(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.apply_file.return_value = {"applied": ["sys/config file.g"]}

        resp = daemon.dispatch(cmd, manager, "POST", "apply/sys/config%20file.g", None)
        assert resp["status"] == 200
        manager.apply_file.assert_called_once_with("sys/config file.g")


# --- handle_reference ---


class TestHandleReference:
    def test_reference_repo_not_cloned(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        with patch("os.path.isdir", return_value=False):
            resp = daemon.dispatch(cmd, manager, "GET", "reference", None)

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
            resp = daemon.dispatch(cmd, manager, "GET", "reference", None)

        body = json.loads(resp["body"])
        assert "sys/config.g" in body["files"]


# --- handle_backup_detail edge cases ---


class TestHandleBackupDetailEdgeCases:
    def test_missing_commit_hash(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "GET", "backup/", None)
        assert resp["status"] == 400

    def test_download_exception_returns_500(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_download.side_effect = RuntimeError("git archive failed")

        resp = daemon.dispatch(cmd, manager, "GET", "backup/abc123/download", None)
        assert resp["status"] == 500

    def test_download_sets_content_disposition(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.get_backup_download.return_value = b"PK\x03\x04zip"

        resp = daemon.dispatch(cmd, manager, "GET", "backup/abc12345deadbeef/download", None)
        assert resp["status"] == 200
        assert "abc12345" in resp["headers"]["Content-Disposition"]


# --- handle_settings ---


class TestHandleSettings:
    def test_settings_sets_repo_url(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"referenceRepoUrl": "https://new.example.com/repo.git"})
        resp = daemon.dispatch(cmd, manager, "POST", "settings", body)
        assert resp["status"] == 200
        cmd.set_plugin_data.assert_any_call("referenceRepoUrl", "https://new.example.com/repo.git", "MeltingplotConfig")

    def test_settings_sets_branch_override(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"firmwareBranchOverride": "custom"})
        resp = daemon.dispatch(cmd, manager, "POST", "settings", body)
        assert resp["status"] == 200
        cmd.set_plugin_data.assert_any_call("firmwareBranchOverride", "custom", "MeltingplotConfig")

    def test_settings_invalid_json(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "POST", "settings", "not json{")
        assert resp["status"] == 400

    def test_settings_empty_body(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "POST", "settings", "")
        assert resp["status"] == 200

    def test_settings_ignores_unknown_fields(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        body = json.dumps({"unknownField": "value"})
        resp = daemon.dispatch(cmd, manager, "POST", "settings", body)
        assert resp["status"] == 200
        cmd.set_plugin_data.assert_not_called()


# --- handle_restore edge cases ---


class TestHandleRestoreEdgeCases:
    def test_restore_missing_hash(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "POST", "restore/", None)
        assert resp["status"] == 400

    def test_restore_error_from_manager(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.restore_backup.return_value = {"error": "commit not found"}

        resp = daemon.dispatch(cmd, manager, "POST", "restore/bad_hash", None)
        assert resp["status"] == 400


# --- handle_diff edge cases ---


class TestHandleDiffEdgeCases:
    def test_diff_file_missing_path(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        resp = daemon.dispatch(cmd, manager, "GET", "diff/", None)
        assert resp["status"] == 400

    def test_diff_file_error_from_manager(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_file.return_value = {"error": "Unknown reference path"}

        resp = daemon.dispatch(cmd, manager, "GET", "diff/unknown/file.g", None)
        assert resp["status"] == 400

    def test_diff_all_returns_files(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        manager.diff_all.return_value = [
            {"file": "sys/config.g", "status": "modified", "hunks": []}
        ]

        resp = daemon.dispatch(cmd, manager, "GET", "diff", None)
        body = json.loads(resp["body"])
        assert len(body["files"]) == 1


# --- register_endpoints ---


class TestRegisterEndpoints:
    def test_registers_all_endpoints(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        registered = daemon.register_endpoints(cmd)
        assert len(registered) > 0
        assert cmd.add_http_endpoint.call_count > 0

    def test_handles_registration_failure(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.add_http_endpoint.side_effect = Exception("DSF not ready")
        registered = daemon.register_endpoints(cmd)
        # Should return empty list but not crash
        assert registered == []
