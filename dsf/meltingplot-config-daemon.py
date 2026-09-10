#!/usr/bin/env python3
"""Meltingplot Config — DSF SBC daemon.

Connects to DSF via Unix socket, registers HTTP endpoints, and handles
config sync / diff / apply requests from the DWC frontend.
"""

import json
import logging
import os
import sys
import tempfile
import time
import traceback
from urllib.parse import unquote

from dsf.connections import CommandConnection
from dsf.http import HttpEndpointConnection, HttpResponseType
from dsf.object_model import HttpEndpointType

# --- dsf-python workarounds -------------------------------------------------
#
# These paper over bugs in the dsf-python library itself. Each one is applied
# through _apply_dsf_workaround so that a library that has moved on cannot take
# the daemon down at import time: a workaround that no longer fits is reported
# and skipped, not raised.
#
# Verified against dsf-python v3.6-dev and v3.7-dev. The module paths, the
# PluginManifest constructor and the Board/NetworkInterface property objects all
# survive in 3.7, so every patch below still applies there. What changed is how
# much of each one is still doing work — noted per patch.


def _apply_dsf_workaround(name, patch):
    """Apply one dsf-python workaround, tolerating a library that moved on.

    :param name: Short identifier used in the warning
    :param patch: Callable performing the patch
    """
    try:
        patch()
    except ImportError:
        pass  # dsf not installed (e.g. test environment)
    except Exception as exc:  # noqa: BLE001 - never let a workaround be fatal
        print(
            f"[MeltingplotConfig] dsf-python workaround '{name}' did not apply: "
            f"{exc.__class__.__name__}: {exc}",
            file=sys.stderr,
        )


def _patch_plugin_manifest_data():
    """PluginManifest._data is a plain dict that _update_from_json skips.

    dsf-python 3.6 initialises `_data` as `{}`, and `_update_from_json` only
    handles ModelObject, ModelCollection, ModelDictionary and list — plain
    dicts are silently ignored, so `plugin.data` stays empty forever.

    Replacing it with a ModelDictionary makes deserialization populate it.

    dsf-python 3.7 fixed this (`data = model_prop('data', ModelDictionary, ...)`),
    where `_data` is that property's storage. Assigning a fresh empty
    ModelDictionary there is exactly what the property's own default does, so
    this is redundant but harmless on 3.7.
    """
    from dsf.object_model.model_dictionary import ModelDictionary
    from dsf.object_model.plugins.plugin_manifest import PluginManifest

    original_init = PluginManifest.__init__

    def patched_init(self):
        original_init(self)
        self._data = ModelDictionary(False)

    PluginManifest.__init__ = patched_init


def _patch_board_state():
    """BoardState is missing values DSF reports, e.g. "timedOut".

    The Board.state setter coerces through BoardState(value), which raises
    ValueError for anything unlisted — and that crashes get_object_model()
    entirely, losing firmware detection and the directory mapping.

    Still missing in dsf-python 3.7, so this patch is load-bearing on both.

    Two parts: replace the enum, and replace the setter. On 3.6 the setter
    reads the module-level name, so swapping the enum is what fixes it; on 3.7
    the property captured the enum at class-definition time and ignores the
    swap, so there the replaced setter is what does the work. Keeping both
    covers either library.
    """
    from enum import Enum

    import dsf.object_model.boards.boards as boards_module
    from dsf.object_model.boards.boards import Board

    class PatchedBoardState(str, Enum):
        """Replacement BoardState that includes all known DSF states."""

        unknown = "unknown"
        flashing = "flashing"
        flashFailed = "flashFailed"
        resetting = "resetting"
        running = "running"
        timedOut = "timedOut"

    boards_module.BoardState = PatchedBoardState

    def safe_state_setter(self, value):
        try:
            if value is None or isinstance(value, PatchedBoardState):
                self._state = value
            elif isinstance(value, str):
                self._state = PatchedBoardState(value)
            else:
                raise TypeError(f"invalid type for Board.state: {type(value)}")
        except (ValueError, KeyError):
            self._state = PatchedBoardState.unknown

    Board.state = Board.state.setter(safe_state_setter)


