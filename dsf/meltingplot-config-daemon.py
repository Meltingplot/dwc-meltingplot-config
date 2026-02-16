#!/usr/bin/env python3
"""Meltingplot Config — DSF SBC daemon.

Connects to DSF via Unix socket, registers HTTP endpoints, and handles
config sync / diff / apply requests from the DWC frontend.
"""

import json
import logging
import sys
import traceback
from urllib.parse import unquote

from dsf.connections import CommandConnection, InterceptConnection
from dsf.commands.code import CodeResult
from dsf.http import HttpEndpointType

from config_manager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("MeltingplotConfig")

PLUGIN_ID = "MeltingplotConfig"
API_NAMESPACE = "MeltingplotConfig"

# Maps (method, route_suffix) -> handler function name
ROUTES = {}


def route(method, path):
    """Decorator to register an HTTP endpoint handler."""
    def decorator(func):
        ROUTES[(method, path)] = func
        return func
    return decorator


# --- Plugin data helpers ---


def get_plugin_data(cmd):
    """Read plugin sbcData from the DSF object model."""
    try:
        model = cmd.get_object_model()
        plugins = model.get("plugins", {})
        plugin = plugins.get(PLUGIN_ID, {})
        return plugin.get("sbcData", {})
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


@route("GET", "status")
def handle_status(cmd, manager, _body, _path_extra):
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


@route("POST", "sync")
def handle_sync(cmd, manager, _body, _path_extra):
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


@route("GET", "branches")
def handle_branches(_cmd, manager, _body, _path_extra):
    """GET /machine/MeltingplotConfig/branches"""
    return json_response({"branches": manager.get_branches()})


@route("GET", "diff")
def handle_diff(_cmd, manager, _body, _path_extra):
    """GET /machine/MeltingplotConfig/diff"""
    files = manager.diff_all()
    return json_response({"files": files})


@route("GET", "diff/")
def handle_diff_file(_cmd, manager, _body, path_extra):
    """GET /machine/MeltingplotConfig/diff/{file}"""
    if not path_extra:
        return error_response("File path required")
    result = manager.diff_file(unquote(path_extra))
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


@route("GET", "reference")
def handle_reference(_cmd, manager, _body, _path_extra):
    """GET /machine/MeltingplotConfig/reference"""
    from git_utils import list_files
    from config_manager import REFERENCE_DIR
    import os
    if not os.path.isdir(os.path.join(REFERENCE_DIR, ".git")):
        return json_response({"files": []})
    files = list_files(REFERENCE_DIR)
    return json_response({"files": files})


@route("GET", "backups")
def handle_backups(_cmd, manager, _body, _path_extra):
    """GET /machine/MeltingplotConfig/backups"""
    return json_response({"backups": manager.get_backups()})


@route("POST", "apply")
def handle_apply(_cmd, manager, _body, _path_extra):
    """POST /machine/MeltingplotConfig/apply"""
    result = manager.apply_all()
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


@route("POST", "apply/")
def handle_apply_file(_cmd, manager, body, path_extra):
    """POST /machine/MeltingplotConfig/apply/{file}[/hunks]"""
    if not path_extra:
        return error_response("File path required")

    # Check if this is a /hunks sub-route
    parts = path_extra.split("/hunks", 1)
    file_path = unquote(parts[0])

    if len(parts) > 1:
        # POST /apply/{file}/hunks
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return error_response("Invalid JSON body")
        hunk_indices = data.get("hunks", [])
        if not isinstance(hunk_indices, list):
            return error_response("'hunks' must be a list of indices")
        result = manager.apply_hunks(file_path, hunk_indices)
    else:
        # POST /apply/{file}
        result = manager.apply_file(file_path)

    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


