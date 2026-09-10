# CLAUDE.md

## Project Overview

**dwc-meltingplot-config** is a combined DWC + DSF plugin for Meltingplot 3D printers. It syncs reference configurations from a git repository, diffs them against the printer's current config, and lets users apply updates (all at once, per file, or per hunk). All config changes are backed up in a local git repo.

## Repository Structure

```
dwc-meltingplot-config/
├── plugin.json                        # DWC+DSF plugin manifest (shared by both packages)
├── src/
│   ├── core/                          # Shared, framework-neutral logic (Vue 2.7 AND Vue 3)
│   │   ├── host.js                    #   Host seam + pluginEntry/pluginDataValue/readPluginData
│   │   ├── api.js                     #   API_BASE, apiGet/apiPost/apiBlob, error + download helpers
│   │   ├── diff.js                    #   Hunk parsing, side-by-side rows, selection, normalizers
│   │   ├── status.js                  #   Sync-status chip map
│   │   ├── backend.js                 #   SBC backend state + auto-recovery (takes a Host)
│   │   ├── useConfigPage.js           #   Main page state and actions
│   │   ├── useConfigDiff.js           #   Diff selection + expand-on-demand detail fetch
│   │   └── useBackupHistory.js        #   Backup list, file tree, content/diff viewer
│   ├── ui36/                          # DWC 3.6 UI — Vue 2.7 + Vuetify 2.7
│   │   ├── index.js                   #   Entry — registerRoute from '@/routes', backend recovery
│   │   ├── host.js                    #   Vuex adapter
│   │   ├── MeltingplotConfig.vue      #   Main page: Status/Changes/History/Settings tabs
│   │   └── components/{ConfigStatus,ConfigDiff,BackupHistory}.vue
│   ├── ui37/                          # DWC 3.7 UI — Vue 3.5 + Vuetify 4
│   │   ├── index.ts                   #   Entry — registerRoute from '@/plugins', unregister on unload
│   │   ├── host.ts                    #   Pinia adapter
│   │   ├── MeltingplotConfig.vue      #   Main page (<script setup lang="ts">)
│   │   └── components/{ConfigStatus,ConfigDiff,BackupHistory}.vue
│   ├── routes.js / store.js           # Jest-only stubs for DWC's @/routes and @/store
│   └── __mocks__/                     # Jest manual mocks
├── dsf/                               # SBC backend (Python 3) — identical in both packages
│   ├── meltingplot-config-daemon.py   # Main daemon — DSF connection, HTTP endpoint dispatch
│   ├── config_manager.py              # Core logic: sync, diff, apply (full/file/hunks), backup
│   └── git_utils.py                   # Git CLI wrapper (clone, fetch, checkout, backup repo)
├── scripts/
│   ├── stage.js                       # node scripts/stage.js 36|37 [outDir] — the tree a builder gets
│   ├── build.js                       # node scripts/build.js 36|37 — stage + build-plugin-pkg + rename
│   ├── build-zip.js                   # Structure-only ZIP for the plugin-structure tests
│   ├── ci-local.sh                    # Run the CI pipeline locally
│   └── version.js                     # Version computation from git tags
├── .gitignore
├── CLAUDE.md                          # This file
├── PLAN.md                            # Detailed architecture and implementation plan
├── docs/PLAN-dwc37-dual-build.md      # Plan: build one DWC 3.6 and one DWC 3.7 package from this repo
└── README.md                          # User-facing build and install docs
```

**There is deliberately no `src/index.*` in the repository.** Both DWC builders always
compile `<plugin-dir>/src/index.*` and cannot be pointed at a subdirectory, so the
generation is chosen by staging: `scripts/stage.js` writes the one-line entry point into
the staged tree. Never hand the raw repository to a DWC builder.

## Language & Ecosystem

This repository builds **two packages from one source tree**: a DWC 3.6 one and a DWC 3.7
one. They are different framework stacks, so a package built for one does not load on the
other.