def _patch_network_interface_type():
    """NetworkInterfaceType is missing values DSF reports.

    dsf-python 3.6 defines only "lan" and "wifi", while DSF 3.6.3-rc.1 reports
    "ethernet" for wired interfaces — and the setter's coercion raises
    ValueError, crashing get_object_model().

    dsf-python 3.7 added "ethernet" but dropped "lan", so the same class of
    crash just moved to the other value. The replacement enum below carries
    "lan", "wifi", "ethernet" and an "unknown" fallback, which covers both.

    Same two parts, for the same reason, as the BoardState patch.
    """
    from enum import Enum

    import dsf.object_model.network.network_interface as ni_module
    import dsf.object_model.network.network_interface_type as nit_module
    from dsf.object_model.network.network_interface import NetworkInterface

    class PatchedNetworkInterfaceType(str, Enum):
        """Replacement NetworkInterfaceType covering 3.6 and 3.7 values."""

        unknown = "unknown"
        lan = "lan"
        wifi = "wifi"
        ethernet = "ethernet"

    nit_module.NetworkInterfaceType = PatchedNetworkInterfaceType
    ni_module.NetworkInterfaceType = PatchedNetworkInterfaceType

    def safe_type_setter(self, value):
        try:
            if value is None or value == "":
                self._type = PatchedNetworkInterfaceType.wifi
            elif isinstance(value, PatchedNetworkInterfaceType):
                self._type = value
            elif isinstance(value, str):
                self._type = PatchedNetworkInterfaceType(value)
            else:
                raise TypeError(
                    f"invalid type for NetworkInterface.type: {type(value)}"
                )
        except (ValueError, KeyError):
            self._type = PatchedNetworkInterfaceType.unknown

    NetworkInterface.type = NetworkInterface.type.setter(safe_type_setter)


_apply_dsf_workaround("PluginManifest.data", _patch_plugin_manifest_data)
_apply_dsf_workaround("BoardState", _patch_board_state)
_apply_dsf_workaround("NetworkInterfaceType", _patch_network_interface_type)

# --- end dsf-python workarounds ---------------------------------------------

from config_manager import ConfigManager, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("MeltingplotConfig")

PLUGIN_ID = "MeltingplotConfig"
API_NAMESPACE = "MeltingplotConfig"

# --- Persistent settings (survive plugin upgrade/reinstall) ---

# Settings file lives in DATA_DIR (on the SD card), not in the plugin
# directory, because DSF wipes plugin files during upgrade/reinstall.
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Plugin data keys that are persisted to disk.  detectedFirmwareVersion is
# excluded because it is re-detected from hardware at every startup.
PERSISTED_KEYS = [
    "referenceRepoUrl",
    "firmwareBranchOverride",
    "activeBranch",
    "lastSyncTimestamp",
    "status",
]


