# Implementation Plan: dwc-meltingplot-config

## Goal

Build a **Duet Web Control (DWC) plugin** that helps keep 3D printer configurations up to date for Meltingplot printers. The plugin runs entirely in the browser (DWC-only), works in both standalone and SBC modes, and provides a UI for viewing, comparing, and updating printer configuration files.

---

## Phase 1: Project Scaffold

Set up the repository structure following the DWC external plugin conventions.

### 1.1 Create the plugin manifest (`plugin.json`)

The root-level `plugin.json` defines the plugin for DWC's build and installation system.

```json
{
  "id": "MeltingplotConfig",
  "name": "Meltingplot Config",
  "author": "Meltingplot",
  "version": "0.1.0",
  "license": "LGPL-3.0-or-later",
  "homepage": "https://github.com/Meltingplot/dwc-meltingplot-config",
  "dwcVersion": "auto",
  "sbcRequired": false,
  "tags": ["meltingplot", "configuration", "config-management"]
}
```

Key decisions:
- **`id`: `MeltingplotConfig`** — alphanumeric, max 32 chars, used as webpack chunk name
- **`dwcVersion`: `"auto"`** — auto-populated at build time with the DWC version
- **`sbcRequired`: `false`** — pure DWC plugin, no SBC dependency
- **License**: LGPL-3.0-or-later (matching DWC's own license)

### 1.2 Create the entry point (`src/index.js`)

Registers a route under the **Plugins** menu category using DWC's `registerRoute` API.

```
src/
  index.js                  # Plugin entry — registers route(s)
  MeltingplotConfig.vue     # Main page component
  components/               # Reusable sub-components (added as needed)
```

### 1.3 Create the main Vue component (`src/MeltingplotConfig.vue`)

Initial skeleton that:
- Connects to the Vuex store (`machine/model`) to read the machine object model
- Displays current board info and firmware version
- Provides a placeholder for configuration management features

### 1.4 Update `CLAUDE.md`

Update the project documentation to reflect the new structure, build commands, and conventions.

### 1.5 Add a `README.md`

Provide a user-facing README with:
- What the plugin does
- How to build it
- How to install it on a Duet controller

---

## Phase 2: Core Configuration Features

### 2.1 Configuration file viewer

- Use DWC's `getFileList()` and `download()` actions to list and read config files from `0:/sys/` (e.g., `config.g`, `config-override.g`, `homeall.g`, etc.)
- Display the files in a navigable list with content preview
- Show file metadata (size, last modified)

### 2.2 Configuration comparison / drift detection

- Define a **reference configuration** (bundled with the plugin or fetched from a known source)
- Compare the printer's current `config.g` against the reference
- Highlight differences (added/removed/changed lines)
- Surface a status indicator: "up to date" vs. "changes available"

### 2.3 Configuration update workflow

- Present a diff view showing proposed changes
- Allow the user to accept or reject individual changes
- Use DWC's `upload()` action to write updated config files back to `0:/sys/`
- Optionally back up the existing config before overwriting

---

## Phase 3: Build & Development Workflow

### 3.1 Build process

DWC plugins are built using DWC's own build toolchain. The workflow:

```bash
# One-time setup: clone DWC and install deps
git clone https://github.com/Duet3D/DuetWebControl.git
cd DuetWebControl
npm install

# Build the plugin (point to this repo's root, which contains plugin.json)
npm run build-plugin /path/to/dwc-meltingplot-config

# Output: dist/MeltingplotConfig-0.1.0.zip
```

The build script:
1. Validates `plugin.json`
2. Copies plugin source into DWC's plugin directory
3. Runs webpack to produce named chunks (`MeltingplotConfig.*.js`)
4. Packages the chunks + manifest into a ZIP

### 3.2 Development server

For iterative development:

```bash
cd DuetWebControl
# Copy/symlink plugin into src/plugins/MeltingplotConfig/
npm run serve
# Access at localhost:8080, connect to a Duet board with CORS enabled
```

### 3.3 Installation

Upload the built `.zip` file via **DWC -> Settings -> Plugins -> Install Plugin**.

---

## Proposed Repository Structure (after Phase 1)

```
dwc-meltingplot-config/
├── plugin.json             # DWC plugin manifest
├── src/
│   ├── index.js            # Entry point — registers routes
│   ├── MeltingplotConfig.vue  # Main plugin page
│   └── components/         # Sub-components (added as needed)
├── .gitignore              # Python + Node artifacts
├── CLAUDE.md               # AI assistant instructions
└── README.md               # User-facing documentation
```

---

## Technology Stack

| Component       | Technology          | Notes                                    |
|-----------------|---------------------|------------------------------------------|
| UI framework    | Vue.js 2.7         | Required by DWC (stable branch)          |
| UI components   | Vuetify 2.7        | Material Design, globally available      |
| State           | Vuex               | Access machine model via `machine/model` |
| Bundler         | Webpack (Vue CLI 5) | Via DWC's build system                  |
| Icons           | Material Design Icons | `mdi-*` prefix                         |
| Language        | JavaScript (ES6+)  | TypeScript optional but not required     |
| Package format  | ZIP                 | Built by `npm run build-plugin`          |

---

## Immediate Next Steps (What to implement now)

1. **`plugin.json`** — Create the manifest at repository root
2. **`src/index.js`** — Register the plugin route
3. **`src/MeltingplotConfig.vue`** — Initial page showing printer info
4. **`README.md`** — Build and install instructions
5. **`CLAUDE.md`** — Update with project structure and conventions
6. **`.gitignore`** — Add Node.js patterns (node_modules, dist, etc.)

Phase 2 features (config viewer, diff, update) will be built incrementally after the scaffold is working.

---

## Open Questions

- **Reference config source**: Should reference configurations be bundled in the plugin ZIP (under `sd/`), fetched from a remote URL, or stored on the printer's SD card in a known location?
- **Scope of configs**: Which config files should the plugin manage — only `config.g`, or also `homeall.g`, `bed.g`, tool definitions, etc.?
- **Versioning scheme**: Should configs be versioned per printer model, per firmware version, or both?
- **Python component**: The `.gitignore` suggests Python was considered. Should there be a DSF/SBC Python component for background config sync, or is a DWC-only approach sufficient?
