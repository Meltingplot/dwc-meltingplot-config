/**
 * Integration test: Plugin ZIP structure validation.
 *
 * Runs the actual build script and validates that the output ZIP
 * contains exactly the layout DWC expects when installing a plugin.
 */
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { describe, it, expect, beforeAll } from '@jest/globals';

const ROOT = path.resolve(__dirname, '..', '..', '..');
const DIST_DIR = path.join(ROOT, 'dist');

// Complete list of valid SBC permissions from DSF 3.6 SbcPermissions enum.
// Source: DuetSoftwareFramework/src/DuetAPI/Utility/SbcPermissions.cs (v3.6-dev)
const VALID_SBC_PERMISSIONS = new Set([
    'none',
    'commandExecution',
    'codeInterceptionRead',
    'codeInterceptionReadWrite',
    'managePlugins',
    'servicePlugins',
    'manageUserSessions',
    'objectModelRead',
    'objectModelReadWrite',
    'registerHttpEndpoints',
    'readFilaments',
    'writeFilaments',
    'readFirmware',
    'writeFirmware',
    'readGCodes',
    'writeGCodes',
    'readMacros',
    'writeMacros',
    'readMenu',
    'writeMenu',
    'readSystem',
    'writeSystem',
    'readWeb',
    'writeWeb',
    'fileSystemAccess',
    'launchProcesses',
    'networkAccess',
    'webcamAccess',
    'gpioAccess',
    'superUser',
]);

let zipPath;
let zipEntries;

beforeAll(() => {
    // Run the real build script
    execSync('node scripts/build-zip.js', { cwd: ROOT, stdio: 'pipe' });

    // Find the produced ZIP
    const zips = fs.readdirSync(DIST_DIR).filter(f => f.endsWith('.zip'));
    expect(zips.length).toBeGreaterThan(0);
    zipPath = path.join(DIST_DIR, zips[0]);

    // List ZIP entries using unzip -l (available on all CI runners)
    const output = execSync(`unzip -l "${zipPath}"`, { encoding: 'utf8' });
    // Parse entry names from unzip output (lines with dates like 2024-xx-xx)
    zipEntries = output
        .split('\n')
        .filter(line => /\d{4}-\d{2}-\d{2}/.test(line))
        .map(line => line.trim().split(/\s+/).slice(3).join(' '))
        .filter(Boolean);
});

describe('Plugin manifest validation (DWC 3.6 compatibility)', () => {
    let manifest;

    beforeAll(() => {
        manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'));
    });

    it('id is non-empty, max 32 chars, only allowed characters', () => {
        expect(manifest.id).toBeTruthy();
        expect(manifest.id.length).toBeLessThanOrEqual(32);
        expect(manifest.id).toMatch(/^[a-zA-Z0-9 .\-_]+$/);
    });

    it('name is non-empty, max 64 chars, only allowed characters', () => {
        expect(manifest.name).toBeTruthy();
        expect(manifest.name.length).toBeLessThanOrEqual(64);
        expect(manifest.name).toMatch(/^[a-zA-Z0-9 .\-_]+$/);
    });

    it('author is non-empty', () => {
        expect(manifest.author).toBeTruthy();
        expect(manifest.author.trim().length).toBeGreaterThan(0);
    });

    it('version is a valid semver-like string', () => {
        expect(manifest.version).toMatch(/^\d+\.\d+\.\d+/);
    });

    it('every sbcPermission is a valid DSF 3.6 SbcPermission enum value', () => {
        expect(manifest.sbcPermissions).toBeDefined();
        expect(Array.isArray(manifest.sbcPermissions)).toBe(true);

        const invalid = manifest.sbcPermissions.filter(p => !VALID_SBC_PERMISSIONS.has(p));
        expect(invalid).toEqual([]);
    });

    it('dwcVersion is null or a valid version string (not "auto")', () => {
        if (manifest.dwcVersion !== null && manifest.dwcVersion !== undefined) {
            // Must look like a version number, not a word like "auto"
            expect(manifest.dwcVersion).toMatch(/^\d+(\.\d+)*$/);
        }
    });

    it('sbcDsfVersion is null or a valid version string', () => {
        if (manifest.sbcDsfVersion !== null && manifest.sbcDsfVersion !== undefined) {
            expect(manifest.sbcDsfVersion).toMatch(/^\d+(\.\d+)*$/);
        }
    });
});

describe('Plugin ZIP structure', () => {
    it('produces a ZIP named <PluginId>-<version>.zip', () => {
        const pluginJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'));
        const expected = `${pluginJson.id}-${pluginJson.version}.zip`;
        expect(path.basename(zipPath)).toBe(expected);
    });

    it('contains plugin.json at root', () => {
        expect(zipEntries).toContain('plugin.json');
    });

    it('contains dsf/ directory with all Python backend files', () => {
        const dsfDir = path.join(ROOT, 'dsf');
        const expectedPy = fs.readdirSync(dsfDir).filter(f => f.endsWith('.py'));
        expect(expectedPy.length).toBeGreaterThan(0);

        for (const pyFile of expectedPy) {
            expect(zipEntries).toContain(`dsf/${pyFile}`);
        }
    });

    it('contains the main daemon script in dsf/', () => {
        const pluginJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'));
        // sbcExecutableArguments holds the script filename when sbcExecutable is python3
        const script = pluginJson.sbcExecutableArguments || pluginJson.sbcExecutable;
        expect(zipEntries).toContain(`dsf/${script}`);
    });

    it('contains dwc/src/ directory with frontend sources', () => {
        const dwcEntries = zipEntries.filter(e => e.startsWith('dwc/src/'));
        expect(dwcEntries.length).toBeGreaterThan(0);
    });

    it('includes all .vue component files in the ZIP', () => {
        const expectedVue = ['MeltingplotConfig.vue', 'ConfigStatus.vue', 'ConfigDiff.vue', 'BackupHistory.vue'];
        for (const vue of expectedVue) {
            const found = zipEntries.some(e => e.endsWith(vue));
            expect(found).toBe(true);
        }
    });

    it('includes index.js entry point', () => {
        const found = zipEntries.some(e => e.endsWith('index.js'));
        expect(found).toBe(true);
    });

    it('plugin.json inside ZIP is valid JSON with required fields', () => {
        // Extract plugin.json from ZIP and validate
        const extracted = execSync(`unzip -p "${zipPath}" plugin.json`, { encoding: 'utf8' });
        const manifest = JSON.parse(extracted);

        expect(manifest.id).toBe('MeltingplotConfig');
        expect(manifest.name).toBeTruthy();
        expect(manifest.version).toMatch(/^\d+\.\d+\.\d+/);
        expect(manifest.sbcRequired).toBe(true);
        expect(manifest.sbcExecutable).toBeTruthy();
        expect(manifest.sbcPermissions).toContain('registerHttpEndpoints');
        expect(manifest.sbcPermissions).toContain('fileSystemAccess');
        expect(manifest.sbcPermissions).toContain('networkAccess');
    });

    it('does not contain test files, node_modules, or git metadata', () => {
        const forbidden = zipEntries.filter(e =>
            e.includes('node_modules/') ||
            e.includes('tests/') ||
            e.includes('.git/') ||
            e.includes('__pycache__/') ||
            e.endsWith('.test.js')
        );
        expect(forbidden).toEqual([]);
    });

    it('does not contain test stubs (routes.js, __mocks__)', () => {
        const stubs = zipEntries.filter(e =>
            e.includes('__mocks__') ||
            e.endsWith('routes.js')
        );
        expect(stubs).toEqual([]);
    });
});
