---
name: dwc-dsf-plugin-dev
description: Reference guide for developing DWC + DSF plugins for Duet3D printers. Use when building a new plugin, debugging DSF API issues, setting up plugin manifest, registering frontend routes, writing Python daemon code, testing without real hardware, or troubleshooting dsf-python bugs. Covers the full stack from plugin.json to CI/CD.
user-invocable: true
allowed-tools: Read, Grep, Glob
---

# DWC + DSF Plugin Developer Guide

Use this guide when developing plugins for DuetWebControl 3.6 + DuetSoftwareFramework.
Target stack: Vue 2.7 + Vuetify 2.7 + Vuex 3 (frontend), Python 3 + dsf-python v3.6 (backend).

---

## Plugin Manifest (plugin.json)

```jsonc
{
  "id": "MyPlugin",
  "name": "My Plugin",
  "version": "0.0.0",
  "data": {
    "myKey": "defaultValue"        // Pre-declare ALL keys used with SetPluginData
  }
  // "sbcData": {}                 // DSF v3.6 IGNORES this — do NOT use
}
```

- `data` is the ONLY field DSF reads for plugin key-value storage.
- Every key written with `cmd.set_plugin_data(id, key, value)` MUST be pre-declared in `data`.
- `sbcData` is silently ignored — no `SbcData` property exists in the DSF ObjectModel.

---

## Plugin Registration (Frontend)

```javascript
import { registerRoute } from '@/routes'
import MyPlugin from './MyPlugin.vue'

registerRoute(MyPlugin, {
    Plugins: {
        MyPlugin: {
            icon: 'mdi-cog',          // Material Design Icons
            caption: 'My Plugin',
            path: '/MyPlugin'          // becomes /plugins/MyPlugin
        }
    }
})
```

---

## DSF Python Bugs — Required Monkey-Patches

All patches go at the top of the daemon file. Wrap each in `try/except ImportError: pass` so tests work without the real dsf library.

### plugin.data always empty

`PluginManifest.__init__` creates `_data` as plain `dict`. Deserialization skips plain dicts.

```python
try:
    from dsf.object_model.plugins.plugin_manifest import PluginManifest as _PM
    from dsf.object_model.model_dictionary import ModelDictionary as _MD
    _orig_init = _PM.__init__
    def _patched_init(self):
        _orig_init(self)
        self._data = _MD(False)
    _PM.__init__ = _patched_init
except ImportError:
    pass
```

### resolve_path() returns Response object, not string

```python
response = cmd.resolve_path("0:/sys")
real_path = getattr(response, "result", response)
if not isinstance(real_path, str):
    real_path = str(real_path)
```

### BoardState enum missing values — crashes get_object_model()

DSF may report states like `timedOut` not in the enum. The setter raises `ValueError`, crashing the entire `get_object_model()` call.

```python
try:
    import dsf.object_model.boards.boards as _boards_mod
    from dsf.object_model.boards.boards import Board as _Board
    from enum import Enum

    class _PatchedBoardState(str, Enum):
        unknown = "unknown"
        flashing = "flashing"
        flashFailed = "flashFailed"
        resetting = "resetting"
        running = "running"
        timedOut = "timedOut"

    _boards_mod.BoardState = _PatchedBoardState

    def _safe_state_setter(self, value):
        try:
            if value is None or isinstance(value, _PatchedBoardState):
                self._state = value
            elif isinstance(value, str):
                self._state = _PatchedBoardState(value)
        except (ValueError, KeyError):
            self._state = _PatchedBoardState.unknown

    _Board.state = _Board.state.setter(_safe_state_setter)
except ImportError:
    pass
```

### No get_file() / put_file() on CommandConnection

These methods DO NOT EXIST. Use `cmd.resolve_path()` + standard `open()` for all file I/O.

---

## DSF ObjectModel API Rules

| Do this | Not this |
|---------|----------|
| `getattr(board, "firmware_version", "")` | `board.get("firmwareVersion")` |
| `model.plugins.get("MyPlugin")` | `getattr(model.plugins, "MyPlugin")` |
| `getattr(model.directories, "system", "")` | `model.directories["system"]` |
| `firmware_version` (snake_case) | `firmwareVersion` (camelCase) |

- `model.plugins` is a `ModelDictionary` (dict subclass) — `.get()` is fine there.
- `Board`, `Plugin`, `Directories` are typed ModelObjects — use `getattr()`.
- dsf-python auto-converts JSON camelCase to Python snake_case.

---

## File I/O on the Printer

```
Virtual path:   "0:/sys/config.g"
                     |  cmd.resolve_path("0:/sys")
Real FS path:   "/opt/dsf/sd/sys/config.g"
```

1. At daemon startup, call `cmd.resolve_path()` for each directory.
2. Store the mapping: `{"0:/sys/": "/opt/dsf/sd/sys/"}`.
3. Use standard `open()` with the resolved path for all reads/writes.
4. DSF directory values lack trailing slashes (`0:/sys`). Add them yourself.

