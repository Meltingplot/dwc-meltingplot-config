# CLAUDE.md

## Project Overview

**dwc-meltingplot-config** is a combined DWC + DSF plugin for Meltingplot 3D printers. It syncs reference configurations from a git repository, diffs them against the printer's current config, and lets users apply updates (all at once, per file, or per hunk). All config changes are backed up in a local git repo.

## Repository Structure

```
dwc-meltingplot-config/
├── plugin.json                        # DWC+DSF plugin manifest
├── src/                               # DWC frontend (Vue 2.7 + Vuetify 2.7)
│   ├── index.js                       # Entry point — registers route under Plugins menu
│   ├── MeltingplotConfig.vue          # Main page: tabs for Status/Changes/History/Settings
│   └── components/
│       ├── ConfigStatus.vue           # Status dashboard (FW version, sync status, branch)
│       ├── ConfigDiff.vue             # Diff viewer with hunk-level checkboxes and apply
│       └── BackupHistory.vue          # Backup list with download and restore buttons
├── dsf/                               # SBC backend (Python 3)
│   ├── meltingplot-config-daemon.py   # Main daemon — DSF connection, HTTP endpoint dispatch
│   ├── config_manager.py             # Core logic: sync, diff, apply (full/file/hunks), backup
│   └── git_utils.py                  # Git CLI wrapper (clone, fetch, checkout, backup repo)
├── .gitignore
├── CLAUDE.md                          # This file
├── PLAN.md                            # Detailed architecture and implementation plan
└── README.md                          # User-facing build and install docs
```

## Language & Ecosystem

