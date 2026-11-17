#!/usr/bin/env node
/**
 * stage.js — assemble the source tree a DWC builder is handed.
 *
 * One repository produces two plugin packages: a DWC 3.6 one (Vue 2.7 /
 * Vuetify 2.7, webpack) and a DWC 3.7 one (Vue 3.5 / Vuetify 4, Vite). Both
 * builders always compile `<plugin-dir>/src/index.*` and cannot be pointed at
 * a subdirectory, so the generation is picked by staging: this script copies
 * the generation-neutral sources plus exactly one `ui<gen>/` into a temporary
 * tree and writes the one-line entry point into it.
 *
 * That is also why the repository itself has no `src/index.*`: neither
 * generation is "the default" and the raw tree can never be handed to a DWC
 * builder by accident.
 *
 * Usage:
 *   node scripts/stage.js 36|37 [outDir]
 *
 * Prints the staged directory on the last line.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

/** Generations this repository can build. */
const GENERATIONS = ['36', '37'];

/**
 * Files under `src/` that exist only for Jest and must never be staged.
 *
 * DWC provides the real `@/routes` and `@/store` modules at build time; a
 * staged copy would shadow them.
 */
const SRC_EXCLUDES = new Set(['routes.js', 'store.js', '__mocks__']);

/**
 * Build artefacts that must never end up in a package. DWC 3.7's builder lists
 * every file under `dsf/` in the manifest's `dsfFiles`, so a stray `__pycache__`
 * would be shipped and installed on the SBC.
 */
const ARTEFACTS = /^(__pycache__|\.pytest_cache|node_modules|\.DS_Store)$/;

/**
 * The dsf-python release series each package installs into the plugin venv.
 *
 * dsf-python refuses to talk to a DSF whose IPC protocol is older than its own
 * (`ServerInitMessage.is_compatible`): 3.7.x needs protocol 13, DSF 3.6 speaks
 * 12. An unpinned `dsf-python` gets whatever PyPI serves newest, so once 3.7
 * was published every fresh 3.6 install pulled a library that cannot connect —
 * and that also changed the object-model classes our workarounds patch.
 * Each package therefore pins the series matching the DSF it targets.
 */
const DSF_PYTHON = {
    36: 'dsf-python>=3.6.0,<3.7',
    37: 'dsf-python>=3.7.0,<3.8'
};

/**
 * The manifest for one generation: `plugin.json` with the dsf-python
 * dependency pinned to that generation's series.
 *
 * @param {string} gen `36` or `37`
 * @returns {object} Manifest
 */
function stagedManifest(gen) {
    const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'));
    manifest.sbcPythonDependencies = (manifest.sbcPythonDependencies || [])
        .filter(dep => !/^dsf-python\b/.test(dep))
        .concat(DSF_PYTHON[gen]);
    return manifest;
}

/**
 * Copy a directory recursively, skipping build artefacts.
 *
 * @param {string} from Source directory
 * @param {string} to Target directory
 */
function copyDir(from, to) {
    fs.mkdirSync(to, { recursive: true });
    for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
        if (ARTEFACTS.test(entry.name) || entry.name.endsWith('.pyc')) {
            continue;
        }
        const src = path.join(from, entry.name);
        const dst = path.join(to, entry.name);
        if (entry.isDirectory()) {
            copyDir(src, dst);
        } else {
            fs.copyFileSync(src, dst);
        }
    }
}

/**
 * Stage the tree for one DWC generation.
 *
 * @param {string} gen `36` or `37`
 * @param {string} [outDir] Target directory; defaults to a temp directory
 * @returns {string} The staged directory
 */
function stage(gen, outDir) {
    if (!GENERATIONS.includes(gen)) {
        throw new Error(`Unknown generation "${gen}" (expected ${GENERATIONS.join(' or ')})`);
    }

    const target = outDir
        ? path.resolve(outDir)
        : fs.mkdtempSync(path.join(os.tmpdir(), `MeltingplotConfig-dwc${gen}-`));

    fs.rmSync(target, { recursive: true, force: true });
    fs.mkdirSync(target, { recursive: true });

    // Shared, framework-neutral logic
    copyDir(path.join(ROOT, 'src', 'core'), path.join(target, 'src', 'core'));

    // Exactly one UI generation — the other one would not even compile here
    copyDir(path.join(ROOT, 'src', `ui${gen}`), path.join(target, 'src', `ui${gen}`));

    // Anything else directly under src/ that is not a Jest-only stub
    for (const entry of fs.readdirSync(path.join(ROOT, 'src'), { withFileTypes: true })) {
        if (SRC_EXCLUDES.has(entry.name) || entry.name === 'core' || /^ui\d+$/.test(entry.name)) {
            continue;
        }
        const src = path.join(ROOT, 'src', entry.name);
        const dst = path.join(target, 'src', entry.name);
        if (entry.isDirectory()) {
            copyDir(src, dst);
        } else {
            fs.copyFileSync(src, dst);
        }
    }

    // The Python backend goes into both packages unchanged. Both builders read
    // it from the directory they are given, not from the repository.
    copyDir(path.join(ROOT, 'dsf'), path.join(target, 'dsf'));

    fs.writeFileSync(
        path.join(target, 'plugin.json'),
        JSON.stringify(stagedManifest(gen), null, 2) + '\n'
    );

    // Deliberately no package.json: DWC 3.7's builder runs `npm install` inside
    // the plugin directory when one lists dependencies it cannot resolve, and
    // ours pins Vue 2 / Vuetify 2 / Jest for the test suite.
    const ext = gen === '37' ? 'ts' : 'js';
    fs.writeFileSync(
        path.join(target, 'src', `index.${ext}`),
        `// Generated by scripts/stage.js — do not edit.\n` +
        `// Entry point for the DWC 3.${gen[1]} package.\n` +
        `import "./ui${gen}/index";\n`
    );

    return target;
}

module.exports = { stage, stagedManifest, GENERATIONS, DSF_PYTHON };

if (require.main === module) {
    const [gen, outDir] = process.argv.slice(2);
    if (!gen) {
        console.error('Usage: node scripts/stage.js 36|37 [outDir]');
        process.exit(1);
    }
    try {
        console.log(stage(gen, outDir));
    } catch (err) {
        console.error(err.message);
        process.exit(1);
    }
}
