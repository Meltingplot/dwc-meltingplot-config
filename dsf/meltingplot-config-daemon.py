#!/usr/bin/env python3
"""Meltingplot Config — DSF SBC daemon.

Connects to DSF via Unix socket, registers HTTP endpoints, and handles
config sync / diff / apply requests from the DWC frontend.
"""

import json
import logging
import sys
import tempfile
import time
import traceback
from urllib.parse import unquote

from dsf.connections import CommandConnection
from dsf.http import HttpEndpointConnection, HttpResponseType
from dsf.object_model import HttpEndpointType

from config_manager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("MeltingplotConfig")

PLUGIN_ID = "MeltingplotConfig"
API_NAMESPACE = "MeltingplotConfig"


# --- Plugin data helpers ---


def get_plugin_data(cmd):
    """Read plugin data from the DSF object model.

    The DSF ObjectModel uses attribute access (not dict-style .get()).
    model.plugins is a ModelDictionary (dict subclass) keyed by plugin ID.
    Each Plugin has a .data dict holding custom key-value pairs set via
    CommandConnection.set_plugin_data().
    """
    try:
        model = cmd.get_object_model()
        plugins = getattr(model, "plugins", None) or {}
        plugin = plugins.get(PLUGIN_ID) if isinstance(plugins, dict) else None
        if plugin is None:
            return {}
        data = getattr(plugin, "data", None)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def set_plugin_data(cmd, key, value):
    """Update a single field in plugin sbcData."""
    try:
        cmd.set_plugin_data(key, value, PLUGIN_ID)
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
        return error_response(result["error"])

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    set_plugin_data(cmd, "activeBranch", result["activeBranch"])
    set_plugin_data(cmd, "lastSyncTimestamp", now)
    set_plugin_data(cmd, "status", "up_to_date")

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
    from git_utils import list_files
    from config_manager import REFERENCE_DIR
    import os
    if not os.path.isdir(os.path.join(REFERENCE_DIR, ".git")):
        return json_response({"files": []})
    files = list_files(REFERENCE_DIR)
    return json_response({"files": files})


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


def handle_backup(_cmd, manager, _body, queries):
    """GET /machine/MeltingplotConfig/backup?hash=<hash>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    files = manager.get_backup_files(commit_hash)
    return json_response({"hash": commit_hash, "files": files})


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


def handle_restore(_cmd, manager, _body, queries):
    """POST /machine/MeltingplotConfig/restore?hash=<hash>"""
    commit_hash = queries.get("hash", "")
    if not commit_hash:
        return error_response("Commit hash required (use ?hash= query param)")
    result = manager.restore_backup(commit_hash)
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


def handle_settings(cmd, _manager, body, _queries):
    """POST /machine/MeltingplotConfig/settings"""
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return error_response("Invalid JSON body")

    if "referenceRepoUrl" in data:
        set_plugin_data(cmd, "referenceRepoUrl", data["referenceRepoUrl"])
    if "firmwareBranchOverride" in data:
        set_plugin_data(cmd, "firmwareBranchOverride", data["firmwareBranchOverride"])

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
    ("POST", "apply"): handle_apply,
    ("POST", "applyHunks"): handle_apply_hunks,
    ("GET", "backup"): handle_backup,
    ("GET", "backupDownload"): handle_backup_download,
    ("POST", "restore"): handle_restore,
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
            logger.info("Registered endpoint: %s /%s/%s", method, API_NAMESPACE, path)
        except Exception as exc:
            logger.error("Failed to register %s %s: %s", method, path, exc)
    return registered


def main():
    logger.info("Meltingplot Config daemon starting...")

    cmd = CommandConnection()
    cmd.connect()
    logger.info("Connected to DSF")

    # Detect firmware version on startup
    # The DSF ObjectModel uses attribute access with snake_case names:
    #   model.boards -> list of Board objects
    #   board.firmware_version -> str
    try:
        model = cmd.get_object_model()
        boards = getattr(model, "boards", None) or []
        if boards:
            fw = getattr(boards[0], "firmware_version", "") or ""
            if fw:
                set_plugin_data(cmd, "detectedFirmwareVersion", fw)
                logger.info("Detected firmware version: %s", fw)
    except Exception as exc:
        logger.warning("Could not detect firmware version: %s", exc)

    manager = ConfigManager(dsf_command_connection=cmd)

    # Register HTTP endpoints (each runs in its own async handler thread)
    endpoints = register_endpoints(cmd, manager)

    logger.info(
        "Meltingplot Config daemon ready, %d endpoints registered",
        len(endpoints),
    )

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
