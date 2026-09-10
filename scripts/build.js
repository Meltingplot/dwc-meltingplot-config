#!/usr/bin/env node
/**
 * build.js — build one plugin package from a local DuetWebControl checkout.
 *
 * Usage:
 *   DWC36_DIR=~/src/DuetWebControl-3.6 node scripts/build.js 36
 *   DWC37_DIR=~/src/DuetWebControl-3.7 node scripts/build.js 37
 *
 * The checkout must be the matching branch with `npm install` already done
 * (`v3.6-dev` for 36, `v3.7-dev` for 37; the 3.7 toolchain needs Node 22+).
 *
 * Both legs use `build-plugin-pkg`, not `build-plugin`: DWC 3.7's loader takes
 * the JS/CSS list from `manifest.dwcFiles`, which only the `-pkg` script fills
 * in. Without it 3.7 registers the plugin as SBC-only and never loads the page.
 *
 * Output: dist/MeltingplotConfig-<version>-dwc<gen>.zip
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const { stage } = require('./stage');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'dist');
const PLUGIN_ID = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8')).id;

/** Per-generation build settings. */
const LEGS = {
    36: { env: 'DWC36_DIR', branch: 'v3.6-dev' },
    37: { env: 'DWC37_DIR', branch: 'v3.7-dev' }
};

/**
 * Run a command, inheriting stdio, and fail the build if it does.
 *
 * @param {string} command Executable
 * @param {Array<string>} args Arguments
 * @param {string} cwd Working directory
 */
function run(command, args, cwd) {
    const result = spawnSync(command, args, { cwd, stdio: 'inherit', shell: process.platform === 'win32' });
    if (result.status !== 0) {
        throw new Error(`${command} ${args.join(' ')} failed with status ${result.status}`);
    }
}

/**
 * The ZIPs a build produced, newest first, with sourcemap archives dropped.
 *
 * `-srcmap.zip` sorts before the real ZIP ('-' < '.'), so anything that just
 * takes the first match would ship the sourcemaps as the release asset.
 *
 * @param {string} dir Directory to scan
 * @returns {Array<string>} Absolute paths
 */
function findZips(dir) {
    if (!fs.existsSync(dir)) {
        return [];
    }
    return fs.readdirSync(dir)
        .filter(name => name.startsWith(`${PLUGIN_ID}-`) && name.endsWith('.zip') && !name.endsWith('-srcmap.zip'))
        .map(name => path.join(dir, name))
        .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
}

/**
 * Stage and build one generation.
 *
 * @param {string} gen `36` or `37`
 * @returns {string} Path of the packaged ZIP
 */
function build(gen) {
    const leg = LEGS[gen];
    if (!leg) {
        throw new Error(`Unknown generation "${gen}" (expected 36 or 37)`);
    }

    const dwcDir = process.env[leg.env];
    if (!dwcDir) {
        throw new Error(`${leg.env} is not set — point it at a ${leg.branch} checkout with npm install done`);
    }
    if (!fs.existsSync(path.join(dwcDir, 'scripts', 'build-plugin-pkg.js'))) {
        throw new Error(`${leg.env}="${dwcDir}" does not look like a DuetWebControl checkout`);
    }

    const stageDir = stage(gen, path.join(ROOT, '.build', `dwc${gen}`));
    console.log(`Staged DWC 3.${gen[1]} sources in ${stageDir}`);

    let zipSource;
    if (gen === '36') {
        // The 3.6 builder copies the plugin into src/plugins/<id> inside the
        // checkout. An interrupted run leaves a stale copy that gets compiled
        // again on the next build, so clear it out first.
        fs.rmSync(path.join(dwcDir, 'src', 'plugins', PLUGIN_ID), { recursive: true, force: true });
        run('npm', ['run', 'build-plugin-pkg', '--', stageDir], dwcDir);
        zipSource = path.join(dwcDir, 'dist');
    } else {
        // The 3.7 builder writes the ZIP next to the plugin directory.
        run('node', [path.join(dwcDir, 'scripts', 'build-plugin-pkg.js'), stageDir], dwcDir);
        zipSource = stageDir;
    }

    const [built] = findZips(zipSource);
    if (!built) {
        throw new Error(`No plugin ZIP found in ${zipSource}`);
    }

    fs.mkdirSync(DIST, { recursive: true });
    const version = path.basename(built).replace(`${PLUGIN_ID}-`, '').replace(/\.zip$/, '');
    const target = path.join(DIST, `${PLUGIN_ID}-${version}-dwc${gen}.zip`);
    fs.copyFileSync(built, target);
    console.log(`\nBuilt ${path.relative(ROOT, target)}`);
    return target;
}

module.exports = { build };

if (require.main === module) {
    const gen = process.argv[2];
    if (!gen) {
        console.error('Usage: node scripts/build.js 36|37');
        process.exit(1);
    }
    try {
        build(gen);
    } catch (err) {
        console.error(err.message);
        process.exit(1);
    }
}
