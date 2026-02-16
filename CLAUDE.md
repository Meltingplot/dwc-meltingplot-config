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
- **Backend:** Python 3 (runs as DSF SBC plugin process)
- **State management:** Vuex 3 (machine model via `machine/model` store)
- **Bundler:** Webpack (Vue CLI 5) via DWC's `build-plugin` script
- **DSF communication:** `dsf-python` library (Unix socket, installed via `sbcPythonDependencies` in plugin venv)
- **Git operations:** `git` CLI via subprocess
- **Diffing/patching:** Python `difflib` (standard library)
- **Target DWC version:** 3.6 (`v3.6-dev` branch of Duet3D/DuetWebControl)

## Development Setup

### Building the frontend

```bash
git clone -b v3.6-dev https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl && npm install
npm run build-plugin /path/to/dwc-meltingplot-config/src
```

Output: `dist/MeltingplotConfig-<version>.zip`

### Backend

The Python backend requires no build step. It runs on the SBC under DSF.

## Testing

### Backend (Python)

- **Framework:** pytest
- **Run:** `pytest tests/ -v` (uses `pyproject.toml` for pythonpath config)
- **Install:** `pip install pytest`
- **Test files:**
  - `tests/test_git_utils.py` — Git operations (clone, fetch, branches, backup repo)
  - `tests/test_config_manager.py` — Diff engine, hunk parsing, hunk apply, path conversion, round-trip
  - `tests/test_daemon.py` — Response helpers, handler functions, endpoint registry (mocks DSF library)
  - `tests/test_daemon_handlers.py` — Handler edge cases, plugin data helpers, register_endpoints

### Frontend (JavaScript)

- **Framework:** Jest 29 + @vue/test-utils 1.x (Vue 2)
- **Run:** `npm test`
- **Test files (in `tests/frontend/`):**
  - `ConfigStatus.test.js` — Props rendering, status mapping, button state, events
  - `ConfigDiff.test.js` — File filtering, hunk selection/deselection, emit payloads, CSS class logic
  - `BackupHistory.test.js` — Empty/loading states, backup display, expand/collapse, fetch mocking
- **Integration tests (in `tests/frontend/integration/`):**
  - `full-mount.test.js` — Full component tree with real Vuetify
  - `plugin-registration.test.js` — DWC plugin registration contract
  - `plugin-structure.test.js` — Plugin ZIP structure validation
  - `user-flows.test.js` — End-to-end user flows with mock backend

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
| Backup strategy | Local git repo at `/opt/dsf/plugins/MeltingplotConfig/backups/` |
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
- Backend: Follow PEP 8 / PEP 257. Use `logging` module, not print.
- Prefer editing existing files over creating new ones.
- Do not add unnecessary abstractions or over-engineer solutions.
- Keep this CLAUDE.md updated as the project evolves.
