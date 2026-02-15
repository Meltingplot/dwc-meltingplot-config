#!/usr/bin/env node
/**
 * Build script: assembles the DWC plugin ZIP.
 *
 * The ZIP structure matches what DWC expects when installing a plugin:
 *
 *   MeltingplotConfig-<version>.zip
 *   ├── plugin.json
 *   ├── dsf/
 *   │   ├── meltingplot-config-daemon.py
 *   │   ├── config_manager.py
 *   │   └── git_utils.py
 *   └── dwc/
 *       └── MeltingplotConfig/
 *           └── ... (source files, to be compiled by DWC's build-plugin in production)
 *
 * For a full production build, use DWC's build-plugin command instead:
 *   cd DuetWebControl && npm run build-plugin /path/to/dwc-meltingplot-config
 *
 * This script creates a standalone ZIP for CI artifact purposes.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const archiver = require('archiver');

const ROOT = path.resolve(__dirname, '..');
const pluginJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'));
const version = pluginJson.version;
const pluginId = pluginJson.id;

const DIST_DIR = path.join(ROOT, 'dist');
const ZIP_NAME = `${pluginId}-${version}.zip`;
const ZIP_PATH = path.join(DIST_DIR, ZIP_NAME);

// Ensure dist directory exists
fs.mkdirSync(DIST_DIR, { recursive: true });

const output = fs.createWriteStream(ZIP_PATH);
const archive = archiver('zip', { zlib: { level: 9 } });

output.on('close', () => {
    const sizeKB = (archive.pointer() / 1024).toFixed(1);
    console.log(`Built ${ZIP_NAME} (${sizeKB} KB)`);
});

archive.on('error', (err) => {
    console.error('Archive error:', err);
    process.exit(1);
});

archive.pipe(output);

// plugin.json at root
archive.file(path.join(ROOT, 'plugin.json'), { name: 'plugin.json' });

// dsf/ — Python backend files
const dsfDir = path.join(ROOT, 'dsf');
const dsfFiles = fs.readdirSync(dsfDir).filter(f => f.endsWith('.py'));
for (const file of dsfFiles) {
    archive.file(path.join(dsfDir, file), { name: `dsf/${file}` });
}

// dwc/ — Frontend source files (for DWC's plugin loader)
// In a production build, these would be compiled JS chunks.
// For CI, we include the source so the ZIP is a valid plugin structure.
archive.directory(path.join(ROOT, 'src'), 'dwc/src');

archive.finalize();