@route("GET", "backup/")
def handle_backup_detail(_cmd, manager, _body, path_extra):
    """GET /machine/MeltingplotConfig/backup/{commitHash}[/download]"""
    if not path_extra:
        return error_response("Commit hash required")

    parts = path_extra.split("/download", 1)
    commit_hash = parts[0]

    if len(parts) > 1:
        # GET /backup/{hash}/download
        try:
            archive_bytes = manager.get_backup_download(commit_hash)
            return {
                "status": 200,
                "body": archive_bytes,
                "contentType": "application/zip",
                "headers": {
                    "Content-Disposition": f'attachment; filename="backup-{commit_hash[:8]}.zip"'
                },
            }
        except Exception as exc:
            return error_response(f"Download failed: {exc}", status=500)
    else:
        # GET /backup/{hash}
        files = manager.get_backup_files(commit_hash)
        return json_response({"hash": commit_hash, "files": files})


@route("POST", "restore/")
def handle_restore(_cmd, manager, _body, path_extra):
    """POST /machine/MeltingplotConfig/restore/{commitHash}"""
    if not path_extra:
        return error_response("Commit hash required")
    result = manager.restore_backup(path_extra)
    if "error" in result:
        return error_response(result["error"])
    return json_response(result)


@route("POST", "settings")
def handle_settings(cmd, _manager, body, _path_extra):
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


# --- Endpoint dispatch ---


def dispatch(cmd, manager, method, path, body):
    """Dispatch an HTTP request to the correct handler."""
    # path comes as the part after /machine/MeltingplotConfig/
    # Try exact match first, then prefix match with path_extra
    handler = ROUTES.get((method, path))
    if handler:
        return handler(cmd, manager, body, "")

    # Try prefix matching for routes that end with /
    for (route_method, route_path), handler in ROUTES.items():
        if route_method != method:
            continue
        if route_path.endswith("/") and path.startswith(route_path):
            path_extra = path[len(route_path):]
            return handler(cmd, manager, body, path_extra)

    return error_response(f"Unknown endpoint: {method} {path}", status=404)


# --- Main ---


def register_endpoints(cmd):
    """Register all HTTP GET and POST endpoints with DSF."""
    endpoint_paths = set()
    for method, path in ROUTES:
        # Register the base path (without trailing parts that are dynamic)
        base = path.rstrip("/")
        if not base:
            continue
        endpoint_paths.add((method, base))

    registered = []
    for method, path in sorted(endpoint_paths):
        http_type = (
            HttpEndpointType.GET if method == "GET" else HttpEndpointType.POST
        )
        try:
            cmd.add_http_endpoint(http_type, API_NAMESPACE, path)
            registered.append(f"{method} /{API_NAMESPACE}/{path}")
        except Exception as exc:
            logger.error("Failed to register %s %s: %s", method, path, exc)

    return registered


def main():
    logger.info("Meltingplot Config daemon starting...")

    cmd = CommandConnection()
    cmd.connect()
    logger.info("Connected to DSF")

    # Detect firmware version on startup
    try:
        model = cmd.get_object_model()
        boards = model.get("boards", [])
        if boards:
            fw = boards[0].get("firmwareVersion", "")
            if fw:
                set_plugin_data(cmd, "detectedFirmwareVersion", fw)
                logger.info("Detected firmware version: %s", fw)
    except Exception as exc:
        logger.warning("Could not detect firmware version: %s", exc)

    manager = ConfigManager(dsf_command_connection=cmd)

    # Register HTTP endpoints
    registered = register_endpoints(cmd)
    for ep in registered:
        logger.info("Registered endpoint: %s", ep)

    logger.info("Meltingplot Config daemon ready, entering event loop...")

    # Event loop: listen for HTTP requests
    try:
        while True:
            http_request = cmd.receive_http_request()
            if http_request is None:
                continue

            method = "GET" if http_request.endpoint_type == HttpEndpointType.GET else "POST"
            path = http_request.path.lstrip("/")
            body = http_request.body

            logger.debug("HTTP %s /%s", method, path)

            try:
                response = dispatch(cmd, manager, method, path, body)
                cmd.send_http_response(
                    response.get("status", 200),
                    response.get("body", ""),
                    response.get("contentType", "application/json"),
                )
            except Exception:
                logger.error("Handler error: %s", traceback.format_exc())
                cmd.send_http_response(
                    500,
                    json.dumps({"error": "Internal server error"}),
                    "application/json",
                )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        cmd.close()


if __name__ == "__main__":
    main()