- **Frontend:** Vue.js 2.7 + Vuetify 2.7 (DWC 3.6 uses Vue 2.7 + Vuetify 2.7 + Vuex 3)
  - **Source:** `v3.6-dev` branch of [Duet3D/DuetWebControl](https://github.com/Duet3D/DuetWebControl/tree/v3.6-dev)
- **Backend:** Python 3 (runs as DSF SBC plugin process)
  - **Source:** `v3.6-dev` branch of [Duet3D/DuetSoftwareFramework](https://github.com/Duet3D/DuetSoftwareFramework/tree/v3.6-dev)
- **State management:** Vuex 3 (machine model via `machine/model` store)
  - In DWC 3.6, `state.plugins` is a **Map** (not a plain object) keyed by plugin ID
  - Each value is a **full Plugin object** (id, name, version, data, …) — custom data lives in `plugin.data`
  - Access pattern: `state.plugins.get('MeltingplotConfig')?.data?.someKey`
  - Use `instanceof Map` guard for test compatibility (tests may use plain objects)
- **Bundler:** Webpack (Vue CLI 5) via DWC's `build-plugin` script
- **DSF communication:** `dsf-python` library v3.6-dev (Unix socket, installed via `sbcPythonDependencies` in plugin venv)
  - **Source:** `v3.6-dev` branch of [Duet3D/dsf-python](https://github.com/Duet3D/dsf-python/tree/v3.6-dev)
  - **ObjectModel API:** uses **attribute access** with **snake_case** names (not dict `.get()`). Use `getattr(obj, "attr", default)` for safe access.
  - `model.boards` → `List[Board]`; `board.firmware_version` → `str`
  - `model.plugins` → `ModelDictionary` (dict subclass, keyed by plugin ID); `plugin.data` → `dict` of custom key-value pairs
  - Write plugin data via `cmd.set_plugin_data(plugin_id, key, value)`; read it back from `plugin.data[key]`
  - **Plugin manifest `data` vs `sbcData`:** DSF v3.6 only recognises the `data` field in `plugin.json`. There is **no `SbcData` property** in the DSF ObjectModel — `sbcData` in the manifest is silently ignored. Keys used with `SetPluginData` **must** be pre-declared in the `data` section of `plugin.json`.
  - Key class paths in dsf-python: `dsf.object_model.ObjectModel`, `dsf.object_model.boards.Board`, `dsf.object_model.plugins.Plugin` / `PluginManifest`
- **Git operations:** `git` CLI via subprocess
- **Diffing/patching:** Python `difflib` (standard library)
- **Target DWC version:** 3.6 (`v3.6-dev` branch of Duet3D/DuetWebControl)

## Known dsf-python Bugs & Runtime Workarounds

These bugs exist in dsf-python v3.6-dev and are worked around in our daemon at startup. **Do not remove these workarounds** — they are required for correct operation on real hardware.

### 1. PluginManifest._data deserialization bug

**Bug:** `PluginManifest.__init__` initialises `_data` as a plain `dict {}`. The `_update_from_json()` method only handles `ModelObject`, `ModelCollection`, `ModelDictionary`, and `list` — it silently **skips** plain `dict` properties. This means `get_object_model().plugins[id].data` is always `{}`.

**Workaround:** Monkey-patch `PluginManifest.__init__` to replace `_data` with `ModelDictionary(False)` at import time in `meltingplot-config-daemon.py` (lines 24-36). This makes `_update_from_json` populate `plugin.data` correctly.

**Important:** The monkey-patch import is wrapped in `try/except ImportError: pass` so tests can run without the real dsf library installed.

### 2. No `get_file()` / `put_file()` methods on CommandConnection

**Bug:** `dsf.connections.CommandConnection` has **no** `get_file()` or `put_file()` methods, despite what documentation might suggest. Calling them raises `AttributeError`.

**Workaround:** At daemon startup, use `cmd.resolve_path("0:/sys")` to convert virtual printer paths (e.g., `"0:/sys"`) to real filesystem paths (e.g., `"/opt/dsf/sd/sys"`). Then use standard Python `open()` for all file I/O. The `ConfigManager` stores a `resolved_dirs` mapping for this purpose.

### 3. DSF Directories object — typed ModelObject, not a dict

**Finding:** `model.directories` is a typed `Directories` ModelObject with named snake_case properties (`filaments`, `firmware`, `g_codes`, `macros`, `menu`, `system`, `web`). Values are strings like `"0:/sys"` (no trailing slash). This is **not a dict** — use `getattr()` for attribute access.

**Our implementation:** `build_directory_map(model)` in the daemon reads these attributes and builds a `ref_folder → printer_path` mapping (e.g., `{"sys/": "0:/sys/"}`). This mapping is passed to `ConfigManager` to convert between reference repo paths and printer paths.

### 4. `resolve_path()` returns a Response object, not a string

**Bug:** `BaseCommandConnection.resolve_path()` returns the raw `Response` object from `perform_command()`. Unlike other methods (e.g., `remove_http_endpoint`, `set_network_protocol`) which unwrap with `res.result`, `resolve_path` does not. Calling `.endswith()` on the Response fails with `AttributeError`.

**Workaround:** Extract the actual path via `getattr(response, "result", response)` after calling `cmd.resolve_path()`. The daemon does this in the path-resolution loop at startup.

## Development Setup

### Building the frontend

```bash
git clone -b v3.6-dev https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl && npm install
npm run build-plugin /path/to/dwc-meltingplot-config
```

Output: `dist/MeltingplotConfig-<version>.zip`

### Backend

The Python backend requires no build step. It runs on the SBC under DSF.

## Testing

### Testing strategy

Neither DuetWebControl nor DuetSoftwareFramework have end-to-end tests for plugins. DWC has zero test infrastructure. DSF has NUnit unit tests for code parsing and model deserialization only. dsf-python uses mock Unix socket servers with threading for protocol-level tests.

Our testing strategy fills this gap with four layers:

1. **Unit tests** — Test individual functions/methods in isolation (mocked dependencies)
2. **Integration tests** — Test ConfigManager with real git repos and temp filesystems
3. **E2E backend tests** — Wire daemon handlers to real ConfigManager with real git + filesystem, exercising the full Python chain: `handler → config_manager → git_utils → filesystem`
4. **Frontend E2E tests** — Mount full Vue component tree with MockBackend, testing user flows through the UI
5. **API contract tests** — Validate that daemon handler response shapes match what frontend components expect

### Backend (Python)

- **Framework:** pytest
- **Run:** `pytest tests/ -v` (uses `pyproject.toml` for pythonpath config)
- **Install:** `pip install pytest`
- **Test files:**
  - `tests/test_git_utils.py` — Git operations (clone, fetch, branches, backup repo)
  - `tests/test_config_manager.py` — Diff engine, hunk parsing, hunk apply, path conversion, round-trip
  - `tests/test_daemon.py` — Response helpers, handler functions, endpoint registry (mocks DSF library)
  - `tests/test_daemon_handlers.py` — Handler edge cases, plugin data helpers, register_endpoints
  - `tests/test_integration.py` — Full sync → diff → apply → backup → restore round-trip with real git repos
  - `tests/test_e2e.py` — **End-to-end**: daemon handlers wired to real ConfigManager, real git repos, and real temp filesystem — tests the complete backend chain without mocks

### Frontend (JavaScript)

- **Framework:** Jest 29 + @vue/test-utils 1.x (Vue 2)
- **Install:** `npm install` (installs devDependencies including Jest)
- **Run:** `npm test`
- **Test files (in `tests/frontend/`):**
  - `ConfigStatus.test.js` — Props rendering, status mapping, button state, events
  - `ConfigDiff.test.js` — File filtering, hunk selection/deselection, emit payloads, side-by-side diff logic
  - `BackupHistory.test.js` — Empty/loading states, backup display, expand/collapse, fetch mocking
- **Integration tests (in `tests/frontend/integration/`):**
  - `full-mount.test.js` — Full component tree with real Vuetify
  - `plugin-registration.test.js` — DWC plugin registration contract
  - `plugin-structure.test.js` — Plugin ZIP structure validation
  - `user-flows.test.js` — End-to-end user flows with mock backend
  - `api-contract.test.js` — Validates daemon API response shapes match frontend component expectations

## Linting & Formatting

- **Frontend linter:** ESLint 8 with `eslint-plugin-vue` (Vue 2 recommended rules)
- **Run lint:** `npm run lint`
- **Config:** `.eslintrc.js`

## Building

The plugin is built via DWC's `build-plugin` command, which compiles Vue components with webpack and packages everything into an installable ZIP. The CI workflow handles this automatically.

For local development, a standalone `scripts/build-zip.js` packages source files into a ZIP for structure validation.

## CI/CD

GitHub Actions workflow at `.github/workflows/ci.yml` (3 stages):

1. **Python Tests** — runs `pytest` on Python 3.9, 3.10, 3.11, 3.12
2. **Frontend Lint & Tests** — runs `npm run lint` + `npm test` with Node.js 18
3. **Build** — checks out DuetWebControl `v3.6-dev`, runs `build-plugin`, uploads artifact (30-day retention)

**Triggers:** push to `main`/`master`, pull requests to `main`/`master`, manual `workflow_dispatch` with optional DWC ref override.

## Key Architecture Decisions

| Decision | Choice |
|----------|--------|
| Target DWC version | 3.6 (`v3.6-dev` branch — Vue 2.7 + Vuetify 2.7) |
| Reference config source | Git repo — one repo per printer model |
| Firmware versioning | One branch per firmware version |
| Backend runtime | Python SBC daemon via DSF (venv with `sbcPythonDependencies`) |
| Persistent data location | `/opt/dsf/sd/MeltingplotConfig/` — survives plugin upgrades (DSF wipes `PLUGIN_DIR`) |
| Backup strategy | Worktree-based git repo — tracks sys/, macros/, filaments/ in-place |
| Partial apply | Hunk-level selection — users pick individual change blocks |

## HTTP API

All endpoints are under `/machine/MeltingplotConfig/`. Each endpoint is registered separately with DSF via `add_http_endpoint()` and handled by an async callback. Dynamic parameters use query strings (DSF does exact path matching, no path parameters).

- `GET /status` — sync status, firmware version, active branch
- `POST /sync` — fetch + checkout reference repo
- `GET /diff` — full diff (all files); with `?file=<path>` returns single file diff with indexed hunks
- `GET /reference` — list files in reference repo
- `GET /branches` — list available branches
- `POST /apply` — apply all changes (with backup); with `?file=<path>` applies single file
- `POST /applyHunks?file=<path>` — apply selected hunks (body: `{"hunks": [0, 2, 5]}`)
- `GET /backups` — backup history
- `GET /backup?hash=<hash>` — backup file list
- `GET /backupDownload?hash=<hash>` — download backup as ZIP
- `POST /restore?hash=<hash>` — restore from backup
- `POST /settings` — update plugin settings

## Git Workflow

- **Default remote branch:** `main`
- **Commit messages:** Use clear, descriptive messages summarizing the change

## Conventions for AI Assistants

- Frontend: Vue 2.7 + Vuetify 2.7 conventions (DWC 3.6). Use `v-model`, `$set` for reactivity, `mapState`/`mapGetters` for Vuex.
- Frontend plugin data: Access via `state.plugins.get('MeltingplotConfig')?.data` (Map) with a plain-object fallback for tests. Never read custom data directly off the plugin object — it lives in `plugin.data`.
- Frontend test mocks: `createStore(pluginData)` wraps the data as `{ MeltingplotConfig: { data: pluginData } }` to match the real Plugin object structure.
- Backend: Follow PEP 8 / PEP 257. Use `logging` module, not print.
- DSF ObjectModel: **never use dict-style `.get()` on model objects**. Use `getattr(obj, "snake_case_name", default)` for safe attribute access. `model.plugins` is a dict so `.get()` is fine there, but `Plugin`, `Board`, etc. are typed objects with snake_case properties.
- DSF plugin data: Use the `data` field (not `sbcData`) in `plugin.json` for all custom key-value pairs. DSF v3.6 ignores `sbcData` entirely. `SetPluginData` requires keys to already exist in `data`.
- DSF file I/O: Use `cmd.resolve_path(printer_path)` + standard `open()`. **Never** call `cmd.get_file()` or `cmd.put_file()` — they do not exist on CommandConnection.
- Test mocks for DSF ObjectModel: use `types.SimpleNamespace` to simulate typed objects (e.g., `SimpleNamespace(firmware_version="3.5")` for a Board, `SimpleNamespace(data={...})` for a Plugin). Do not use plain dicts for objects that are not dicts in production.
- Prefer editing existing files over creating new ones.
- Do not add unnecessary abstractions or over-engineer solutions.
- Keep this CLAUDE.md updated as the project evolves.

### Common debugging pitfalls

These patterns have caused real bugs in this project. Be aware of them:

1. **Summary hunks vs detail hunks:** `diff_all()` returns summary hunks `{index, header}` only. `diff_file()` returns full hunks with `{index, header, lines, summary}`. Frontend guard logic must check for `hunk.lines` (not just `hunk` truthiness) to decide whether to fetch detail.
2. **Monkey-patch import order in tests:** The dsf-python monkey-patch in the daemon imports `dsf.object_model.plugins.plugin_manifest` at module level. Tests that mock `dsf.*` modules must set up mocks **before** importing the daemon. The monkey-patch is wrapped in `try/except ImportError: pass` for this reason.
3. **File I/O on printer:** The daemon resolves virtual paths at startup (`cmd.resolve_path("0:/sys")` → `"/opt/dsf/sd/sys"`). ConfigManager stores this mapping and uses filesystem I/O. If `resolve_path()` fails, the default mapping (`DEFAULT_RESOLVED_DIRS`) is used.
4. **Directory mapping trailing slashes:** DSF Directories values lack trailing slashes (`"0:/sys"`). The daemon adds them (`"0:/sys/"`). The reference repo folder name is extracted after the `:/` separator.
5. **Side-by-side diff rendering:** `sideBySideLines(hunk)` pairs consecutive `-`/`+` lines into left/right columns. Context lines appear on both sides. Unbalanced removes/adds leave empty cells (`null` value, `diff-empty` CSS class).
6. **Plugin upgrade wipes PLUGIN_DIR:** DSF deletes the entire `/opt/dsf/plugins/MeltingplotConfig/` directory tree during plugin upgrade (confirmed empirically — the backup folder and `.git` are destroyed). All persistent data (settings, reference repo, backups) must live in `DATA_DIR` (`/opt/dsf/sd/MeltingplotConfig/`), not `PLUGIN_DIR`. The daemon migrates from the legacy location on first startup if the old data hasn't been wiped yet.
7. **`plugin.data` reset on upgrade:** DSF removes the old Plugin entry from the object model and creates a new one from the new `plugin.json`. All runtime values written via `SetPluginData` are lost. The daemon must restore state from `settings.json` on every startup, not assume `plugin.data` persists across upgrades.

### Verifying upstream APIs

The dsf-python, DuetWebControl, and DuetSoftwareFramework libraries are **not installed locally** — they run on the printer's SBC or are used only at build time. When writing code that interacts with these libraries:

1. **Do not guess API patterns.** Clone the upstream repo to `/tmp/` and read the actual source:
   ```bash
   git clone --branch v3.6-dev --depth 1 https://github.com/Duet3D/dsf-python.git /tmp/dsf-python
   ```
2. **Check the actual class definitions** before using any property or method. Key locations in dsf-python:
   - `src/dsf/object_model/object_model.py` — `ObjectModel` class (top-level: `.boards`, `.plugins`, `.state`, etc.)
   - `src/dsf/object_model/boards/boards.py` — `Board` class (`.firmware_version`, `.name`, `.short_name`, etc.)
   - `src/dsf/object_model/plugins/plugin_manifest.py` — `PluginManifest` (`.data`, `.id`, `.version`, etc.)
   - `src/dsf/object_model/plugins/plugins.py` — `Plugin` extends `PluginManifest` (`.pid`, `.dsf_files`, etc.)
   - `src/dsf/object_model/model_dictionary.py` — `ModelDictionary(dict)` (used for `.plugins`, `.globals`)
   - `src/dsf/object_model/directories/directories.py` — `Directories` (typed ModelObject with `.filaments`, `.firmware`, `.g_codes`, `.macros`, `.menu`, `.system`, `.web`)
   - `src/dsf/connections/base_command_connection.py` — `BaseCommandConnection` (available methods: `add_http_endpoint`, `resolve_path`, `set_plugin_data`, `perform_command`, `get_object_model`, etc. — **no** `get_file`/`put_file`)
3. **Common pitfall:** dsf-python converts JSON camelCase to Python snake_case automatically (e.g., `firmwareVersion` → `firmware_version`). The JSON wire format and the Python API use different naming conventions.
4. **For DWC frontend APIs**, check the DuetWebControl source for store structure, plugin registration API, and component patterns:
   ```bash
   git clone --branch v3.6-dev --depth 1 https://github.com/Duet3D/DuetWebControl.git /tmp/DuetWebControl
   ```
5. **Upstream testing status (as of 2026-02):**
   - **DuetWebControl:** Zero test infrastructure. No CI test pipeline. Only admin workflows (CLA, issue bots).
   - **DuetSoftwareFramework:** NUnit unit tests for code parsing, model deserialization, IPC subscription. No plugin lifecycle or HTTP integration tests.
   - **dsf-python:** pytest with mock Unix socket servers using `threading.Thread` + `threading.Event` for synchronization. Tests validate protocol messages (JSON over sockets). Has JSON test fixtures for object model.
   - **Conclusion:** No upstream E2E tests exist for the plugin ↔ DSF ↔ DWC interaction. Our project must implement its own.
