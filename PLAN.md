# Implementation Plan: dwc-meltingplot-config

## Goal

Build a **combined DWC + DSF plugin** that keeps Meltingplot 3D printer configurations up to date. A **Python SBC backend** fetches reference configurations from a git repository (one repo per printer model, one branch per firmware version), compares them against the printer's current config, manages backups via a local git repo, and exposes an HTTP API. A **DWC frontend** provides the user interface for reviewing drift, applying updates, and browsing backup history.

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
| Reference config source | Fetched from a **git repository** — **one repo per printer model**, URL configured in plugin settings |
| Firmware versioning | **One branch per firmware version** within the printer model's repo |
| SBC/DSF usage | **Yes** — Python SBC backend handles git operations, diffing, and backups |
| Scope of configs | **Entire reference bundle** — every config file in the reference package |
| Versioning | Addresses **both printer model** (repo) **and firmware version** (branch) |
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
    "readMacros",
    "writeMacros",
    "readFilaments",
    "writeFilaments",
    "networkAccess",
    "setPluginData"
  ],
  "sbcPythonDependencies": [],
  "sbcData": {
    "referenceRepoUrl": "",
    "firmwareBranchOverride": "",
    "detectedFirmwareVersion": "",
    "activeBranch": "",
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
  - `referenceRepoUrl` — the git repo URL for this printer model
  - `firmwareBranchOverride` — manual override (empty = auto-detect, which is the default)
  - `detectedFirmwareVersion` — firmware version read from the board (informational)
  - `activeBranch` — the branch currently checked out (auto-detected or overridden)

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

### 2.1 Reference repository model

Each printer model has its **own git repository**. Firmware versions are tracked as **branches** within that repo.

**Example:** A printer model "MP-400" with configs for firmware 3.5.0 and 3.5.1:

```
meltingplot-config-mp400.git          # one repo per printer model
├── branch: main                       # default branch (latest stable)
├── branch: 3.5.0                      # firmware version branch
│   ├── sys/                           # system config files → 0:/sys/
│   │   ├── config.g
│   │   ├── config-override.g
│   │   ├── homeall.g
│   │   ├── homex.g
│   │   ├── homey.g
│   │   ├── homez.g
│   │   ├── bed.g
│   │   └── ...
│   ├── macros/                        # macro files → 0:/macros/
│   │   ├── print_start.g
│   │   ├── print_end.g
│   │   └── ...
│   ├── filaments/                     # filament configs → 0:/filaments/
│   │   ├── PLA/
│   │   │   ├── config.g
│   │   │   ├── load.g
│   │   │   └── unload.g
│   │   ├── PETG/
│   │   │   └── ...
│   │   └── ...
│   └── manifest.json                  # optional metadata
├── branch: 3.5.1
│   ├── sys/
│   ├── macros/
│   ├── filaments/
│   │   └── ... (updated configs)
│   └── manifest.json
```

**Advantages of this approach:**
- `git diff 3.5.0..3.5.1` instantly shows what changed between firmware versions
- Access control is per-repo (per printer model)
- Clean separation — no deeply nested directory trees
- Branches can be created from each other, inheriting config and tracking deltas

**Operations:**
- `git clone <referenceRepoUrl>` on first run (stored at `/opt/dsf/plugins/MeltingplotConfig/reference/`)
- `git fetch` + `git checkout <branch>` to switch firmware versions
- `git pull` on manual or scheduled sync to get latest changes for the current branch

### 2.2 Config resolver

The branch is **automatically selected** from the printer's firmware version. Manual override is only for edge cases.

**Resolution order:**

1. Read firmware version from the DSF object model (`boards[0].firmwareVersion`), store in `detectedFirmwareVersion`
2. If `firmwareBranchOverride` is set (non-empty), use that instead — this is a manual escape hatch, not the normal path
3. `git checkout <resolved-branch>` in the local reference clone, update `activeBranch`
4. If the exact branch does not exist, list available branches and find the closest match (e.g., firmware `3.5.1` with no `3.5.1` branch falls back to `3.5`) — surface a warning to the user

**On firmware update:** When the printer firmware changes, the plugin detects the new version on next status check and automatically switches to the matching branch, triggering a new diff.

### 2.3 Diff engine

Compares every file in the reference config set against the printer's current files across all managed directories:

| Reference directory | Printer path | DSF permission |
|---------------------|-------------|----------------|
| `sys/` | `0:/sys/` | `readSystem` / `writeSystem` |
| `macros/` | `0:/macros/` | `readMacros` / `writeMacros` |
| `filaments/` | `0:/filaments/` | `readFilaments` / `writeFilaments` |

**Process:**

1. List all files in the reference set across `sys/`, `macros/`, and `filaments/`
2. For each file, read the current version from the corresponding `0:/` path via DSF file API
3. Produce a unified diff for each changed file
4. Categorize: `unchanged`, `modified`, `missing` (exists in reference but not on printer), `extra` (exists on printer but not in reference)

**HTTP API endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/machine/MeltingplotConfig/status` | Sync status, active branch, FW version |
| `POST` | `/machine/MeltingplotConfig/sync` | Trigger git fetch + checkout of reference repo |
| `GET` | `/machine/MeltingplotConfig/branches` | List available branches (firmware versions) |
| `GET` | `/machine/MeltingplotConfig/diff` | Full diff: reference branch vs current config |
| `GET` | `/machine/MeltingplotConfig/diff/{file}` | Diff for a single file |
| `GET` | `/machine/MeltingplotConfig/reference` | List reference config files on active branch |
| `GET` | `/machine/MeltingplotConfig/backups` | List backup commits (git log) |
| `POST` | `/machine/MeltingplotConfig/apply` | Apply reference config (with backup) |
| `POST` | `/machine/MeltingplotConfig/apply/{file}` | Apply a single file |
| `GET` | `/machine/MeltingplotConfig/backup/{commitHash}` | View a specific backup snapshot |
| `GET` | `/machine/MeltingplotConfig/backup/{commitHash}/download` | Download backup as ZIP archive |
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

- Firmware version (auto-detected from board) and active reference branch
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
- "Download" button per commit — downloads a ZIP of all config files from that snapshot
- "Restore" button per commit (with confirmation)

### 3.4 Settings panel

Either a settings tab or a section within the main page:
- Reference repository URL (text field — the repo for this printer model)
- Detected firmware version and active branch (read-only, shows what was auto-selected)
- Branch override (optional text field — only used when auto-detection doesn't match a branch)
- Available branches list (fetched from remote, shown as reference)
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
4. User configures the reference repo URL (for their printer model) in the Settings tab
5. Plugin auto-detects firmware version → checks out matching branch → compares configs

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