def _load_settings_file(path):
    """Read and parse a single settings file, returning a filtered dict."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in PERSISTED_KEYS}
    except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
        return {}


def load_settings_from_disk():
    """Load persisted plugin settings from disk.

    Returns a dict of key-value pairs, or {} if no file is found.
    """
    return _load_settings_file(SETTINGS_FILE)


def save_settings_to_disk(updates):
    """Merge *updates* into the persisted settings file.

    Reads the current file, updates only PERSISTED_KEYS, and writes back.
    """
    try:
        current = load_settings_from_disk()
        for key, value in updates.items():
            if key in PERSISTED_KEYS:
                current[key] = value
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except (IOError, OSError) as exc:
        logger.warning("Failed to save settings to disk: %s", exc)


# --- Directory mapping from DSF object model ---

# Known directory property names on the DSF Directories object (snake_case).
_DIR_ATTRS = ["filaments", "firmware", "g_codes", "macros", "menu", "system", "web"]


def build_directory_map(model):
    """Build a ref-folder → printer-path mapping from the DSF object model.

    Reads model.directories (a typed Directories object with properties like
    'system' → '0:/sys', 'macros' → '0:/macros', etc.) and produces a dict
    mapping reference repo top-level folders to full printer paths:
        {'sys/': '0:/sys/', 'macros/': '0:/macros/', ...}
    """
    dirs = getattr(model, "directories", None)
    if dirs is None:
        return {}

    dir_map = {}
    for attr in _DIR_ATTRS:
        dsf_path = getattr(dirs, attr, None)
        if not dsf_path or not isinstance(dsf_path, str):
            continue
        # Ensure trailing slash: "0:/sys" -> "0:/sys/"
        if not dsf_path.endswith("/"):
            dsf_path += "/"
        # Extract folder name after volume prefix: "0:/sys/" -> "sys/"
        if ":/" in dsf_path:
            ref_folder = dsf_path.split(":/", 1)[1]
        else:
            ref_folder = dsf_path
        if ref_folder:
            dir_map[ref_folder] = dsf_path

    return dir_map


# --- Plugin data helpers ---


def get_plugin_data(cmd):
    """Read plugin data from the DSF object model.

    Relies on the monkey-patch above that changes PluginManifest._data
    from a plain dict to ModelDictionary(False), so _update_from_json
    populates it correctly.
    """
    try:
        model = cmd.get_object_model()
        plugins = getattr(model, "plugins", None) or {}
        plugin = plugins.get(PLUGIN_ID) if isinstance(plugins, dict) else None
        if plugin is None:
            return {}
        data = getattr(plugin, "data", None)
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_plugin_data(cmd, key, value):
    """Update a single field in plugin data."""
    try:
        cmd.set_plugin_data(PLUGIN_ID, key, value)
    except Exception as exc:
        logger.warning("Failed to set plugin data %s=%s: %s", key, value, exc)


# --- JSON response helpers ---


def json_response(body, status=200):
    """Create a JSON response dict."""
    return {"status": status, "body": json.dumps(body), "contentType": "application/json"}


def error_response(message, status=400):
    return json_response({"error": message}, status=status)


# --- HTTP endpoint handlers ---
# Each handler takes (cmd, manager, body, queries) and returns a response dict.


def handle_status(cmd, manager, _body, _queries):
    """GET /machine/MeltingplotConfig/status"""
    data = get_plugin_data(cmd)
    branches = manager.get_branches()
    return json_response({
        "status": data.get("status", "not_configured"),
        "detectedFirmwareVersion": data.get("detectedFirmwareVersion", ""),
        "activeBranch": data.get("activeBranch", ""),
        "referenceRepoUrl": data.get("referenceRepoUrl", ""),
        "lastSyncTimestamp": data.get("lastSyncTimestamp", ""),
        "branches": branches,
    })


def handle_sync(cmd, manager, _body, _queries):
    """POST /machine/MeltingplotConfig/sync"""
    data = get_plugin_data(cmd)
    repo_url = data.get("referenceRepoUrl", "")
    fw_version = data.get("detectedFirmwareVersion", "")
    override = data.get("firmwareBranchOverride", "")

    result = manager.sync(repo_url, fw_version, branch_override=override)
    if "error" in result:
        # Update status to sync_error so the UI reflects the failure
        new_status = "sync_error" if result.get("networkError") else "error"
        set_plugin_data(cmd, "status", new_status)
        save_settings_to_disk({"status": new_status})
        return error_response(result["error"])

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    set_plugin_data(cmd, "activeBranch", result["activeBranch"])
    set_plugin_data(cmd, "lastSyncTimestamp", now)
    set_plugin_data(cmd, "status", "up_to_date")

    save_settings_to_disk({
        "activeBranch": result["activeBranch"],
        "lastSyncTimestamp": now,
        "status": "up_to_date",
    })

    return json_response(result)


def handle_branches(_cmd, manager, _body, _queries):
    """GET /machine/MeltingplotConfig/branches"""
    return json_response({"branches": manager.get_branches()})


def handle_diff(_cmd, manager, _body, queries):
    """GET /machine/MeltingplotConfig/diff[?file=<path>]

    Without file param: returns all file diffs.
    With file param: returns detailed diff for a single file.
    """
    file_param = queries.get("file", "")
    if file_param:
        result = manager.diff_file(unquote(file_param))
        if "error" in result:
            return error_response(result["error"])
        return json_response(result)

    files = manager.diff_all()
    return json_response({"files": files})


def handle_reference(_cmd, manager, _body, _queries):
    """GET /machine/MeltingplotConfig/reference"""
    return json_response({"files": manager.list_reference_files()})


def handle_backups(_cmd, manager, _body, _queries):
    """GET /machine/MeltingplotConfig/backups"""
    return json_response({"backups": manager.get_backups()})


def handle_apply(_cmd, manager, body, queries):
    """POST /machine/MeltingplotConfig/apply[?file=<path>]

    Without file param: applies all reference config.
    With file param: applies a single file.
    """
    file_param = queries.get("file", "")
    if file_param:
        result = manager.apply_file(unquote(file_param))
    else:
        result = manager.apply_all()
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


def handle_apply_hunks(_cmd, manager, body, queries):
    """POST /machine/MeltingplotConfig/applyHunks?file=<path>

    Body: {"hunks": [0, 2, 5]}
    """
    file_param = queries.get("file", "")
    if not file_param:
        return error_response("File path required (use ?file= query param)")
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return error_response("Invalid JSON body")
    hunk_indices = data.get("hunks", [])
    if not isinstance(hunk_indices, list):
        return error_response("'hunks' must be a list of indices")
    result = manager.apply_hunks(unquote(file_param), hunk_indices)
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


def handle_apply_selection(_cmd, manager, body, _queries):
    """POST /machine/MeltingplotConfig/applySelection

    Body: {"files": ["sys/config.g", {"file": "sys/homeall.g", "hunks": [0, 2]}]}

    Applies everything the user left selected in one go: whole files for
    plain entries, only the listed hunks for entries carrying "hunks".
    Files the user deselected are simply absent from the payload.
    """
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return error_response("Invalid JSON body")
    if not isinstance(data, dict):
        return error_response("Invalid JSON body")
    files = data.get("files")
    if files is None:
        return error_response("'files' selection required")
    result = manager.apply_selection(files)
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


def handle_manual_backup(_cmd, manager, body, _queries):
    """POST /machine/MeltingplotConfig/manualBackup

    Body (optional): {"message": "My backup note"}
    """
    message = ""
    if body:
        try:
            data = json.loads(body)
            message = data.get("message", "")
        except json.JSONDecodeError:
            return error_response("Invalid JSON body")
    result = manager.create_manual_backup(message)
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


def handle_backup(_cmd, manager, _body, queries):
    """GET /machine/MeltingplotConfig/backup?hash=<hash>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    files = manager.get_backup_files(commit_hash)
    changed_files = manager.get_backup_changed_files(commit_hash)
    return json_response({
        "hash": commit_hash,
        "files": files,
        "changedFiles": changed_files,
    })


