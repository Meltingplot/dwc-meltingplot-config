# Implementation Plan: dwc-meltingplot-config

## Goal

Build a **combined DWC + DSF plugin** that keeps Meltingplot 3D printer configurations up to date. A **Python SBC backend** fetches reference configurations from a git repository, compares them against the printer's current config, manages backups via git, and exposes an HTTP API. A **DWC frontend** provides the user interface for reviewing drift, applying updates, and browsing backup history.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  DWC Frontend (Vue 2 + Vuetify 2)                   │
│  ┌───────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ Status    │ │ Diff View  │ │ Backup History   │  │
│  │ Dashboard │ │ & Apply    │ │ (git log)        │  │
│  └─────┬─────┘ └─────┬──────┘ └────────┬─────────┘  │
│        │              │                 │            │
│        └──────────────┴─────────────────┘            │
│                       │  HTTP API                    │
├───────────────────────┼─────────────────────────────┤
│  DSF Python Backend   │                              │
│  ┌────────────────────▼──────────────────────────┐   │
│  │  HTTP endpoints (registered via DSF)          │   │
│  ├───────────────────────────────────────────────┤   │
│  │  Reference Repo     │ Config Backup Repo      │   │
│  │  (git clone/pull    │ (local git repo at      │   │
│  │   from remote)      │  /opt/dsf/plugins/      │   │
│  │                     │  MeltingplotConfig/     │   │
│  │                     │  backups/)              │   │
│  ├───────────────────────────────────────────────┤   │
│  │  Config Resolver: printer model + FW version  │   │
│  │  → selects correct reference config set       │   │
│  ├───────────────────────────────────────────────┤   │
│  │  Diff Engine: compare reference vs current    │   │
│  │  Applier: write updated configs to 0:/sys/    │   │
│  └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## Design Decisions (from discussion)

| Question | Decision |
|----------|----------|
| Reference config source | Fetched from a **git repository** (URL configured in plugin settings) |
| SBC/DSF usage | **Yes** — Python SBC backend handles git operations, diffing, and backups |
| Scope of configs | **Entire reference bundle** — every config file in the reference package |
| Versioning | Addresses **both printer model and firmware version** |
| Backup strategy | **Git-based** — local git repo tracks all config changes over time |

---

## Phase 1: Project Scaffold

### 1.1 Plugin manifest (`plugin.json`)

```json
{
  "id": "MeltingplotConfig",
  "name": "Meltingplot Config",
  "author": "Meltingplot",
  "version": "0.1.0",
  "license": "LGPL-3.0-or-later",
  "homepage": "https://github.com/Meltingplot/dwc-meltingplot-config",
  "dwcVersion": "auto",
  "sbcRequired": true,
  "sbcDsfVersion": "3.5",
  "sbcExecutable": "meltingplot-config-daemon.py",
  "sbcExecutableArguments": null,
  "sbcOutputRedirected": true,
  "sbcPermissions": [
    "commandExecution",
    "objectModelRead",
    "objectModelReadWrite",
    "registerHttpEndpoints",
    "fileSystemAccess",
    "readSystem",
    "writeSystem",
    "networkAccess",
    "setPluginData"
  ],
  "sbcPythonDependencies": [],
  "sbcData": {
    "referenceRepoUrl": "",
    "printerModel": "",
    "lastSyncTimestamp": "",
    "status": "not_configured"
  },
  "tags": ["meltingplot", "configuration", "config-management"]
}
```

Key changes from earlier draft:
- **`sbcRequired`: `true`** — git operations need the SBC
- **`sbcDsfVersion`: `"3.5"`** — minimum DSF version
- **`sbcExecutable`** — Python daemon process
- **`sbcPermissions`** — file system, network (git fetch), HTTP endpoints, object model access
- **`sbcData`** — plugin-specific state exposed via the DSF object model

### 1.2 Repository structure

```
dwc-meltingplot-config/
├── plugin.json                     # DWC+DSF plugin manifest
├── src/                            # DWC frontend source (Vue 2)
│   ├── index.js                    # Entry point — registers routes
│   ├── MeltingplotConfig.vue       # Main plugin page
│   └── components/
│       ├── ConfigStatus.vue        # Status dashboard widget
│       ├── ConfigDiff.vue          # Side-by-side diff viewer
│       └── BackupHistory.vue       # Git log / backup browser
├── dsf/                            # SBC backend (Python)
│   ├── meltingplot-config-daemon.py  # Main executable (DSF runs this)
│   ├── config_manager.py           # Core logic: sync, diff, apply
│   └── git_utils.py               # Git operations wrapper
├── .gitignore
├── CLAUDE.md
├── README.md
└── PLAN.md                         # This file
```

