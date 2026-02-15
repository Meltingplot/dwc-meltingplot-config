# Meltingplot Config

A DWC + DSF plugin that keeps Meltingplot 3D printer configurations up to date.

## What It Does

- **Syncs** reference configurations from a git repository (one repo per printer model, one branch per firmware version)
- **Diffs** the reference against the printer's current config, showing changes at the hunk level
- **Applies** updates — all at once, per file, or by selecting individual change blocks
- **Backs up** every config change in a local git repository with full history and restore

## Requirements

- Duet SBC (Raspberry Pi) running **DSF 3.5+**
- Duet Web Control (DWC) **3.5+**
- Git installed on the SBC

## Building

The DWC frontend is built via DWC's build system. The DSF backend is plain Python (no build step).

```bash
# Clone DWC and install dependencies
git clone https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl && npm install

# Build the plugin ZIP
npm run build-plugin /path/to/dwc-meltingplot-config
# Output: dist/MeltingplotConfig-0.1.0.zip
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
├── src/                               # DWC frontend (Vue 2 + Vuetify 2)
│   ├── index.js                       # Entry point — registers route
│   ├── MeltingplotConfig.vue          # Main page with tabs
│   └── components/
│       ├── ConfigStatus.vue           # Status dashboard
│       ├── ConfigDiff.vue             # Diff viewer with hunk selection
│       └── BackupHistory.vue          # Backup browser with download
├── dsf/                               # SBC backend (Python)
│   ├── meltingplot-config-daemon.py   # Main daemon (DSF runs this)
│   ├── config_manager.py             # Core logic: sync, diff, apply
│   └── git_utils.py                  # Git operations wrapper
├── .gitignore
├── CLAUDE.md
├── PLAN.md
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

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/machine/MeltingplotConfig/status` | Sync status, active branch, FW version |
| `POST` | `/machine/MeltingplotConfig/sync` | Trigger git fetch + checkout |
| `GET` | `/machine/MeltingplotConfig/branches` | List available branches |
| `GET` | `/machine/MeltingplotConfig/diff` | Full diff: reference vs current config |
| `GET` | `/machine/MeltingplotConfig/diff/{file}` | Diff for a single file (with indexed hunks) |
| `POST` | `/machine/MeltingplotConfig/apply` | Apply all reference config (with backup) |
| `POST` | `/machine/MeltingplotConfig/apply/{file}` | Apply a single file |
| `POST` | `/machine/MeltingplotConfig/apply/{file}/hunks` | Apply selected hunks only |
| `GET` | `/machine/MeltingplotConfig/backups` | List backup commits |
| `GET` | `/machine/MeltingplotConfig/backup/{hash}` | View backup snapshot |
| `GET` | `/machine/MeltingplotConfig/backup/{hash}/download` | Download backup as ZIP |
| `POST` | `/machine/MeltingplotConfig/restore/{hash}` | Restore from backup |

## License

LGPL-3.0-or-later