def handle_backup_download(_cmd, manager, _body, queries):
    """GET /machine/MeltingplotConfig/backupDownload?hash=<hash>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    try:
        archive_bytes = manager.get_backup_download(commit_hash)
        tmp = tempfile.NamedTemporaryFile(
            suffix=f"-backup-{commit_hash[:8]}.zip", delete=False
        )
        tmp.write(archive_bytes)
        tmp.close()
        return {
            "status": 200,
            "body": tmp.name,
            "contentType": "application/zip",
            "responseType": "file",
        }
    except Exception as exc:
        return error_response(f"Download failed: {exc}", status=500)


def handle_backup_file_content(_cmd, manager, _body, queries):
    """GET /machine/MeltingplotConfig/backupFileContent?hash=<hash>&file=<path>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    file_param = queries.get("file", "")
    if not file_param:
        return error_response("File path required (use ?file= query param)")
    result = manager.get_backup_file_content(commit_hash, unquote(file_param))
    return json_response(result)


def handle_backup_file_diff(_cmd, manager, _body, queries):
    """GET /machine/MeltingplotConfig/backupFileDiff?hash=<hash>&file=<path>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    file_param = queries.get("file", "")
    if not file_param:
        return error_response("File path required (use ?file= query param)")
    result = manager.get_backup_file_diff(commit_hash, unquote(file_param))
    return json_response(result)


def handle_restore(_cmd, manager, _body, queries):
    """POST /machine/MeltingplotConfig/restore?hash=<hash>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    result = manager.restore_backup(commit_hash)
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


