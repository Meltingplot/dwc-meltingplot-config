# Meltingplot Config

A DWC + DSF plugin that keeps Meltingplot 3D printer configurations up to date.

## What It Does

- **Syncs** reference configurations from a git repository (one repo per printer model, one branch per firmware version)
- **Diffs** the reference against the printer's current config, showing changes at the hunk level
- **Applies** updates — all at once, per file, or by selecting individual change blocks
- **Partially applies** — deselect any file or hunk you want to keep and *Apply All* becomes
  *Partially Apply*, updating everything else in a single pass
- **Backs up** every config change in a local git repository with full history and restore

## Requirements

- Duet SBC (Raspberry Pi) running **DSF 3.6** or **3.7**
- Duet Web Control (DWC) **3.6** or **3.7**
- Git installed on the SBC
- Python **3.10+** (on the SBC)

## Which package do I install?

Every release ships **two ZIPs of the same plugin version**. DWC 3.6 and DWC 3.7 are
different framework stacks (Vue 2.7 + Vuetify 2.7 vs. Vue 3.5 + Vuetify 4), so a
package built for one does not load on the other:

| Asset | Install on | Requires |
|---|---|---|
| `MeltingplotConfig-<version>-dwc36.zip` | DuetWebControl **3.6** | DSF **3.6** |
| `MeltingplotConfig-<version>-dwc37.zip` | DuetWebControl **3.7** | DSF **3.7** |

Each package is rejected by the other generation at install time, so picking the wrong
file gives an error rather than a broken install. The Python backend is identical in
both.

## Building

The DWC frontend is built by DWC's own build system — one build per generation, from the
same source tree. The DSF backend is plain Python (no build step).

```bash
# One checkout per generation, each with npm install done
git clone -b v3.6-dev https://github.com/Duet3D/DuetWebControl.git dwc36 && (cd dwc36 && npm install)
git clone -b v3.7-dev https://github.com/Duet3D/DuetWebControl.git dwc37 && (cd dwc37 && npm install)

# Build either package
DWC36_DIR=$PWD/dwc36 npm run build:plugin 36   # dist/MeltingplotConfig-<version>-dwc36.zip
DWC37_DIR=$PWD/dwc37 npm run build:plugin 37   # dist/MeltingplotConfig-<version>-dwc37.zip
```

The 3.6 toolchain (vue-cli + webpack) runs on Node 18; the 3.7 one (Vite 8 + vue-tsc)
needs **Node 22+**.

