#!/usr/bin/env node
/**
 * Build script: assembles a structure-only DWC plugin ZIP.
 *
 * The ZIP structure matches what DWC expects when installing a plugin:
 *
 *   MeltingplotConfig-<version>-dwc<gen>.zip
 *   ├── plugin.json
 *   ├── dsf/
 *   │   ├── meltingplot-config-daemon.py
 *   │   ├── config_manager.py
 *   │   └── git_utils.py
 *   └── dwc/
 *       └── src/
 *           └── ... (staged sources, compiled by DWC's builder in production)
 *
 * The sources come from scripts/stage.js, so this ZIP contains exactly the tree
 * a real build would be handed — which is what the plugin-structure tests check.
 *
 * For a real build, use scripts/build.js instead:
 *   DWC36_DIR=... node scripts/build.js 36
 *
 * Usage:
 *   node scripts/build-zip.js [36|37]      (default: 36)
 *
 * Env: ZIP_OUT_DIR overrides the output directory (default: dist/).
 */

'use strict';

const fs = require('fs');
const path = require('path');
const archiver = require('archiver');

const { execSync } = require('child_process');
const { stage, GENERATIONS } = require('./stage');

const ROOT = path.resolve(__dirname, '..');

const gen = process.argv[2] || '36';
if (!GENERATIONS.includes(gen)) {
    console.error(`Usage: node scripts/build-zip.js [${GENERATIONS.join('|')}]`);
    process.exit(1);
}
const stageDir = stage(gen, path.join(ROOT, '.build', `zip-dwc${gen}`));
const pluginJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'));
const pluginId = pluginJson.id;

// Compute version from git without modifying source files
let version;
try {
    version = execSync('node scripts/version.js', { cwd: ROOT, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).split('\n')[0];
} catch {
    version = pluginJson.version;
}
// Build a stamped plugin.json for the ZIP (don't modify source file)
const stampedPluginJson = { ...pluginJson, version };
console.log(`Building version ${version} for DWC 3.${gen[1]}`);

// Overridable so the plugin-structure tests can build into a scratch directory
// instead of clobbering a real build in dist/.
const DIST_DIR = process.env.ZIP_OUT_DIR
    ? path.resolve(process.env.ZIP_OUT_DIR)
    : path.join(ROOT, 'dist');
const ZIP_NAME = `${pluginId}-${version}-dwc${gen}.zip`;
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

// plugin.json at root (with computed version)
archive.append(JSON.stringify(stampedPluginJson, null, 2) + '\n', { name: 'plugin.json' });

// dsf/ — Python backend files
const dsfDir = path.join(stageDir, 'dsf');
const dsfFiles = fs.readdirSync(dsfDir).filter(f => f.endsWith('.py'));
for (const file of dsfFiles) {
    archive.file(path.join(dsfDir, file), { name: `dsf/${file}` });
}

// dwc/ — Frontend source files (for DWC's plugin loader)
// In a production build, these would be compiled JS chunks. For CI, we include
// the staged source so the ZIP is a valid plugin structure. Staging is what
// drops the Jest-only stubs and the other generation's UI.
archive.glob('**/*', { cwd: path.join(stageDir, 'src') }, { prefix: 'dwc/src/' });

archive.finalize();
