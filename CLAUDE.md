# CLAUDE.md

## Project Overview

**dwc-meltingplot-config** is a combined DWC + DSF plugin for Meltingplot 3D printers. It syncs reference configurations from a git repository, diffs them against the printer's current config, and lets users apply updates (all at once, per file, or per hunk). All config changes are backed up in a local git repo.

## Repository Structure

```
dwc-meltingplot-config/
├── plugin.json                        # DWC+DSF plugin manifest
├── src/                               # DWC frontend (Vue 2 + Vuetify 2)
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

- **Frontend:** Vue.js 2.7 + Vuetify 2.7 (required by DWC stable branch)
- **Backend:** Python 3 (runs as DSF SBC plugin process)
- **State management:** Vuex (machine model via `machine/model` store)
- **Bundler:** Webpack (Vue CLI 5) via DWC's `build-plugin` script
- **DSF communication:** `dsf-python` library (Unix socket)
- **Git operations:** `git` CLI via subprocess
- **Diffing/patching:** Python `difflib` (standard library)

## Development Setup

### Building the frontend

```bash
git clone https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl && npm install
npm run build-plugin /path/to/dwc-meltingplot-config
```

Output: `dist/MeltingplotConfig-0.1.0.zip`

### Backend

The Python backend requires no build step. It runs on the SBC under DSF.

## Testing

No test framework is configured yet. When tests are added, document:

- Test framework (e.g., pytest, unittest)
- How to run tests
- Test file naming conventions and directory structure

## Linting & Formatting

No linting or formatting tools are configured yet. When added, document:

- Linter (e.g., ruff, flake8, eslint)
- Formatter (e.g., ruff format, black, prettier)
- Type checker (e.g., mypy, pyright)

## CI/CD

No CI/CD pipelines are configured yet.

## Key Architecture Decisions

| Decision | Choice |
|----------|--------|
| Reference config source | Git repo — one repo per printer model |
| Firmware versioning | One branch per firmware version |
| Backend runtime | Python SBC daemon via DSF |
| Backup strategy | Local git repo at `/opt/dsf/plugins/MeltingplotConfig/backups/` |
| Partial apply | Hunk-level selection — users pick individual change blocks |

## HTTP API

All endpoints are under `/machine/MeltingplotConfig/`. Key endpoints:

- `GET /status` — sync status, firmware version, active branch
- `POST /sync` — fetch + checkout reference repo
- `GET /diff` — full diff (all files)
- `GET /diff/{file}` — single file diff with indexed hunks
- `POST /apply` — apply all changes (with backup)
- `POST /apply/{file}` — apply single file
- `POST /apply/{file}/hunks` — apply selected hunks (body: `{"hunks": [0, 2, 5]}`)
- `GET /backups` — backup history
- `GET /backup/{hash}/download` — download backup as ZIP
- `POST /restore/{hash}` — restore from backup

## Git Workflow

- **Default remote branch:** `main`
- **Commit messages:** Use clear, descriptive messages summarizing the change

## Conventions for AI Assistants

- Frontend: Vue 2 + Vuetify 2 conventions. Use `v-model`, `$set` for reactivity, `mapState` for Vuex.
- Backend: Follow PEP 8 / PEP 257. Use `logging` module, not print.
- Prefer editing existing files over creating new ones.
- Do not add unnecessary abstractions or over-engineer solutions.
- Keep this CLAUDE.md updated as the project evolves.