def handle_delete_backup(_cmd, manager, _body, queries):
    """POST /machine/MeltingplotConfig/deleteBackup?hash=<hash>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    try:
        result = manager.delete_backup(commit_hash)
        return json_response(result)
    except RuntimeError as exc:
        return error_response(str(exc))


def handle_settings(cmd, _manager, body, _queries):
    """POST /machine/MeltingplotConfig/settings"""
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return error_response("Invalid JSON body")

    persisted_updates = {}
    if "referenceRepoUrl" in data:
        set_plugin_data(cmd, "referenceRepoUrl", data["referenceRepoUrl"])
        persisted_updates["referenceRepoUrl"] = data["referenceRepoUrl"]
    if "firmwareBranchOverride" in data:
        set_plugin_data(cmd, "firmwareBranchOverride", data["firmwareBranchOverride"])
        persisted_updates["firmwareBranchOverride"] = data["firmwareBranchOverride"]

    if persisted_updates:
        save_settings_to_disk(persisted_updates)

    return json_response({"ok": True})


# --- Endpoint registry ---
# Maps (HTTP_METHOD, endpoint_path) to handler function.
# Each DSF endpoint path is registered individually with its own async handler.

ENDPOINTS = {
    ("GET", "status"): handle_status,
    ("POST", "sync"): handle_sync,
    ("GET", "branches"): handle_branches,
    ("GET", "diff"): handle_diff,
    ("GET", "reference"): handle_reference,
    ("GET", "backups"): handle_backups,
    ("POST", "manualBackup"): handle_manual_backup,
    ("POST", "apply"): handle_apply,
    ("POST", "applyHunks"): handle_apply_hunks,
    ("POST", "applySelection"): handle_apply_selection,
    ("GET", "backup"): handle_backup,
    ("GET", "backupDownload"): handle_backup_download,
    ("GET", "backupFileContent"): handle_backup_file_content,
    ("GET", "backupFileDiff"): handle_backup_file_diff,
    ("POST", "restore"): handle_restore,
    ("POST", "deleteBackup"): handle_delete_backup,
    ("POST", "settings"): handle_settings,
}


# --- Async handler factory ---


def _make_async_handler(cmd, manager, handler_func):
    """Create an async HTTP handler for a dsf-python endpoint."""
    async def _handler(http_conn):
        request = await http_conn.read_request()
        try:
            queries = getattr(request, "queries", {}) or {}
            body = getattr(request, "body", "") or ""
            response = handler_func(cmd, manager, body, queries)

            content_type = response.get("contentType", "application/json")
            resp_type_str = response.get("responseType", "")

            if resp_type_str == "file":
                resp_type = HttpResponseType.File
            elif content_type == "application/json":
                resp_type = HttpResponseType.JSON
            else:
                resp_type = HttpResponseType.PlainText

            await http_conn.send_response(
                response.get("status", 200),
                response.get("body", ""),
                resp_type,
            )
        except Exception:
            logger.error("Handler error: %s", traceback.format_exc())
            await http_conn.send_response(
                500,
                json.dumps({"error": "Internal server error"}),
                HttpResponseType.JSON,
            )
    return _handler


# --- Registration and main ---


def register_endpoints(cmd, manager):
    """Register all HTTP endpoints with DSF and set async handlers."""
    registered = []
    for (method, path), handler_func in ENDPOINTS.items():
        http_type = HttpEndpointType.GET if method == "GET" else HttpEndpointType.POST
        try:
            endpoint = cmd.add_http_endpoint(http_type, API_NAMESPACE, path)
            endpoint.set_endpoint_handler(
                _make_async_handler(cmd, manager, handler_func)
            )
            registered.append(endpoint)
            logger.debug("Registered endpoint: %s /%s/%s", method, API_NAMESPACE, path)
        except Exception as exc:
            logger.error("Failed to register %s %s: %s", method, path, exc)
    return registered


def main():
    # Ensure persistent data directory exists (survives plugin upgrades)
    os.makedirs(DATA_DIR, exist_ok=True)

    cmd = CommandConnection()
    cmd.connect()

    # Restore persisted settings so user config survives plugin reload
    persisted = load_settings_from_disk()
    if persisted:
        for key, value in persisted.items():
            if value:  # skip empty strings
                set_plugin_data(cmd, key, value)
        logger.debug("Restored %d persisted setting(s) from disk", len(persisted))
    else:
        logger.debug("No persisted settings found, using defaults")

    # Read object model once at startup for firmware version + directory mappings
    dir_map = None
    fw_version = ""
    try:
        model = cmd.get_object_model()

        # Detect firmware version
        boards = getattr(model, "boards", None) or []
        if boards:
            fw_version = getattr(boards[0], "firmware_version", "") or ""
            if fw_version:
                set_plugin_data(cmd, "detectedFirmwareVersion", fw_version)

        # Build directory mapping from object model
        dir_map = build_directory_map(model)
        if not dir_map:
            logger.warning("No directory mappings from DSF, using defaults")
    except Exception as exc:
        logger.warning("Could not read object model: %s", exc)

    # Resolve virtual printer paths to real filesystem paths via DSF.
    # e.g. "0:/sys/" -> "/opt/dsf/sd/sys/"
    from config_manager import DEFAULT_DIRECTORY_MAP
    effective_dir_map = dir_map if dir_map else DEFAULT_DIRECTORY_MAP
    resolved_dirs = {}
    for ref_folder, printer_prefix in effective_dir_map.items():
        try:
            # resolve_path wants a path without trailing slash.
            # dsf-python's resolve_path returns a Response object (not a
            # plain string) — the actual path is in response.result.
            response = cmd.resolve_path(printer_prefix.rstrip("/"))
            real_path = getattr(response, "result", response)
            if not isinstance(real_path, str):
                real_path = str(real_path)
            if not real_path.endswith("/"):
                real_path += "/"
            resolved_dirs[printer_prefix] = real_path
            logger.debug("Resolved %s -> %s", printer_prefix, real_path)
        except Exception as exc:
            logger.warning("Could not resolve %s: %s", printer_prefix, exc)

    manager = ConfigManager(
        dsf_command_connection=cmd,
        directory_map=dir_map if dir_map else None,
        resolved_dirs=resolved_dirs if resolved_dirs else None,
    )

    # Register HTTP endpoints (each runs in its own async handler thread)
    endpoints = register_endpoints(cmd, manager)

    fw_info = f", firmware {fw_version}" if fw_version else ""
    logger.info("Ready — %d endpoints%s", len(endpoints), fw_info)

    # Keep main thread alive — endpoint handlers run in background threads
    try:
        while True:
            time.sleep(600)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        for ep in endpoints:
            ep.close()
        cmd.close()


if __name__ == "__main__":
    main()
