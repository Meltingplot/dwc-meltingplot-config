#!/usr/bin/env node
/**
 * Compute the plugin version from git tags and commit count.
 *
 * Version scheme:
 *   - HEAD is exactly on a tag `vX.Y.Z`  →  "X.Y.Z"
 *   - N commits past tag `vX.Y.Z`        →  "X.Y.Z-dev.N"
 *   - No version tags exist               →  "<base>-dev.<total-commits>"
 *
 * The base version (used when no tags exist) is read from plugin.json.
 *
 * Usage:
 *   node scripts/version.js          # prints computed version
 *   node scripts/version.js --write  # also updates plugin.json + package.json
 */

'use strict';

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

function git(cmd) {
    return execSync(cmd, { cwd: ROOT, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
}

function computeVersion() {
    // Read the base version from plugin.json (used as fallback when no tags exist)
    const pluginJson = JSON.parse(
        fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8')
    );
    const baseVersion = pluginJson.version.replace(/-dev\.\d+$/, '');

    // Check if we're in a git repo with commits
    let commitCount;
    try {
        commitCount = parseInt(git('git rev-list --count HEAD'), 10);
    } catch {
        // Not a git repo or no commits — use base version as-is
        return baseVersion;
    }

    // Try to describe HEAD relative to the latest vX.Y.Z tag
    try {
        const describe = git('git describe --tags --match "v[0-9]*" --long');
        // Format: v0.2.0-3-gabcdef  →  tag=v0.2.0, ahead=3, hash=gabcdef
        const match = describe.match(/^v(.+)-(\d+)-g[0-9a-f]+$/);
        if (match) {
            const tagVersion = match[1];
            const ahead = parseInt(match[2], 10);
            if (ahead === 0) {
                // HEAD is exactly on the tag
                return tagVersion;
            }
            return `${tagVersion}-dev.${ahead}`;
        }
    } catch {
        // No matching tags found — fall through to commit-count fallback
    }

    // No version tags at all: use base version + total commit count
    return `${baseVersion}-dev.${commitCount}`;
}

function writeVersion(version) {
    // Update plugin.json
    const pluginPath = path.join(ROOT, 'plugin.json');
    const pluginJson = JSON.parse(fs.readFileSync(pluginPath, 'utf8'));
    pluginJson.version = version;
    fs.writeFileSync(pluginPath, JSON.stringify(pluginJson, null, 2) + '\n');

    // Update package.json
    const packagePath = path.join(ROOT, 'package.json');
    const packageJson = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
    packageJson.version = version;
    fs.writeFileSync(packagePath, JSON.stringify(packageJson, null, 2) + '\n');
}

const version = computeVersion();
console.log(version);

if (process.argv.includes('--write')) {
    writeVersion(version);
    console.log(`Updated plugin.json and package.json to ${version}`);
}