`scripts/build.js` stages the tree first — see [Two packages, one source tree](#two-packages-one-source-tree).

For structure validation without a DWC checkout, a standalone script packages the staged
sources into a ZIP:

```bash
npm run build 36     # or 37
# Output: dist/MeltingplotConfig-<version>-dwc<gen>.zip
```

## Installation

1. Upload the ZIP matching your DWC generation via **DWC → Settings → Plugins → Install Plugin**
2. DSF extracts the backend files and starts the daemon
3. DWC loads the frontend
4. Navigate to **Plugins → Meltingplot Config**
5. In the **Settings** tab, configure the reference repository URL for your printer model
6. The plugin auto-detects your firmware version, selects the matching branch, and compares configs

### Updating

Installing a newer ZIP over an existing installation is an *upgrade*. DSF stops the
old backend process during the upgrade and does not start the new one, which leaves
the plugin in DWC's **"partially started"** state with all HTTP endpoints returning
404.

The plugin recovers from this on its own: after reloading DWC, it detects the stopped
backend and asks DSF to start it (which also restores the boot auto-start entry). If
that does not work — for example because DSF refused the start — open
**Plugins → Meltingplot Config**; a warning banner with a **Start Backend** button is
shown while the backend is down.

## Two packages, one source tree

DWC 3.6 and DWC 3.7 need different UI code, but everything below the templates — the API
client, the diff engine, the selection state, the backend recovery — is the same. So the
repository holds that logic **once**, in `src/core/`, and two thin template sets on top:

```
src/
  core/        framework-neutral: Composition API only, no DWC imports
  ui36/        Vue 2.7 / Vuetify 2.7 templates + the Vuex host adapter
  ui37/        Vue 3.5 / Vuetify 4 templates + the Pinia host adapter
```

The only way `core/` reaches DWC is a **Host** — two methods, `model()` and
`startSbcPlugin(id)` — implemented once per generation in `ui36/host.js` and
`ui37/host.ts`. No Vue or store types cross that boundary.

There is deliberately **no `src/index.js` in the repository**. Both DWC builders always
compile `<plugin-dir>/src/index.*` and cannot be pointed at a subdirectory, so the
generation is picked by staging: `scripts/stage.js 36|37` copies `core/`, one `ui<gen>/`,
`dsf/` and `plugin.json` into a temporary tree and writes the one-line entry point into
it. Neither generation is "the default", and the raw tree can never be handed to a DWC
builder by accident.

The staged tree carries **no `package.json`** on purpose: DWC 3.7's builder runs
`npm install` inside the plugin directory when one lists dependencies it cannot resolve,
and ours pins Vue 2 / Vuetify 2 / Jest for the test suite.

## Plugin Structure

```
dwc-meltingplot-config/
├── plugin.json                        # DWC+DSF plugin manifest (shared by both packages)
├── src/
│   ├── core/                          # Shared, framework-neutral logic
│   │   ├── host.js                    #   The Host seam + plugin.data access
│   │   ├── api.js                     #   fetch wrappers for the daemon endpoints
│   │   ├── diff.js                    #   Hunk parsing, side-by-side rendering, selection
│   │   ├── status.js                  #   Sync-status chip presentation
│   │   ├── backend.js                 #   SBC backend state and auto-recovery
│   │   ├── useConfigPage.js           #   Main page state and actions
│   │   ├── useConfigDiff.js           #   Diff viewer selection and detail loading
│   │   └── useBackupHistory.js        #   Backup list, file tree, content/diff viewer
│   ├── ui36/                          # DWC 3.6 UI — Vue 2.7 + Vuetify 2.7
│   │   ├── index.js                   #   Entry point — registers route, recovers backend
│   │   ├── host.js                    #   Vuex adapter
│   │   ├── MeltingplotConfig.vue      #   Main page: Status/Changes/History/Settings tabs
│   │   └── components/
│   │       ├── ConfigStatus.vue       #   Status dashboard (FW version, sync status, branch)
│   │       ├── ConfigDiff.vue         #   Diff viewer with hunk-level checkboxes and apply
│   │       └── BackupHistory.vue      #   Backup list with download, restore, and delete
│   ├── ui37/                          # DWC 3.7 UI — Vue 3.5 + Vuetify 4
│   │   ├── index.ts                   #   Entry point — registers and unregisters the route
│   │   ├── host.ts                    #   Pinia adapter
│   │   ├── MeltingplotConfig.vue      #   Main page: Status/Changes/History/Settings tabs
│   │   └── components/
│   │       ├── ConfigStatus.vue       #   Status dashboard
│   │       ├── ConfigDiff.vue         #   Diff viewer with hunk-level checkboxes and apply
│   │       └── BackupHistory.vue      #   Backup list with download, restore, and delete
│   ├── routes.js                      # Stub for DWC's route registration API (Jest only)
│   └── store.js                       # Stub for DWC's Vuex store (Jest only)
├── dsf/                               # SBC backend (Python 3) — identical in both packages
│   ├── meltingplot-config-daemon.py   # Main daemon — DSF connection, HTTP endpoint dispatch
│   ├── config_manager.py              # Core logic: sync, diff, apply (full/file/hunks), backup
│   └── git_utils.py                   # Git CLI wrapper (clone, fetch, checkout, backup repo)
├── scripts/
│   ├── stage.js                       # Assemble the tree a DWC builder is handed
│   ├── build.js                       # Stage + run DWC's build-plugin-pkg + name the ZIP
│   ├── build-zip.js                   # Standalone structure-only ZIP builder for CI
│   ├── ci-local.sh                    # Run the CI pipeline on a workstation
│   └── version.js                     # Version computation from git tags
├── tests/
│   ├── frontend/                      # Jest (Vue 2.7): shared core + the DWC 3.6 UI
│   └── ui37/                          # Vitest (Vue 3.5): the DWC 3.7 UI + the core again
├── .eslintrc.js                       # ESLint config (per-generation overrides)
├── .gitignore
├── babel.config.js                    # Babel config for Jest
├── jest.config.js                     # Jest test runner config
├── package.json                       # Node.js dependencies and scripts
├── pyproject.toml                     # Python project config (pytest, coverage)
├── CLAUDE.md                          # AI assistant instructions
├── PLAN.md                            # Architecture and implementation plan
├── docs/PLAN-dwc37-dual-build.md      # Plan for the DWC 3.6 + 3.7 dual build
└── README.md
```

## Reference Repository Layout

Each printer model has its own git repo with firmware versions as branches:

```
meltingplot-config-mp400.git
├── branch: 3.5.0
│   ├── sys/           → 0:/sys/
│   ├── macros/        → 0:/macros/
│   └── filaments/     → 0:/filaments/
├── branch: 3.5.1
│   └── ...
```

### Protected files

Some files hold machine-specific data (calibration, per-machine tuning) and are
never overwritten by a reference update. They are hidden from the diff view and
reported as `skipped` by *Apply all*:

- `sys/config-override.g` — RepRapFirmware's own `M500` output
- `sys/meltingplot/machine-override`
- `sys/meltingplot/dsf-config-override.g`
- `sys/meltingplot/global-override.g`
- `filaments/<profile>/config-override.g` — per-material tuning (pressure advance, retract, …)
- `filaments/<profile>/temps.g` — per-material temperatures

A filament profile's `config.g`, `load.g` and `unload.g` stay updatable — they are
machine-generated on the printer, not hand-edited.

Protection applies to the printer's **existing** copy only. If a protected file is
missing on the printer — e.g. a filament profile the printer has never seen — there
is nothing to preserve, so it shows up in the diff view as `missing` and is created
from the reference by *Create File* or *Apply all*. Once created, it is protected
from all further reference updates.

## Partial apply

Everything on the **Changes** tab starts selected. Uncheck a file in its header — or
uncheck individual hunks inside a file — and the toolbar button changes from
**Apply All** to **Partially Apply**. Pressing it sends only what is still selected to
`POST /applySelection`: whole files for the ones you left alone, just the checked hunks
for the ones you narrowed down, and nothing at all for the files you excluded. The whole
selection is written under a single pair of backup commits, so one partial apply is one
restore point.

Unchecking every hunk in a file is the same as unchecking the file. Files marked `extra`
(present on the printer but not in the reference) are never applied and have no checkbox.

## API Endpoints

All endpoints are under `/machine/MeltingplotConfig/`. Dynamic parameters use query strings (DSF uses exact path matching, no path parameters).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/machine/MeltingplotConfig/status` | Sync status, FW version, active branch, last sync time |
| `POST` | `/machine/MeltingplotConfig/sync` | Trigger git fetch + checkout |
| `GET` | `/machine/MeltingplotConfig/branches` | List available branches |
| `GET` | `/machine/MeltingplotConfig/diff` | Full diff (all files) |
| `GET` | `/machine/MeltingplotConfig/diff?file=<path>` | Single file diff with indexed hunks |
| `GET` | `/machine/MeltingplotConfig/reference` | List files in reference repo |
| `POST` | `/machine/MeltingplotConfig/apply` | Apply all reference config (with backup) |
| `POST` | `/machine/MeltingplotConfig/apply?file=<path>` | Apply a single file (with backup) |
| `POST` | `/machine/MeltingplotConfig/applyHunks?file=<path>` | Apply selected hunks (body: `{"hunks": [0, 2, 5]}`) |
| `POST` | `/machine/MeltingplotConfig/applySelection` | Apply a mixed selection in one pass (body: `{"files": ["sys/homeall.g", {"file": "sys/config.g", "hunks": [0, 2]}]}`) |
| `GET` | `/machine/MeltingplotConfig/backups` | List backup commits |
| `POST` | `/machine/MeltingplotConfig/manualBackup` | Create manual backup with optional message |
| `GET` | `/machine/MeltingplotConfig/backup?hash=<hash>` | View backup file list and changed files |
| `GET` | `/machine/MeltingplotConfig/backupDownload?hash=<hash>` | Download backup as ZIP |
| `GET` | `/machine/MeltingplotConfig/backupFileDiff?hash=<hash>&file=<path>` | Diff between backup and current file |
| `POST` | `/machine/MeltingplotConfig/restore?hash=<hash>` | Restore from backup |
| `POST` | `/machine/MeltingplotConfig/deleteBackup?hash=<hash>` | Delete a backup commit |
| `POST` | `/machine/MeltingplotConfig/settings` | Update plugin settings |

## Testing

### Backend (Python)

- **Framework:** pytest
- **Install:** `pip install pytest pytest-cov`
- **Run:** `pytest tests/ -v`

Test files:

| File | Description |
|------|-------------|
| `tests/test_git_utils.py` | Git operations (clone, fetch, branches, checkout) |
| `tests/test_git_utils_extra.py` | Additional git tests (list_files, edge cases) |
| `tests/test_config_manager.py` | Diff engine, hunk parsing, apply, path conversion |
| `tests/test_config_manager_methods.py` | ConfigManager method-level tests |
| `tests/test_daemon.py` | Response helpers, handler functions, endpoint registry |
| `tests/test_daemon_handlers.py` | Handler edge cases, plugin data helpers |
| `tests/test_daemon_startup.py` | Daemon startup, settings loading, directory mapping |
| `tests/test_integration.py` | Full sync/diff/apply/backup/restore round-trip with real git repos |
| `tests/test_e2e.py` | End-to-end: daemon handlers wired to real ConfigManager and filesystem |

### Frontend (JavaScript)

- **Framework:** Jest 29 + @vue/test-utils 1.x (Vue 2)
- **Install:** `npm install`
- **Run:** `npm test` (all tests), `npm run test:unit` (unit only), `npm run test:integration` (integration only)

The suite runs the shared `src/core/` logic and the DWC 3.6 components under Vue 2.7.

### DWC 3.7 UI (Vitest)

Two Vue majors cannot share one `node_modules`, so the 3.7 tests are their own npm package.

- **Framework:** Vitest 2 + @vue/test-utils 2 + happy-dom, with real Vuetify 4
- **Install & run:** `npm --prefix tests/ui37 ci && npm run test:ui37` — needs **Node 22+**
  (`scripts/ci-local.sh ui37` falls back to a container on an older Node)
- It mounts the four DWC 3.7 components and the entry point, **and runs the whole of
  `tests/frontend/core/` a second time** under Vue 3's reactivity — which is what proves
  the shared logic really is generation-neutral.

The 3.7 templates are additionally type-checked by `vue-tsc` during the 3.7 build leg.

Test files:

| File | Description |
|------|-------------|
| `tests/frontend/ConfigStatus.test.js` | Props rendering, status mapping, button state, events |
| `tests/frontend/ConfigDiff.test.js` | File filtering, hunk selection/deselection, emit payloads |
| `tests/frontend/ConfigDiffExtra.test.js` | Additional diff tests (side-by-side rendering, edge cases) |
| `tests/frontend/BackupHistory.test.js` | Empty/loading states, backup display, expand/collapse |
| `tests/frontend/MeltingplotConfig.test.js` | Main plugin component (tab rendering, routing) |
| `tests/frontend/core/host.test.js` | The Host seam, `plugin.data` access (Map and object) |
| `tests/frontend/core/api.test.js` | fetch wrappers, error extraction, download helper |
| `tests/frontend/core/diff.test.js` | Hunk parsing, side-by-side rows, selection payload |
| `tests/frontend/core/status.test.js` | Sync-status chip mapping |
| `tests/frontend/core/backend.test.js` | Backend recovery + the DWC 3.6 Vuex adapter |
| `tests/frontend/core/useBackupHistory.test.js` | File tree building, backup normalisation |
| `tests/frontend/integration/full-mount.test.js` | Full component tree with real Vuetify |
| `tests/frontend/integration/plugin-registration.test.js` | DWC plugin registration contract |
| `tests/frontend/integration/plugin-structure.test.js` | Plugin ZIP structure validation |
| `tests/frontend/integration/user-flows.test.js` | End-to-end user flows with mock backend |
| `tests/frontend/integration/api-contract.test.js` | Daemon API response shapes match frontend expectations |

### Linting

```bash
npm run lint
```

ESLint 8 with `eslint-plugin-vue`, configured per source area:

| Files | Rules |
|---|---|
| `src/core/**` | `eslint:recommended` — framework-neutral, no Vue rules |
| `src/ui36/**` | `plugin:vue/recommended` (Vue 2) |
| `src/ui37/**` | `plugin:vue/vue3-recommended` with `@typescript-eslint/parser` |

## CI/CD

GitHub Actions workflow at `.github/workflows/ci.yml`:

1. **Python Tests** — `pytest` with coverage on Python 3.10, 3.11, 3.12
2. **Frontend Lint & Tests** — `npm run lint` + unit, core and integration tests on Node.js 18
3. **DWC 3.7 UI Tests** — Vitest in `tests/ui37/` on Node.js 22
4. **Build** — a two-leg matrix, one package per DWC generation:
   | Leg | DuetWebControl | Node | Artifact |
   |---|---|---|---|
   | `36` | `v3.6-dev` | 18 | `MeltingplotConfig-plugin-dwc36` |
   | `37` | `v3.7-dev` | 22 | `MeltingplotConfig-plugin-dwc37` |

   Each leg stages its own tree, runs DWC's `build-plugin-pkg` and checks the packaged
   manifest: the right `dwcVersion`, a populated `dwcFiles` (an empty one would make DWC
   load the plugin as SBC-only and never show the page) and the daemon in `dsfFiles`. The
   3.7 leg also runs `vue-tsc` against the templates — that type check is what catches a
   Vuetify 4 prop that silently changed meaning.

Triggers: push to `main`/`master`, pull requests to `main`/`master`, manual dispatch with
per-generation DWC ref overrides.

`.github/workflows/release.yml` runs the same two legs on a push to `release`, resolves
the newest stable tag **of each series** (`v3.6.*` / `v3.7.*`), and attaches both ZIPs to
one GitHub Release.

### Running CI locally

`scripts/ci-local.sh` reproduces the pipeline on a workstation. Everything it needs lives
in the gitignored `.ci-local/` directory (Python virtualenv, two DuetWebControl checkouts,
built ZIPs) — nothing is installed system-wide.

```bash
scripts/ci-local.sh            # python, frontend, ui37, both build legs
scripts/ci-local.sh python     # pytest in .ci-local/venv
scripts/ci-local.sh frontend   # npm ci + lint + jest unit/core/integration
scripts/ci-local.sh ui37       # Vitest: the DWC 3.7 UI + the core under Vue 3
scripts/ci-local.sh build36    # DWC 3.6 checkout + build.js 36
scripts/ci-local.sh build37    # DWC 3.7 checkout + build.js 37
scripts/ci-local.sh matrix     # pytest on Python 3.10-3.12 via Docker
```

The `matrix` stage needs Docker; it mirrors the CI's Python version matrix, which a
single local interpreter cannot cover. `ui37` and `build37` need **Node 22+** — when the
host Node is older, they run in a `node:22` container instead, so Docker is required in
that case too.

Both build stages temporarily run `scripts/version.js --write` (as CI does) and restore
`plugin.json` / `package.json` afterwards, so the working tree stays clean. The resulting
ZIPs are copied to `.ci-local/dist/`.

Overrides: `DWC36_REF` / `DWC37_REF` select the DuetWebControl refs (defaults `v3.6-dev`
and `v3.7-dev`), `PYTHON=<interpreter>` selects the interpreter used for the venv.

## License

LGPL-3.0-or-later
