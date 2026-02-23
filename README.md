# Meltingplot Config

A DWC + DSF plugin that keeps Meltingplot 3D printer configurations up to date.

## What It Does

- **Syncs** reference configurations from a git repository (one repo per printer model, one branch per firmware version)
- **Diffs** the reference against the printer's current config, showing changes at the hunk level
- **Applies** updates — all at once, per file, or by selecting individual change blocks
- **Backs up** every config change in a local git repository with full history and restore

## Requirements

- Duet SBC (Raspberry Pi) running **DSF 3.6+**
- Duet Web Control (DWC) **3.6+**
- Git installed on the SBC
- Python **3.9+** (on the SBC)

## Building

The DWC frontend is built via DWC's build system. The DSF backend is plain Python (no build step).

```bash
# Clone DWC (v3.6-dev branch) and install dependencies
git clone -b v3.6-dev https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl && npm install

# Build the plugin ZIP
npm run build-plugin /path/to/dwc-meltingplot-config
# Output: dist/MeltingplotConfig-<version>.zip
```

For local development and CI, a standalone build script packages source files into a ZIP for structure validation:

```bash
npm run build
# Output: dist/MeltingplotConfig-<version>.zip
```

## Installation

1. Upload the ZIP via **DWC → Settings → Plugins → Install Plugin**
2. DSF extracts the backend files and starts the daemon
3. DWC loads the frontend
4. Navigate to **Plugins → Meltingplot Config**
5. In the **Settings** tab, configure the reference repository URL for your printer model
6. The plugin auto-detects your firmware version, selects the matching branch, and compares configs

## Plugin Structure

```
dwc-meltingplot-config/
├── plugin.json                        # DWC+DSF plugin manifest
├── src/                               # DWC frontend (Vue 2.7 + Vuetify 2.7)
│   ├── index.js                       # Entry point — registers route under Plugins menu
│   ├── MeltingplotConfig.vue          # Main page: tabs for Status/Changes/History/Settings
│   ├── routes.js                      # Stub for DWC's route registration API
│   └── components/
│       ├── ConfigStatus.vue           # Status dashboard (FW version, sync status, branch)
│       ├── ConfigDiff.vue             # Diff viewer with hunk-level checkboxes and apply
│       └── BackupHistory.vue          # Backup list with download, restore, and delete
├── dsf/                               # SBC backend (Python 3)
│   ├── meltingplot-config-daemon.py   # Main daemon — DSF connection, HTTP endpoint dispatch
│   ├── config_manager.py             # Core logic: sync, diff, apply (full/file/hunks), backup
│   └── git_utils.py                  # Git CLI wrapper (clone, fetch, checkout, backup repo)
├── scripts/
│   ├── build-zip.js                   # Standalone plugin ZIP builder for CI
│   └── version.js                     # Version computation from git tags
├── tests/                             # Backend and frontend test suites
├── .eslintrc.js                       # ESLint config (Vue 2 recommended rules)
├── .gitignore
├── babel.config.js                    # Babel config for Jest
├── jest.config.js                     # Jest test runner config
├── package.json                       # Node.js dependencies and scripts
├── pyproject.toml                     # Python project config (pytest, coverage)
├── CLAUDE.md                          # AI assistant instructions
├── PLAN.md                            # Architecture and implementation plan
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

Test files:

| File | Description |
|------|-------------|
| `tests/frontend/ConfigStatus.test.js` | Props rendering, status mapping, button state, events |
| `tests/frontend/ConfigDiff.test.js` | File filtering, hunk selection/deselection, emit payloads |
| `tests/frontend/ConfigDiffExtra.test.js` | Additional diff tests (side-by-side rendering, edge cases) |
| `tests/frontend/BackupHistory.test.js` | Empty/loading states, backup display, expand/collapse |
| `tests/frontend/MeltingplotConfig.test.js` | Main plugin component (tab rendering, routing) |
| `tests/frontend/integration/full-mount.test.js` | Full component tree with real Vuetify |
| `tests/frontend/integration/plugin-registration.test.js` | DWC plugin registration contract |
| `tests/frontend/integration/plugin-structure.test.js` | Plugin ZIP structure validation |
| `tests/frontend/integration/user-flows.test.js` | End-to-end user flows with mock backend |
| `tests/frontend/integration/api-contract.test.js` | Daemon API response shapes match frontend expectations |

### Linting

```bash
npm run lint
```

ESLint 8 with `eslint-plugin-vue` (Vue 2 recommended rules).

## CI/CD

GitHub Actions workflow at `.github/workflows/ci.yml` runs three stages:

1. **Python Tests** — `pytest` with coverage on Python 3.9, 3.10, 3.11, 3.12
2. **Frontend Lint & Tests** — `npm run lint` + unit and integration tests with Node.js 18
3. **Build** — checks out DuetWebControl `v3.6-dev`, runs `build-plugin`, uploads artifact (30-day retention)

Triggers: push to `main`/`master`, pull requests to `main`/`master`, manual dispatch with optional DWC ref override.

## License

LGPL-3.0-or-later