---

## Persistent Data Location

```
/opt/dsf/plugins/MyPlugin/    <-- WIPED on uninstall/upgrade
/opt/dsf/sd/MyPlugin/         <-- Survives upgrades, safe for settings/data
```

DSF deletes the entire plugin directory on full uninstall. Always store settings, caches, and user data under `/opt/dsf/sd/YourPlugin/`.

---

## HTTP Endpoints

DSF uses exact path matching (no path parameters). Use query strings for dynamic values.

### Backend Registration

```python
def register_endpoints(cmd, manager):
    endpoints = []
    ROUTES = [
        ("GET",  "status",  handle_status),
        ("POST", "sync",    handle_sync),
        ("GET",  "diff",    handle_diff),
    ]
    for method, path, handler in ROUTES:
        ep = cmd.add_http_endpoint(method, f"/machine/MyPlugin/{path}")
        asyncio.ensure_future(_serve(ep, cmd, manager, handler))
        endpoints.append(ep)
    return endpoints

async def _serve(ep, cmd, manager, handler_func):
    while True:
        http_conn = await ep.accept()
        asyncio.ensure_future(_handle(http_conn, cmd, manager, handler_func))

async def _handle(http_conn, cmd, manager, handler_func):
    request = await http_conn.read_request()
    queries = getattr(request, "queries", {}) or {}
    body = getattr(request, "body", "") or ""
    response = handler_func(cmd, manager, body, queries)
    await http_conn.send_response(
        response.get("status", 200),
        response.get("body", ""),
        HttpResponseType.JSON,
    )
```

### Handler Pattern

```python
def handle_status(_cmd, manager, _body, _queries):
    return {"status": 200, "body": json.dumps({"status": "ok"})}

def handle_action(_cmd, manager, body, queries):
    file_param = queries.get("file", "")
    if not file_param:
        return {"status": 400, "body": json.dumps({"error": "file required"})}
    try:
        result = manager.do_something(file_param)
        return {"status": 200, "body": json.dumps(result)}
    except Exception as exc:
        logger.error("Error: %s", exc)
        return {"status": 500, "body": json.dumps({"error": str(exc)})}
```

### Frontend Calls

```javascript
async fetchStatus() {
  try {
    const resp = await fetch('/machine/MyPlugin/status')
    if (!resp.ok) {
      const err = await resp.json()
      this.error = err.error || 'Request failed'
      return
    }
    this.data = await resp.json()
  } catch (err) {
    this.error = 'Network error: ' + err.message
  }
}
```

Use plain `fetch()` — DWC doesn't expose `$fetch` to plugins. Always check `resp.ok` before parsing.

---

## Frontend: Vue 2.7 + Vuetify 2.7 Patterns

### Accessing Plugin Data from Vuex

```javascript
import { mapState } from 'vuex'

export default {
  computed: {
    ...mapState('machine/model', {
      pluginData(state) {
        // state.plugins is a Map in DWC 3.6, NOT a plain object
        if (state.plugins instanceof Map) {
          return state.plugins.get('MyPlugin')?.data || {}
        }
        return state.plugins?.MyPlugin?.data || {}
      }
    }),
    myValue() {
      return this.pluginData.myKey || 'default'
    }
  }
}
```

CRITICAL: `state.plugins` is a Map. Always guard with `instanceof Map`.

### Reactivity Gotchas (Vue 2)

- New object properties: `this.$set(obj, 'newKey', value)` — plain assignment is NOT reactive.
- Array mutation: use `splice`, `push`, `Vue.set` — index assignment (`arr[i] = x`) is NOT reactive.

---

## Daemon Startup Pattern

```python
def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    cmd = CommandConnection()
    cmd.connect()

    # Read firmware version + directory mappings
    try:
        model = cmd.get_object_model()
        boards = getattr(model, "boards", None) or []
        if boards:
            fw_version = getattr(boards[0], "firmware_version", "") or ""
        dir_map = build_directory_map(model)
    except Exception:
        dir_map = DEFAULT_DIRECTORY_MAP

    # Resolve virtual paths to real filesystem paths
    resolved_dirs = {}
    for ref_folder, printer_prefix in dir_map.items():
        try:
            response = cmd.resolve_path(printer_prefix.rstrip("/"))
            real_path = getattr(response, "result", response)
            if not isinstance(real_path, str):
                real_path = str(real_path)
            if not real_path.endswith("/"):
                real_path += "/"
            resolved_dirs[printer_prefix] = real_path
        except Exception:
            pass

    manager = MyManager(resolved_dirs=resolved_dirs)
    endpoints = register_endpoints(cmd, manager)

    try:
        while True:
            time.sleep(600)
    except KeyboardInterrupt:
        pass
    finally:
        for ep in endpoints:
            ep.close()
        cmd.close()
```

---

## Testing

### Backend (pytest)