| | DWC 3.6 (`v3.6-dev`, 3.6.3) | DWC 3.7 (`v3.7-dev`, 3.7.0-rc.1) |
|---|---|---|
| Framework | Vue **2.7** | Vue **3.5** |
| UI kit | Vuetify **2.7** | Vuetify **4** |
| State | Vuex 3 — `@/store`, `store.state.machine.model` | Pinia — `useMachineStore()` from `@/stores/machine` |
| Route registration | `registerRoute` from `@/routes` | `registerRoute` / `unregisterRoute` from `@/plugins` |
| Build | `scripts/build-plugin-pkg.js` → vue-cli/webpack, ZIP in `DuetWebControl/dist/` | `scripts/build-plugin-pkg.js` → Vite lib/IIFE + **vue-tsc type check**, ZIP next to the plugin dir |
| Node | 18 | 22+ (Vite 8 / TypeScript 6) |
| `plugin.data` | plain object (Vuex keeps a JSON clone) | `Map<string, any>` (`@duet3d/objectmodel`) |
| Plugin unload | none | `dwcPluginUnloaded` event, `unregisterRoute()` |
| Plugin load | webpack chunk named after the id | reads **`dwcFiles`** from the manifest; empty list = "SBC-only plugin", UI never loads |

- **Shared core:** `src/core/` — Composition API only, imported from `vue` and therefore
  valid under both Vue 2.7 and Vue 3.5. It must not import anything DWC-specific; DWC is
  reached exclusively through the **Host** seam (`model()`, `startSbcPlugin(id)`).
  - **Source (3.6):** [`v3.6-dev`](https://github.com/Duet3D/DuetWebControl/tree/v3.6-dev)
  - **Source (3.7):** [`v3.7-dev`](https://github.com/Duet3D/DuetWebControl/tree/v3.7-dev)
- **Backend:** Python 3 (runs as DSF SBC plugin process), one tree for both packages
  - **Source:** `v3.6-dev` branch of [Duet3D/DuetSoftwareFramework](https://github.com/Duet3D/DuetSoftwareFramework/tree/v3.6-dev)
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

## Known dsf-python Bugs & Runtime Workarounds

These bugs exist in dsf-python and are worked around in our daemon at startup. **Do not
remove these workarounds** — they are required for correct operation on real hardware.

All of them were re-checked against **dsf-python v3.7-dev (3.7.0-beta.1)**: every module
path, the `PluginManifest` constructor and the `Board` / `NetworkInterface` property
objects still exist there, so each patch still applies. What changed is how much of each
one is still doing work — noted per bug below.

Each patch is applied through `_apply_dsf_workaround(name, patch)`, which swallows
`ImportError` (the library is absent in tests) and reports anything else on stderr instead
of raising. A workaround that no longer fits a future library must degrade, not take the
daemon down at import time.

**3.7 changed how the ObjectModel declares properties**: hand-written `@property` setters
became `model_prop(...)` descriptors built at class-definition time. That matters for two
of the patches — a descriptor captures its enum when the class is defined, so replacing
the module-level enum afterwards no longer reaches it. Both patches therefore do two
things: replace the enum (what fixes 3.6) *and* replace the setter (what fixes 3.7).

### 1. PluginManifest._data deserialization bug

**Bug:** `PluginManifest.__init__` initialises `_data` as a plain `dict {}`. The `_update_from_json()` method only handles `ModelObject`, `ModelCollection`, `ModelDictionary`, and `list` — it silently **skips** plain `dict` properties. This means `get_object_model().plugins[id].data` is always `{}`.

**Workaround:** `_patch_plugin_manifest_data()` wraps `PluginManifest.__init__` and
replaces `_data` with `ModelDictionary(False)`. This makes `_update_from_json` populate
`plugin.data` correctly.

**On 3.7:** fixed upstream — `data = model_prop('data', ModelDictionary, ModelDictionary(False))`,
where `_data` is that descriptor's storage. Assigning a fresh empty `ModelDictionary` there
is exactly what the descriptor's own default does, so the patch is redundant but harmless.

### 2. No `get_file()` / `put_file()` methods on CommandConnection

**Bug:** `dsf.connections.CommandConnection` has **no** `get_file()` or `put_file()` methods, despite what documentation might suggest. Calling them raises `AttributeError`.

**Workaround:** At daemon startup, use `cmd.resolve_path("0:/sys")` to convert virtual printer paths (e.g., `"0:/sys"`) to real filesystem paths (e.g., `"/opt/dsf/sd/sys"`). Then use standard Python `open()` for all file I/O. The `ConfigManager` stores a `resolved_dirs` mapping for this purpose.

### 3. DSF Directories object — typed ModelObject, not a dict

**Finding:** `model.directories` is a typed `Directories` ModelObject with named snake_case properties (`filaments`, `firmware`, `g_codes`, `macros`, `menu`, `system`, `web`). Values are strings like `"0:/sys"` (no trailing slash). This is **not a dict** — use `getattr()` for attribute access.

**Our implementation:** `build_directory_map(model)` in the daemon reads these attributes and builds a `ref_folder → printer_path` mapping (e.g., `{"sys/": "0:/sys/"}`). This mapping is passed to `ConfigManager` to convert between reference repo paths and printer paths.

### 4. `resolve_path()` returns a Response object, not a string

**Bug:** `BaseCommandConnection.resolve_path()` returns the raw `Response` object from `perform_command()`. Unlike other methods (e.g., `remove_http_endpoint`, `set_network_protocol`) which unwrap with `res.result`, `resolve_path` does not. Calling `.endswith()` on the Response fails with `AttributeError`.

**Workaround:** Extract the actual path via `getattr(response, "result", response)` after calling `cmd.resolve_path()`. The daemon does this in the path-resolution loop at startup.

### 5. BoardState enum missing `timedOut` value

**Bug:** `BoardState(str, Enum)` in `dsf.object_model.boards.boards` only defines `unknown`, `flashing`, `flashFailed`, `resetting`, `running`. DSF may report additional states (e.g. `timedOut` when an expansion board doesn't respond). The `Board.state` property setter calls `BoardState(value)` which raises `ValueError` for unrecognised values. This crashes `get_object_model()` entirely — the daemon loses firmware version detection and directory mappings.

**Workaround (two-part), in `_patch_board_state()`:**
1. **Enum replacement:** Replace `BoardState` in `dsf.object_model.boards.boards` with a
   new enum that includes all original members plus `timedOut`. This is what fixes 3.6,
   whose setter reads the module-level name.
2. **Setter safety net:** Replace `Board.state`'s setter with one that uses the new enum
   and catches `ValueError`/`KeyError`, falling back to `BoardState.unknown`. This is what
   fixes 3.7, whose descriptor ignores the enum swap.

A wrong *type* (a number rather than a string) still raises `TypeError` on purpose: DSF
sends JSON, so that would mean the library changed how it calls the setter, which is worth
surfacing rather than papering over.

**On 3.7:** `timedOut` is **still missing** upstream, so this patch is load-bearing on both
generations.

### 6. NetworkInterfaceType enum missing `ethernet` value

**Bug:** `NetworkInterfaceType(str, Enum)` in `dsf.object_model.network.network_interface_type` only defines `lan` and `wifi`. DSF 3.6.3-rc.1 reports `ethernet` for wired interfaces. The `NetworkInterface.type` setter calls `NetworkInterfaceType(value)` which raises `ValueError` for unrecognised values, crashing `get_object_model()` entirely.

**Workaround (two-part), in `_patch_network_interface_type()`:** the same shape as the
`BoardState` patch — replace the enum in both `network_interface_type` and
`network_interface` with one carrying `lan`, `wifi`, `ethernet` and an `unknown` fallback,
and replace `NetworkInterface.type`'s setter.

**On 3.7:** `ethernet` was added upstream — but `lan` was **removed**, so the same class of
crash simply moved to the other value. The replacement enum carries both, which covers
either library.

### 7. DSF 3.7 API compatibility (checked, no change needed)

`resolve_path`, `add_http_endpoint` and `set_plugin_data` keep their signatures in
dsf-python 3.7. `resolve_path` still returns the raw `Response` rather than unwrapping it,
so workaround 4 is still required. `set_plugin_data`'s `value` widened from `str` to
`object`, which is compatible.

**Not yet verified:** `get_object_model()` against a real DSF 3.7 SBC. That remains the
release gate for the 3.7 package — the analysis above is source-level only.

## Development Setup

### Building the frontend

One DuetWebControl checkout per generation, each with `npm install` done:

```bash
git clone -b v3.6-dev https://github.com/Duet3D/DuetWebControl.git dwc36 && (cd dwc36 && npm install)
git clone -b v3.7-dev https://github.com/Duet3D/DuetWebControl.git dwc37 && (cd dwc37 && npm install)

DWC36_DIR=$PWD/dwc36 node scripts/build.js 36   # dist/MeltingplotConfig-<version>-dwc36.zip
DWC37_DIR=$PWD/dwc37 node scripts/build.js 37   # dist/MeltingplotConfig-<version>-dwc37.zip
```

`scripts/build.js` stages the tree (see below), runs DWC's **`build-plugin-pkg`** — not
`build-plugin` — and renames the ZIP with the `-dwc36` / `-dwc37` suffix. Only the `-pkg`
script fills in `dwcFiles`, and DWC 3.7 takes its resource list from there: with an empty
`dwcFiles` it registers the plugin as SBC-only and never loads the page.

The 3.6 toolchain runs on Node 18; the 3.7 one needs **Node 22+**. `scripts/ci-local.sh
build37` falls back to a `node:22` container when the host Node is older.

### Staging

`scripts/stage.js 36|37 [outDir]` copies `src/core/`, one `src/ui<gen>/`, `dsf/` and
`plugin.json` into a tree and writes the generated `src/index.js` / `index.ts` entry
point. Rules that matter:

- The Jest-only stubs (`src/routes.js`, `src/store.js`, `src/__mocks__/`) are **excluded** —
  DWC provides the real `@/routes` and `@/store`, and a staged copy would shadow them.
- The other generation's `ui*/` is excluded — it would not even compile.
- **No `package.json` is staged.** DWC 3.7's builder runs `npm install` inside the plugin
  directory when one lists dependencies it cannot resolve, and ours pins Vue 2 / Vuetify 2
  / Jest for the test suite.
- `__pycache__` and `*.pyc` are skipped: DWC 3.7 lists every file under `dsf/` in
  `dsfFiles`, so stray byte-code would be shipped and installed on the SBC.

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
- **Shared core (in `tests/frontend/core/`):** the framework-neutral logic, tested
  directly rather than through a component
  - `host.test.js` — the Host seam, `plugin.data` as a Map (3.7) and an object (3.6)
  - `api.test.js` — fetch wrappers, error extraction, query and download helpers
  - `diff.test.js` — hunk parsing, side-by-side rows, selection predicates, apply payload
  - `status.test.js` — sync-status chip mapping
  - `backend.test.js` — backend recovery, plus the DWC 3.6 Vuex adapter end to end
  - `useBackupHistory.test.js` — file tree building, backup normalisation
- **DWC 3.6 components (in `tests/frontend/`):**
  - `ConfigStatus.test.js` — Props rendering, status mapping, button state, events
  - `ConfigDiff.test.js` — File filtering, hunk selection/deselection, emit payloads, side-by-side diff logic
  - `ConfigDiffSelection.test.js` — Partial-apply selection state: file/hunk checkboxes, `Apply All` ↔ `Partially Apply`, emitted payload
  - `BackupHistory.test.js` — Empty/loading states, backup display, expand/collapse, fetch mocking
  - `MeltingplotConfig.test.js` — Main page state, API calls, confirm/notify flows
- **Integration tests (in `tests/frontend/integration/`):**
  - `full-mount.test.js` — Full component tree with real Vuetify
  - `plugin-registration.test.js` — DWC plugin registration contract
  - `plugin-structure.test.js` — Plugin ZIP structure, **both generations**: staged contents,
    entry point, manifest, and that neither package carries the other's UI
  - `user-flows.test.js` — End-to-end user flows with mock backend
  - `api-contract.test.js` — Validates daemon API response shapes match frontend component expectations

### DWC 3.7 UI (Vitest)

Two Vue majors cannot share one `node_modules`, so the 3.7 tests live in their own npm
package at `tests/ui37/`.

- **Framework:** Vitest 2 + @vue/test-utils 2 + happy-dom, with real Vuetify 4
- **Install & run:** `npm --prefix tests/ui37 ci && npm --prefix tests/ui37 test`
  (or `npm run test:ui37`; needs **Node 22+**, or `scripts/ci-local.sh ui37` which falls
  back to a container)
- **What it covers:**
  - `specs/*.spec.js` — the four DWC 3.7 components mounted with real Vuetify, plus the
    entry point's route registration, backend recovery and `dwcPluginUnloaded` handling
  - **the whole of `tests/frontend/core/`, a second time** — the shared logic run under
    Vue 3's reactivity, which is what proves it really is generation-neutral
- **Mocks:** `mocks/plugins.js`, `mocks/machineStore.js`, `mocks/events.js` stand in for
  DWC's `@/plugins`, `@/stores/machine` and `@/utils/events`. The machine-store mock keeps
  `plugin.data` in a **Map**, as DWC 3.7 does — the difference `pluginDataValue()` absorbs.

Three things in `vitest.config.mjs` are load-bearing; changing them breaks the run in ways
whose error messages do not point at the cause:

1. `resolve.alias` maps `vue` and `vuetify` to **this** package's copies. Vite resolves
   bare imports from the project root, where they are Vue 2 / Vuetify 2, so without the
   aliases components render nothing.
2. Those aliases are **anchored regexes**, not plain strings. A string alias also rewrites
   subpaths, turning `vuetify/components` into a bare directory path that no longer
   resolves through the package's exports map — hence the separate subpath entries.
3. `server.fs.allow` names the repository root. The config lives in `tests/ui37/` but the
   specs import from `src/` and `tests/frontend/`; without it every import fails with
   "Does the file exist?" for a file that plainly does.

On top of that, `vue-tsc` type-checks the 3.7 templates during the build leg, which is what
catches a Vuetify 4 prop that silently changed meaning.

**Props are not deep-reactive in either generation's test setup**, so a spec that mutates
an entry after mounting must hold the list in `reactive()` — that is what the parent's ref
does in the real app.

## Linting & Formatting

- **Run:** `npm run lint`
- **Config:** `.eslintrc.js`, with one override per source area:

| Files | Rules |
|---|---|
| `src/core/**` | `eslint:recommended` — framework-neutral, no Vue rules |
| `src/ui36/**` | `plugin:vue/recommended` (Vue 2) |
| `src/ui37/**` | `plugin:vue/vue3-recommended` with `@typescript-eslint/parser` |

## Building

Both packages are built through `scripts/build.js` (see **Development Setup**), which
stages the tree and hands it to the respective DWC checkout's `build-plugin-pkg`.

For structure validation without a DWC checkout, `scripts/build-zip.js [36|37]` packages
the staged sources into a ZIP. That is what the `plugin-structure` tests exercise.

## CI/CD

GitHub Actions workflow at `.github/workflows/ci.yml`:

1. **Python Tests** — `pytest` on Python 3.10, 3.11, 3.12
2. **Frontend Lint & Tests** — `npm run lint` + unit, core and integration tests on Node 18
3. **DWC 3.7 UI Tests** — Vitest in `tests/ui37/` on Node 22
4. **Build** — a two-leg matrix:

| `gen` | DWC ref | Node | Artifact |
|---|---|---|---|
| `36` | `v3.6-dev` | 18 | `MeltingplotConfig-plugin-dwc36` |
| `37` | `v3.7-dev` | 22 | `MeltingplotConfig-plugin-dwc37` |

Each leg verifies the packaged manifest: the right `dwcVersion`, a populated `dwcFiles`
and the daemon in `dsfFiles`. The 3.7 leg additionally runs `vue-tsc` (inside
`build-plugin-pkg`) against the templates.

**Artifacts carry the package's contents, never the package file.** GitHub wraps an
artifact in an archive of its own, so uploading `dist/*.zip` hands the downloader a ZIP
inside a ZIP, which DWC rejects. Unpacking first makes that wrapper the installable
package; the unpack step asserts `plugin.json` ends up at the root. `release.yml` is the
exception — its `release-asset-dwc*` artifacts are plumbing that carries the package file
to the publish step, which attaches it to the Release. Those are named and retained (1 day)
to make clear they are not the download.

**Triggers:** push to `main`/`master`, pull requests to `main`/`master`, manual
`workflow_dispatch` with per-generation DWC ref overrides.

`.github/workflows/release.yml` runs the same two legs on a push to `release`, resolving
the newest stable tag **of each series** (`v3.6.*` / `v3.7.*`) and attaching both ZIPs to
one GitHub Release. Resolving the highest tag overall would compile the Vue 2.7 sources
with 3.7's toolchain the day Duet3D tags `v3.7.0`.

## Key Architecture Decisions

| Decision | Choice |
|----------|--------|
| Target DWC versions | **3.6 and 3.7** — two packages from one source tree |
| Code sharing | All logic in `src/core/` (Composition API, framework-neutral); `src/ui36/` and `src/ui37/` are template-only |
| DWC coupling | A two-method **Host** seam (`model()`, `startSbcPlugin(id)`), implemented per generation |
| Entry point | Generated by `scripts/stage.js` — the repository has no `src/index.*` |
| Packaging | `build-plugin-pkg` for both legs; assets suffixed `-dwc36` / `-dwc37` |
| Reference config source | Git repo — one repo per printer model |
| Firmware versioning | One branch per firmware version |
| Backend runtime | Python SBC daemon via DSF (venv with `sbcPythonDependencies`) |
| Persistent data location | `/opt/dsf/sd/MeltingplotConfig/` — survives plugin upgrades (DSF wipes `PLUGIN_DIR`) |
| Backup strategy | Worktree-based git repo — tracks sys/, macros/, filaments/ in-place |
| Partial apply | File- and hunk-level deselection — *Apply All* becomes *Partially Apply* and skips what the user unchecked (`POST /applySelection`) |
| Protected files | Overrides (`config-override.g`, `temps.g`, `machine-override`, `global-override.g`) are never overwritten **once they exist on the printer**; a missing one is seeded from the reference (`ConfigManager._is_overwrite_protected`) |

## HTTP API

All endpoints are under `/machine/MeltingplotConfig/`. Each endpoint is registered separately with DSF via `add_http_endpoint()` and handled by an async callback. Dynamic parameters use query strings (DSF does exact path matching, no path parameters).

- `GET /status` — sync status, firmware version, active branch
- `POST /sync` — fetch + checkout reference repo
- `GET /diff` — full diff (all files); with `?file=<path>` returns single file diff with indexed hunks
- `GET /reference` — list files in reference repo
- `GET /branches` — list available branches
- `POST /apply` — apply all changes (with backup); with `?file=<path>` applies single file
- `POST /applyHunks?file=<path>` — apply selected hunks (body: `{"hunks": [0, 2, 5]}`)
- `POST /applySelection` — apply a mixed selection across files in one pass, under a single
  backup pair (body: `{"files": ["sys/homeall.g", {"file": "sys/config.g", "hunks": [0, 2]}]}`).
  A bare path (or an entry without `hunks`) applies the whole file; an entry with `hunks`
  applies only those hunk indices. Files the user excluded are simply absent from the payload.
  Response: `{"applied": [...], "partial": {path: {"applied": [...], "failed": [...]}},
  "skipped": [...], "errors": {path: reason}}` — `partial`, `skipped` and `errors` are omitted
  when empty.
- `GET /backups` — backup history
- `GET /backup?hash=<hash>` — backup file list
- `GET /backupDownload?hash=<hash>` — download backup as ZIP
- `POST /restore?hash=<hash>` — restore from backup
- `POST /settings` — update plugin settings

## Git Workflow

- **Default remote branch:** `main`
- **Commit messages:** Use clear, descriptive messages summarizing the change

### Always use the PR track

**Never commit or push directly to `main`.** Every change — however small — takes
the same three steps:

1. **Branch** — create a feature branch off the latest `main`
2. **PR** — push the branch and open a pull request against `main`
3. **Merge** — merge that pull request

This applies **even when asked to "merge it into main"**. Such a request means
"land this change on `main`", not "push straight to `main`" — deliver it by
opening a PR and merging the PR. A local `git merge` into `main` followed by
`git push origin main` is never the right way, not even for a clean
fast-forward, a docs-only edit, or a one-line fix. If a change has already been
pushed to a branch, that branch still needs a PR before it reaches `main`.

Why: CI runs on the PR before the change lands, the PR is the review record, and
`main`'s history stays consistent — every commit on `main` arrives through a
merged PR.

Let CI finish on the PR before merging. If the merge is blocked (branch
protection, a required review, a failing check), say so and leave the PR open —
never fall back to pushing to `main`.

### Releases always travel main -> release -> tag

Releases use the same PR track, in three steps, in this order:

1. **PR into `main`** — the change (including the `plugin.json` version bump)
   lands on `main` through a pull request, exactly as above
2. **PR from `main` into `release`** — open a pull request with base `release`
   and head `main`, and merge it. Never push to `release` directly and never
   cherry-pick onto it; `release` only ever receives commits that are already
   on `main`
3. **Tag on a `release` commit** — the `vX.Y.Z` tag must point at a commit on
   the `release` branch, never at a `main`-only commit

Step 3 is automated: `.github/workflows/release.yml` runs on every push to
`release`, reads the version from `plugin.json`, and creates the matching
`vX.Y.Z` tag and GitHub Release itself. So there is no tag to push by hand —
merging the `main` -> `release` PR is what cuts the release. It refuses to run
twice for the same version, so the version bump in `plugin.json` must be part
of what travels through step 1.

Never release from `main`, a feature branch, or a local build.

## Conventions for AI Assistants

- **Logic goes in `src/core/`, never in a template.** If a change would have to be made
  twice — once for Vuetify 2 and once for Vuetify 4 — it belongs in a composable. The
  `ui36`/`ui37` SFCs hold props and a `setup()` that returns a composable, nothing else.
- **`src/core/` may not import anything DWC-specific.** No `@/routes`, no `@/store`, no
  `@/plugins`, no Vuex or Pinia. It reaches DWC only through the Host it is handed.
- **Never index `plugin.data` directly.** It is a plain object on DWC 3.6 and a `Map` on
  DWC 3.7, so `data.referenceRepoUrl` works on one and silently returns `undefined` on the
  other. `pluginDataValue()` in `core/host.js` is the only place allowed to touch it;
  `readPluginData()` is what everything else uses.
- **Vue 2.7 cannot observe properties added after an object became reactive.** Every field
  a file or backup entry will ever carry is set by `normalizeFile` / `normalizeHunk` /
  `normalizeBackup` at creation. Never add one later, and never reintroduce `$set` — the
  symptom on 3.6 is a UI that quietly stops updating after an action that works on 3.7.
- Frontend (3.6): Vue 2.7 + Vuetify 2.7 conventions. Options API in the SFC shell,
  Composition API in the composables.
- Frontend (3.7): Vue 3.5 + Vuetify 4, `<script setup lang="ts">`. TypeScript on purpose —
  `vue-tsc` is what catches a Vuetify prop that changed meaning between the two versions
  (`dense` → `density`, `text` → `variant`, `left` → `start`, …).
- Frontend test mocks: `createStore(pluginData)` builds a namespaced `machine` module with
  a `model` child, mirroring DWC's real store, and wraps the data as
  `{ MeltingplotConfig: { data: pluginData } }` to match the real Plugin object.
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

1. **Summary hunks vs detail hunks:** `diff_all()` returns summary hunks `{index, header}` only. `diff_file()` returns full hunks with `{index, header, lines, summary}`. Frontend guard logic must check for `hunk.lines` (not just `hunk` truthiness) to decide whether to fetch detail. `hasHunkDetail(file)` in `core/diff.js` encodes this check — a file whose panel was never expanded has no per-hunk `selected` flags, so it always applies as a whole file.
2. **Monkey-patch import order in tests:** The dsf-python monkey-patch in the daemon imports `dsf.object_model.plugins.plugin_manifest` at module level. Tests that mock `dsf.*` modules must set up mocks **before** importing the daemon. The monkey-patch is wrapped in `try/except ImportError: pass` for this reason.
3. **File I/O on printer:** The daemon resolves virtual paths at startup (`cmd.resolve_path("0:/sys")` → `"/opt/dsf/sd/sys"`). ConfigManager stores this mapping and uses filesystem I/O. If `resolve_path()` fails, the default mapping (`DEFAULT_RESOLVED_DIRS`) is used.
4. **Directory mapping trailing slashes:** DSF Directories values lack trailing slashes (`"0:/sys"`). The daemon adds them (`"0:/sys/"`). The reference repo folder name is extracted after the `:/` separator.
5. **Side-by-side diff rendering:** `sideBySideLines(hunk)` pairs consecutive `-`/`+` lines into left/right columns. Context lines appear on both sides. Unbalanced removes/adds leave empty cells (`null` value, `diff-empty` CSS class).
6. **Plugin uninstall wipes PLUGIN_DIR:** DSF deletes the entire `/opt/dsf/plugins/MeltingplotConfig/` directory on full uninstall. During upgrade, DSF only removes tracked plugin files (from `DsfFiles`/`DwcFiles`/`SdFiles`) but extra runtime-created files survive. Regardless, all persistent data (settings, reference repo, backups) must live in `DATA_DIR` (`/opt/dsf/sd/MeltingplotConfig/`), not the plugin directory.
7. **Plugin upgrades do not restart the SBC backend** — see below.

### Plugin upgrade leaves the backend stopped

Upgrading the plugin puts it into DWC's **"partially started"** state: the DWC
resources are loaded, but the Python daemon is dead and every
`/machine/MeltingplotConfig/*` endpoint returns 404. This is upstream behaviour,
not a bug in our plugin:

1. `InstallPlugin` (DCS) detects an existing plugin and first runs
   `UninstallPlugin { ForUpgrade = true }`, which issues `StopPlugin` and rewrites
   `plugins.json` **without** our plugin — so it also no longer auto-starts on boot.
2. `InstallPlugin` then re-registers the plugin in the object model with `Pid = -1`
   and never starts it.
3. DWC only issues `StartPlugin` when `installPlugin` is called with `start: true`,
   which `UploadBtn.vue` sets only for `UploadType.start` ("Upload & Start"). The
   "Install Plugin" button on *Settings → Plugins* uses `UploadType.plugin`, so
   `start` is `false`.
4. `Plugins.vue#getPluginStatus` then reports `partiallyStarted`, because
   `(plugin.pid >= 0) != enabledPlugins.includes(id)`.

**Our workaround** lives in `src/core/backend.js` and is shared by both generations:

- `isBackendRunning(model)` (in `core/host.js`) reads `plugin.pid` from `model.plugins`
  (`-1` = stopped, `0` = shutting down, `> 0` = running; `null` when not yet known).
- `ensureBackendRunning(host)` is called from `src/ui36/index.js` and `src/ui37/index.ts`
  when DWC loads our resources. It polls the object model until the PID is known and calls
  `host.startSbcPlugin()` if the backend is stopped — `machine/startSbcPlugin` on Vuex,
  `useMachineStore().startSbcPlugin` on Pinia. DSF's `StartPlugin` defaults to
  `SaveState = true`, so this also restores the boot auto-start entry.
- Both `MeltingplotConfig.vue` pages show a warning banner with a manual **Start Backend**
  button whenever `backendRunning === false`, as a visible fallback.

`@/store` (like `@/routes`) is provided by DWC at build time; `src/store.js` is an
inert Jest-only stub and is excluded from the plugin ZIP.

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
4. **For DWC frontend APIs**, check the DuetWebControl source for store structure, plugin registration API, and component patterns — **the generation matters**, the two differ everywhere:
   ```bash
   git clone --branch v3.6-dev --depth 1 https://github.com/Duet3D/DuetWebControl.git /tmp/dwc36
   git clone --branch v3.7-dev --depth 1 https://github.com/Duet3D/DuetWebControl.git /tmp/dwc37
   ```
   Key locations in the 3.7 tree:
   - `src/plugins/index.ts` — `registerRoute` / `unregisterRoute`, the `window.DWC` surface
   - `src/stores/machine.ts` — `useMachineStore()`, `.model`, `.startSbcPlugin(id)`
   - `src/utils/events.ts` — the event map, including `dwcPluginUnloaded`
   - `scripts/build-plugin.js` — the externals map, the Vite config and `typeCheckPlugin()`;
     the type check includes only `**/*.ts`, `**/*.tsx` and `**/*.vue`, so pure-JavaScript
     plugin code is not checked
   - `scripts/build-plugin-pkg.js` — how `dwcFiles` / `dsfFiles` get populated
5. **Upstream testing status (as of 2026-02):**
   - **DuetWebControl:** Zero test infrastructure. No CI test pipeline. Only admin workflows (CLA, issue bots).
   - **DuetSoftwareFramework:** NUnit unit tests for code parsing, model deserialization, IPC subscription. No plugin lifecycle or HTTP integration tests.
   - **dsf-python:** pytest with mock Unix socket servers using `threading.Thread` + `threading.Event` for synchronization. Tests validate protocol messages (JSON over sockets). Has JSON test fixtures for object model.
   - **Conclusion:** No upstream E2E tests exist for the plugin ↔ DSF ↔ DWC interaction. Our project must implement its own.