### 1.3 DWC frontend entry point (`src/index.js`)

Registers a route under the **Plugins** menu:

```js
'use strict'

import { registerRoute } from '@/routes'
import MeltingplotConfig from './MeltingplotConfig.vue'

registerRoute(MeltingplotConfig, {
    Plugins: {
        MeltingplotConfig: {
            icon: 'mdi-update',
            caption: 'Meltingplot Config',
            translated: true,
            path: '/MeltingplotConfig'
        }
    }
});
```

### 1.4 DWC frontend main component (`src/MeltingplotConfig.vue`)

Initial skeleton with tabs:
- **Status** — current printer model, firmware version, sync status, last check timestamp
- **Changes** — diff view (Phase 2)
- **History** — backup log (Phase 2)
- **Settings** — reference repo URL, printer model selection

### 1.5 DSF Python daemon (`dsf/meltingplot-config-daemon.py`)

The SBC executable that:
1. Connects to DSF via the Unix socket (`/var/run/dsf/dcs.sock`)
2. Registers HTTP endpoints under `/machine/MeltingplotConfig/`
3. Reads plugin data (`sbcData`) for configuration
4. Runs an event loop handling API requests from the DWC frontend

### 1.6 Documentation

- **`README.md`** — what the plugin does, how to build, how to install
- **`CLAUDE.md`** — updated with full project structure and dev conventions

---

## Phase 2: SBC Backend — Reference Sync & Diff Engine

### 2.1 Reference repository management

The Python backend manages a local clone of the reference config repository.

**Reference repo structure convention** (in the remote git repo):

```
reference-configs/
├── <printer-model>/
│   ├── <firmware-version>/
│   │   ├── sys/
│   │   │   ├── config.g
│   │   │   ├── config-override.g
│   │   │   ├── homeall.g
│   │   │   ├── homex.g
│   │   │   ├── homey.g
│   │   │   ├── homez.g
│   │   │   ├── bed.g
│   │   │   └── ...
│   │   └── manifest.json       # metadata: compatible FW range, notes
│   └── latest -> 3.5.0/        # symlink to latest version
└── another-model/
    └── ...
```

**Operations:**
- `git clone` on first run (stored at `/opt/dsf/plugins/MeltingplotConfig/reference/`)
- `git pull` on manual or scheduled sync
- Read `manifest.json` to resolve the correct config set for the printer's model + firmware version

### 2.2 Config resolver

Determines which reference config set to use:

1. Read printer model from `sbcData.printerModel` (configured by user in settings)
2. Read firmware version from the DSF object model (`boards[0].firmwareVersion`)
3. Look up `<printer-model>/<firmware-version>/` in the reference repo
4. If exact version not found, fall back to nearest compatible version (using `manifest.json`)

### 2.3 Diff engine

Compares every file in the reference config set against the printer's current files:

1. List all files in the reference set (e.g., `sys/config.g`, `sys/homeall.g`)
2. For each file, read the current version from `0:/sys/` via DSF file API
3. Produce a unified diff for each changed file
4. Categorize: `unchanged`, `modified`, `missing` (exists in reference but not on printer), `extra` (exists on printer but not in reference)