**pyproject.toml:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["dsf"]
```

**Mock DSF modules BEFORE importing daemon:**
```python
import sys, types, importlib
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def mock_dsf(monkeypatch):
    dsf = types.ModuleType("dsf")
    dsf_conn = types.ModuleType("dsf.connections")
    dsf_http = types.ModuleType("dsf.http")
    dsf_om = types.ModuleType("dsf.object_model")

    class FakeHttpResponseType:
        JSON = "JSON"
        File = "File"
        PlainText = "PlainText"

    dsf_http.HttpResponseType = FakeHttpResponseType
    dsf_conn.CommandConnection = MagicMock

    for name, mod in [("dsf", dsf), ("dsf.connections", dsf_conn),
                       ("dsf.http", dsf_http), ("dsf.object_model", dsf_om)]:
        monkeypatch.setitem(sys.modules, name, mod)

def _import_daemon():
    spec = importlib.util.spec_from_file_location("daemon", "dsf/my-daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

**Mock ObjectModel objects with SimpleNamespace:**
```python
from types import SimpleNamespace

model = SimpleNamespace(
    boards=[SimpleNamespace(firmware_version="3.5.1", name="Duet 3")],
    directories=SimpleNamespace(system="0:/sys", macros="0:/macros"),
    plugins={"MyPlugin": SimpleNamespace(data={"myKey": "value"})}
)
```

### Frontend (Jest 29 + @vue/test-utils 1.x)

**jest.config.js:**
```javascript
module.exports = {
  testEnvironment: 'jsdom',
  transform: {
    '^.+\\.vue$': '@vue/vue2-jest',
    '^.+\\.js$': 'babel-jest'
  },
  testMatch: ['**/tests/frontend/**/*.test.js'],
  setupFiles: ['./tests/frontend/setup.js'],
  moduleNameMapper: { '^@/(.*)$': '<rootDir>/src/$1' }
}
```

**tests/frontend/setup.js:**
```javascript
import Vue from 'vue'
import Vuetify from 'vuetify'
Vue.use(Vuetify)
document.body.setAttribute('data-app', 'true')
global.createVuetify = () => new Vuetify()
```

**Vuex store mock with Map:**
```javascript
function createStore(pluginData = {}) {
  return new Vuex.Store({
    modules: {
      'machine/model': {
        namespaced: true,
        state: {
          plugins: new Map([['MyPlugin', { data: pluginData }]])
        }
      }
    }
  })
}
```

---

## Upstream API Verification

dsf-python, DWC, and DSF are NOT installed locally. Before using any API:

```bash
git clone --branch v3.6-dev --depth 1 https://github.com/Duet3D/dsf-python.git /tmp/dsf-python
git clone --branch v3.6-dev --depth 1 https://github.com/Duet3D/DuetWebControl.git /tmp/DuetWebControl
```

Key dsf-python source locations:
- `src/dsf/object_model/object_model.py` — ObjectModel (`.boards`, `.plugins`, `.state`)
- `src/dsf/object_model/boards/boards.py` — Board (`.firmware_version`, `.name`)
- `src/dsf/object_model/plugins/plugin_manifest.py` — PluginManifest (`.data`, `.id`)
- `src/dsf/object_model/directories/directories.py` — Directories (`.system`, `.macros`)
- `src/dsf/connections/base_command_connection.py` — CommandConnection methods

---

## Quick-Start Checklist

1. Create `plugin.json` with `data` field (not `sbcData`) — pre-declare all keys
2. Create `src/index.js` with `registerRoute`
3. Create main Vue component with Vuetify 2.7
4. Access plugin data via `state.plugins.get('ID')?.data` with Map guard
5. Create Python daemon with DSF monkey-patches at the top
6. Resolve virtual paths at startup, store mapping
7. Store persistent data in `/opt/dsf/sd/YourPlugin/`
8. Register HTTP endpoints with `cmd.add_http_endpoint()`
9. Use `getattr()` for ObjectModel access, never `.get()` on typed objects
10. Set up pytest with dsf module mocks (mock before import)
11. Set up Jest with Vue 2 test utils and Vuetify setup
12. Create CI: Python tests -> Frontend lint+tests -> DWC build

---

## Pitfalls Quick Reference

| Pitfall | Fix |
|---------|-----|
| `plugin.data` always empty | Monkey-patch `PluginManifest.__init__` to use `ModelDictionary` |
| `resolve_path()` returns object | `getattr(response, "result", response)` |
| `BoardState` crash on unknown values | Replace enum + safe setter |
| `get_file()`/`put_file()` missing | `resolve_path()` + `open()` |
| `state.plugins` is a Map | Guard with `instanceof Map` |
| Plugin dir wiped on upgrade | Use `/opt/dsf/sd/YourPlugin/` |
| `sbcData` ignored | Use `data` field only |
| camelCase in Python | dsf-python auto-converts to snake_case |
| `.get()` on typed objects | `getattr(obj, "attr", default)` |
| Trailing slashes missing | DSF omits them — add manually |
| Tests import daemon before mocks | Set up `sys.modules` mocks first |
| Vue 2 reactivity for new keys | `this.$set()` |
