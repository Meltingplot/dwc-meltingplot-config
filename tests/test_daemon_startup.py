"""Tests for daemon startup/shutdown (main()), _make_async_handler exception
path, build_directory_map edge cases, and register_endpoints partial failure."""

import asyncio
import importlib.util
import json
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# --- DSF module mocking (same pattern as test_daemon.py) ---


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


# --- main() startup tests ---


class TestMainStartup:
    """Tests for the main() function startup sequence."""

    def _make_model(self, fw_version="3.5.1", directories=None):
        """Create a mock object model."""
        board = SimpleNamespace(firmware_version=fw_version)
        dirs = directories or SimpleNamespace(
            filaments="0:/filaments",
            firmware="0:/firmware",
            g_codes="0:/gcodes",
            macros="0:/macros",
            menu="0:/menu",
            system="0:/sys",
            web="0:/www",
        )
        return SimpleNamespace(boards=[board], directories=dirs)

    def test_startup_restores_persisted_settings(self):
        """Persisted settings should be restored via set_plugin_data on startup."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        persisted = {
            "referenceRepoUrl": "https://example.com/repo.git",
            "firmwareBranchOverride": "custom",
            "activeBranch": "3.5",
        }

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager"),
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "load_settings_from_disk", return_value=persisted),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # All persisted keys should be set via set_plugin_data
        calls = {c[0][1]: c[0][2] for c in cmd.set_plugin_data.call_args_list}
        assert calls.get("referenceRepoUrl") == "https://example.com/repo.git"
        assert calls.get("firmwareBranchOverride") == "custom"
        assert calls.get("activeBranch") == "3.5"

    def test_startup_skips_empty_persisted_values(self):
        """Empty string values from disk should not be restored."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        persisted = {
            "referenceRepoUrl": "https://example.com/repo.git",
            "firmwareBranchOverride": "",
        }

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager"),
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "load_settings_from_disk", return_value=persisted),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # referenceRepoUrl should be set, firmwareBranchOverride should be skipped
        calls = {c[0][1]: c[0][2] for c in cmd.set_plugin_data.call_args_list
                 if c[0][1] in ("referenceRepoUrl", "firmwareBranchOverride")}
        assert "referenceRepoUrl" in calls
        assert "firmwareBranchOverride" not in calls

    def test_startup_with_no_persisted_settings(self):
        """When no settings file exists, startup continues normally."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager"),
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "load_settings_from_disk", return_value={}),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # Only firmware version should be set (not persisted settings)
        persisted_keys = {"referenceRepoUrl", "firmwareBranchOverride", "activeBranch"}
        for c in cmd.set_plugin_data.call_args_list:
            if c[0][1] in persisted_keys:
                # Should NOT have been called for any persisted key
                assert False, f"set_plugin_data called for {c[0][1]} with no persisted data"

    def test_startup_detects_firmware_and_resolves_paths(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        # Make the main loop exit immediately
        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager") as MockManager,
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # Firmware version should be set
        cmd.set_plugin_data.assert_any_call("MeltingplotConfig", "detectedFirmwareVersion", "3.5.1")

        # ConfigManager should be created with resolved dirs
        MockManager.assert_called_once()
        call_kwargs = MockManager.call_args[1]
        assert call_kwargs["dsf_command_connection"] is cmd
        assert call_kwargs["resolved_dirs"] is not None
        assert len(call_kwargs["resolved_dirs"]) > 0

    def test_startup_when_get_object_model_fails(self):
        """If get_object_model() raises, main should still start with defaults."""
        daemon = _import_daemon()
        cmd = MagicMock()
        cmd.get_object_model.side_effect = Exception("DSF not ready")
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager") as MockManager,
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # Should still create ConfigManager (with defaults)
        MockManager.assert_called_once()
        call_kwargs = MockManager.call_args[1]
        # dir_map should be None (fallback to defaults inside ConfigManager)
        assert call_kwargs["directory_map"] is None

    def test_startup_with_empty_boards(self):
        """If boards is empty, firmware detection is skipped (no set_plugin_data)."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = SimpleNamespace(boards=[], directories=SimpleNamespace(
            filaments="0:/filaments", firmware="0:/firmware",
            g_codes="0:/gcodes", macros="0:/macros",
            menu="0:/menu", system="0:/sys", web="0:/www",
        ))
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager"),
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # detectedFirmwareVersion should NOT be set
        fw_calls = [c for c in cmd.set_plugin_data.call_args_list
                     if c[0][1] == "detectedFirmwareVersion"]
        assert fw_calls == []

    def test_startup_with_none_firmware_version(self):
        """If board.firmware_version is None, skip setting it."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = SimpleNamespace(
            boards=[SimpleNamespace(firmware_version=None)],
            directories=SimpleNamespace(
                filaments="0:/filaments", firmware="0:/firmware",
                g_codes="0:/gcodes", macros="0:/macros",
                menu="0:/menu", system="0:/sys", web="0:/www",
            ),
        )
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager"),
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        fw_calls = [c for c in cmd.set_plugin_data.call_args_list
                     if c[0][1] == "detectedFirmwareVersion"]
        assert fw_calls == []

    def test_startup_resolve_path_partial_failure(self):
        """If resolve_path fails for some directories, others still resolve."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model

        call_count = 0

        def resolve_some(p):
            nonlocal call_count
            call_count += 1
            if "sys" in p:
                return "/opt/dsf/sd/sys"
            if "macros" in p:
                raise RuntimeError("permission denied")
            return f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        cmd.resolve_path.side_effect = resolve_some

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager") as MockManager,
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        call_kwargs = MockManager.call_args[1]
        resolved = call_kwargs["resolved_dirs"]
        # sys should be resolved, macros should not
        assert "0:/sys/" in resolved
        assert "0:/macros/" not in resolved

    def test_startup_resolve_path_all_fail_uses_none(self):
        """If all resolve_path calls fail, resolved_dirs is None (defaults)."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = RuntimeError("all fail")

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager") as MockManager,
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        call_kwargs = MockManager.call_args[1]
        # Empty dict is falsy -> passed as None
        assert call_kwargs["resolved_dirs"] is None

    def test_shutdown_closes_endpoints_and_connection(self):
        """On KeyboardInterrupt, all endpoints and connection should be closed."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        ep1, ep2 = MagicMock(), MagicMock()

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager"),
            patch.object(daemon, "register_endpoints", return_value=[ep1, ep2]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        ep1.close.assert_called_once()
        ep2.close.assert_called_once()
        cmd.close.assert_called_once()

    def test_startup_resolve_path_unwraps_response_object(self):
        """resolve_path returns a Response object — daemon must use .result."""
        daemon = _import_daemon()
        cmd = MagicMock()
        model = self._make_model()
        cmd.get_object_model.return_value = model

        # Simulate dsf-python's resolve_path returning a Response object
        def fake_resolve(p):
            path = f"/opt/dsf/sd/{p.split(':/', 1)[1]}"
            return SimpleNamespace(result=path, success=True)

        cmd.resolve_path.side_effect = fake_resolve

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager") as MockManager,
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        call_kwargs = MockManager.call_args[1]
        resolved = call_kwargs["resolved_dirs"]
        assert resolved is not None
        # Paths should be unwrapped strings, not Response objects
        for printer_prefix, fs_path in resolved.items():
            assert isinstance(fs_path, str), f"Expected string, got {type(fs_path)}"
            assert fs_path.startswith("/opt/dsf/sd/")
            assert fs_path.endswith("/")

    def test_startup_empty_dir_map_falls_back_to_defaults(self):
        """If build_directory_map returns {}, use DEFAULT_DIRECTORY_MAP for resolution."""
        daemon = _import_daemon()
        cmd = MagicMock()
        # Model with no valid directory attributes
        model = SimpleNamespace(
            boards=[SimpleNamespace(firmware_version="3.5")],
            directories=SimpleNamespace(),  # No attrs match _DIR_ATTRS
        )
        cmd.get_object_model.return_value = model
        cmd.resolve_path.side_effect = lambda p: f"/opt/dsf/sd/{p.split(':/', 1)[1]}"

        with (
            patch.object(daemon, "CommandConnection", return_value=cmd),
            patch.object(daemon, "ConfigManager") as MockManager,
            patch.object(daemon, "register_endpoints", return_value=[]),
            patch.object(daemon, "_migrate_legacy_data"),
            patch.object(daemon.os, "makedirs"),
            patch("time.sleep", side_effect=KeyboardInterrupt),
        ):
            daemon.main()

        # Should have used DEFAULT_DIRECTORY_MAP for resolution
        assert cmd.resolve_path.call_count > 0


# --- _make_async_handler exception path tests ---


class TestMakeAsyncHandlerExceptionPath:
    """Tests for _make_async_handler wrapping handler exceptions in 500 response."""

    def test_handler_exception_returns_500(self):
        """If handler_func raises, the wrapper should send a 500 response."""
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        def failing_handler(cmd, manager, body, queries):
            raise RuntimeError("unexpected error in handler")

        handler = daemon._make_async_handler(cmd, manager, failing_handler)

        # Create a mock http_conn with async methods
        http_conn = MagicMock()
        request = SimpleNamespace(queries={}, body="")
        http_conn.read_request = AsyncMock(return_value=request)
        http_conn.send_response = AsyncMock()

        asyncio.get_event_loop().run_until_complete(handler(http_conn))

        # Should have sent a 500 response
        http_conn.send_response.assert_called_once()
        args = http_conn.send_response.call_args[0]
        assert args[0] == 500
        body = json.loads(args[1])
        assert body["error"] == "Internal server error"

    def test_handler_success_sends_json_response(self):
        """Normal handler execution sends proper JSON response."""
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        def ok_handler(cmd, manager, body, queries):
            return {"status": 200, "body": '{"ok":true}', "contentType": "application/json"}

        handler = daemon._make_async_handler(cmd, manager, ok_handler)

        http_conn = MagicMock()
        request = SimpleNamespace(queries={"key": "val"}, body='{"data":1}')
        http_conn.read_request = AsyncMock(return_value=request)
        http_conn.send_response = AsyncMock()

        asyncio.get_event_loop().run_until_complete(handler(http_conn))

        http_conn.send_response.assert_called_once()
        args = http_conn.send_response.call_args[0]
        assert args[0] == 200

    def test_handler_with_file_response_type(self):
        """Handler returning responseType='file' should use File response type."""
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        def file_handler(cmd, manager, body, queries):
            return {
                "status": 200,
                "body": "/tmp/test.zip",
                "contentType": "application/zip",
                "responseType": "file",
            }

        handler = daemon._make_async_handler(cmd, manager, file_handler)

        http_conn = MagicMock()
        request = SimpleNamespace(queries={}, body="")
        http_conn.read_request = AsyncMock(return_value=request)
        http_conn.send_response = AsyncMock()

        asyncio.get_event_loop().run_until_complete(handler(http_conn))

        args = http_conn.send_response.call_args[0]
        assert args[0] == 200
        # Third arg should be the File response type
        assert args[2] == daemon.HttpResponseType.File

    def test_handler_with_none_queries_and_body(self):
        """Handler should handle None queries and body gracefully."""
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        received = {}

        def capturing_handler(cmd, manager, body, queries):
            received["body"] = body
            received["queries"] = queries
            return {"status": 200, "body": '{}', "contentType": "application/json"}

        handler = daemon._make_async_handler(cmd, manager, capturing_handler)

        http_conn = MagicMock()
        # Simulate request with None attributes
        request = SimpleNamespace()  # no queries or body attrs
        http_conn.read_request = AsyncMock(return_value=request)
        http_conn.send_response = AsyncMock()

        asyncio.get_event_loop().run_until_complete(handler(http_conn))

        assert received["body"] == ""
        assert received["queries"] == {}


# --- build_directory_map edge cases ---


class TestBuildDirectoryMapEdgeCases:
    """Additional edge case tests for build_directory_map."""

    def test_path_without_volume_prefix(self):
        """Handles paths that lack the :/ separator (unusual but possible)."""
        daemon = _import_daemon()
        dirs = SimpleNamespace(
            filaments=None, firmware=None, g_codes=None,
            macros=None, menu=None, system="/sys", web=None,
        )
        model = SimpleNamespace(directories=dirs)
        result = daemon.build_directory_map(model)
        # Without :/ separator, the whole path is used as ref_folder
        assert "/sys/" in result

    def test_empty_string_values_skipped(self):
        """Empty string directory values are skipped."""
        daemon = _import_daemon()
        dirs = SimpleNamespace(
            filaments="", firmware="", g_codes="",
            macros="0:/macros", menu="", system="", web="",
        )
        model = SimpleNamespace(directories=dirs)
        result = daemon.build_directory_map(model)
        assert len(result) == 1
        assert "macros/" in result

    def test_non_string_values_skipped(self):
        """Non-string directory values (e.g. int, list) are skipped."""
        daemon = _import_daemon()
        dirs = SimpleNamespace(
            filaments=123, firmware=None, g_codes=["path"],
            macros="0:/macros", menu=False, system="0:/sys", web=0,
        )
        model = SimpleNamespace(directories=dirs)
        result = daemon.build_directory_map(model)
        assert len(result) == 2
        assert "macros/" in result
        assert "sys/" in result

    def test_missing_individual_attrs(self):
        """Directories object with only some known attrs."""
        daemon = _import_daemon()
        # Only has 'system' — all other _DIR_ATTRS fall back to getattr default
        dirs = SimpleNamespace(system="0:/sys")
        model = SimpleNamespace(directories=dirs)
        result = daemon.build_directory_map(model)
        assert result == {"sys/": "0:/sys/"}


# --- register_endpoints partial failure ---


class TestRegisterEndpointsPartialFailure:
    """Tests for register_endpoints when some endpoints fail to register."""

    def test_some_endpoints_fail_others_succeed(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()

        call_count = 0

        def add_endpoint_sometimes_fail(http_type, namespace, path):
            nonlocal call_count
            call_count += 1
            if path == "diff":
                raise RuntimeError("endpoint registration failed")
            ep = MagicMock()
            return ep

        cmd.add_http_endpoint.side_effect = add_endpoint_sometimes_fail

        registered = daemon.register_endpoints(cmd, manager)

        # Should have registered all except the 'diff' endpoint
        total_endpoints = len(daemon.ENDPOINTS)
        assert len(registered) == total_endpoints - 1

    def test_all_endpoints_succeed(self):
        daemon = _import_daemon()
        cmd = MagicMock()
        manager = MagicMock()
        ep = MagicMock()
        cmd.add_http_endpoint.return_value = ep

        registered = daemon.register_endpoints(cmd, manager)
        assert len(registered) == len(daemon.ENDPOINTS)
        # Each endpoint should have a handler set
        assert ep.set_endpoint_handler.call_count == len(daemon.ENDPOINTS)