**HTTP API endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/machine/MeltingplotConfig/status` | Sync status, printer model, FW version |
| `POST` | `/machine/MeltingplotConfig/sync` | Trigger git pull of reference repo |
| `GET` | `/machine/MeltingplotConfig/diff` | Full diff: reference vs current config |
| `GET` | `/machine/MeltingplotConfig/diff/{file}` | Diff for a single file |
| `GET` | `/machine/MeltingplotConfig/reference` | List reference config files |
| `GET` | `/machine/MeltingplotConfig/backups` | List backup commits (git log) |
| `POST` | `/machine/MeltingplotConfig/apply` | Apply reference config (with backup) |
| `POST` | `/machine/MeltingplotConfig/apply/{file}` | Apply a single file |
| `GET` | `/machine/MeltingplotConfig/backup/{commitHash}` | View a specific backup snapshot |
| `POST` | `/machine/MeltingplotConfig/restore/{commitHash}` | Restore from a backup |

### 2.4 Backup system (git-based)

A local git repository at `/opt/dsf/plugins/MeltingplotConfig/backups/` tracks all config changes:

1. **Before any update**, the current config files are copied into the backup repo and committed:
   ```
   backup commit: "Pre-update backup — 2026-02-15T14:30:00"
   ```
2. **After applying updates**, the new state is also committed:
   ```
   backup commit: "Applied reference v3.5.0 for ModelX — 2026-02-15T14:30:05"
   ```
3. The git log provides a full history of every config change
4. Any previous state can be restored by checking out a backup commit

---

## Phase 3: DWC Frontend — Full UI

### 3.1 Status dashboard (`ConfigStatus.vue`)

- Printer model + firmware version (auto-detected)
- Reference repo URL and last sync time
- Status badge: "Up to date" / "Updates available" / "Not configured"
- "Check for updates" button (triggers `POST /sync` then `GET /diff`)

### 3.2 Diff viewer (`ConfigDiff.vue`)

- List of changed files with status icons (modified/missing/extra)
- Click a file to see a side-by-side or unified diff
- "Apply all" button + per-file "Apply" button
- Confirmation dialog before applying (warns about backup)

### 3.3 Backup history (`BackupHistory.vue`)

- Scrollable list of backup commits (from `GET /backups`)
- Each entry shows: timestamp, commit message, number of files changed
- Click to expand and see which files were changed
- "Restore" button per commit (with confirmation)

### 3.4 Settings panel

Either a settings tab or a section within the main page:
- Reference repository URL (text field)
- Printer model (dropdown or text, could auto-populate from board info)
- Auto-sync interval (optional: on boot, daily, manual only)

---

## Phase 4: Build & Packaging

### 4.1 Build process

The DWC frontend is built via DWC's build system. The DSF backend is plain Python (no build step).

```bash
# Clone DWC and install deps
git clone https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl && npm install

# Build the plugin ZIP
npm run build-plugin /path/to/dwc-meltingplot-config
# Output: dist/MeltingplotConfig-0.1.0.zip
```

The ZIP will contain:
```
MeltingplotConfig-0.1.0.zip
├── plugin.json
├── dwc/
│   └── js/
│       └── MeltingplotConfig.xxxxx.js
├── dsf/
│   ├── meltingplot-config-daemon.py
│   ├── config_manager.py
│   └── git_utils.py
```

### 4.2 Installation

1. Upload ZIP via **DWC → Settings → Plugins → Install Plugin**
2. DSF extracts `dsf/` files and starts the daemon
3. DWC loads the frontend chunk
4. User configures reference repo URL and printer model in the Settings tab

---

## Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| DWC frontend | Vue.js 2.7 + Vuetify 2.7 | Required by DWC stable branch |
| State management | Vuex | Machine model via `machine/model` store |
| Bundler | Webpack (Vue CLI 5) | Via DWC's build-plugin script |
| Icons | Material Design Icons | `mdi-*` prefix |
| SBC backend | Python 3 | Runs as DSF plugin process |
| DSF communication | `dsf-python` library | Unix socket connection to DSF |
| Git operations | `git` CLI (subprocess) | Available on SBC, no extra deps |
| Diffing | Python `difflib` | Standard library, unified diffs |
| HTTP API | DSF HTTP endpoint registration | Via `registerHttpEndpoints` permission |
| Config backup | Local git repository | Full history, restore any snapshot |

---

## Immediate Next Steps (Phase 1 implementation)

1. **`plugin.json`** — Combined DWC+DSF manifest
2. **`src/index.js`** — DWC entry point, register route
3. **`src/MeltingplotConfig.vue`** — Main page with tab skeleton
4. **`dsf/meltingplot-config-daemon.py`** — SBC daemon with DSF connection + HTTP endpoint stubs
5. **`dsf/config_manager.py`** — Core logic stubs
6. **`dsf/git_utils.py`** — Git wrapper stubs
7. **`.gitignore`** — Add Node.js patterns
8. **`README.md`** — Build and install instructions
9. **`CLAUDE.md`** — Full project documentation update
