import { execSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { describe, it, expect, beforeAll } from '@jest/globals'

const ROOT = path.resolve(__dirname, '..', '..', '..')
// Its own scratch directory: wiping dist/ would delete a real build
const DIST_DIR = path.join(ROOT, '.build', 'structure-zips')

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
])

/** Both packages this repository produces, from the same source tree. */
const GENERATIONS = ['36', '37']

/** Entry-point extension per generation — the 3.7 UI is TypeScript. */
const ENTRY_EXT = { 36: 'js', 37: 'ts' }

/** gen -> { zipPath, zipEntries } */
const packages = {}

/**
 * Every .vue file of one generation's UI, relative to src/ui<gen>.
 *
 * Derived from the tree rather than hard-coded so the expectation keeps up as
 * the 3.7 UI grows.
 */
function vueFilesOf(gen) {
  const base = path.join(ROOT, 'src', `ui${gen}`)
  const found = []
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(full)
      } else if (entry.name.endsWith('.vue')) {
        found.push(path.relative(base, full))
      }
    }
  }
  walk(base)
  return found
}

beforeAll(() => {
  fs.rmSync(DIST_DIR, { recursive: true, force: true })

  for (const gen of GENERATIONS) {
    execSync(`node scripts/build-zip.js ${gen}`, {
      cwd: ROOT,
      stdio: 'pipe',
      env: { ...process.env, ZIP_OUT_DIR: DIST_DIR }
    })

    const zips = fs.readdirSync(DIST_DIR).filter(f => f.endsWith(`-dwc${gen}.zip`))
    expect(zips).toHaveLength(1)
    const zipPath = path.join(DIST_DIR, zips[0])

    const output = execSync(`unzip -l "${zipPath}"`, { encoding: 'utf8' })
    const zipEntries = output
      .split('\n')
      .filter(line => /\d{4}-\d{2}-\d{2}/.test(line))
      .map(line => line.trim().split(/\s+/).slice(3).join(' '))
      .filter(Boolean)

    packages[gen] = { zipPath, zipEntries }
  }
})

describe('Plugin manifest validation (DWC 3.6 compatibility)', () => {
  let manifest

  beforeAll(() => {
    manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'))
  })

  it('id is non-empty, max 32 chars, only allowed characters', () => {
    expect(manifest.id).toBeTruthy()
    expect(manifest.id.length).toBeLessThanOrEqual(32)
    expect(manifest.id).toMatch(/^[a-zA-Z0-9 .\-_]+$/)
  })

  it('name is non-empty, max 64 chars, only allowed characters', () => {
    expect(manifest.name).toBeTruthy()
    expect(manifest.name.length).toBeLessThanOrEqual(64)
    expect(manifest.name).toMatch(/^[a-zA-Z0-9 .\-_]+$/)
  })

  it('author is non-empty', () => {
    expect(manifest.author).toBeTruthy()
    expect(manifest.author.trim().length).toBeGreaterThan(0)
  })

  it('version is a valid semver-like string', () => {
    expect(manifest.version).toMatch(/^\d+\.\d+\.\d+/)
  })

  it('every sbcPermission is a valid DSF 3.6 SbcPermission enum value', () => {
    expect(manifest.sbcPermissions).toBeDefined()
    expect(Array.isArray(manifest.sbcPermissions)).toBe(true)

    const invalid = manifest.sbcPermissions.filter(p => !VALID_SBC_PERMISSIONS.has(p))
    expect(invalid).toEqual([])
  })

  it('dwcVersion is null, a valid version string, or "auto-major"', () => {
    if (manifest.dwcVersion !== null && manifest.dwcVersion !== undefined) {
      expect(manifest.dwcVersion).toMatch(/^(\d+(\.\d+)*|auto-major)$/)
    }
  })

  it('sbcDsfVersion is null, a valid version string, or "auto-major"', () => {
    if (manifest.sbcDsfVersion !== null && manifest.sbcDsfVersion !== undefined) {
      expect(manifest.sbcDsfVersion).toMatch(/^(\d+(\.\d+)*|auto-major)$/)
    }
  })
})

describe.each(GENERATIONS)('Plugin ZIP structure (DWC 3.%s)', (gen) => {
  let zipPath
  let zipEntries

  beforeAll(() => {
    ({ zipPath, zipEntries } = packages[gen])
  })

  it('is named <PluginId>-<version>-dwc<gen>.zip', () => {
    const pluginJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'))
    // version.js may append -dev.N so match the prefix + semver pattern
    expect(path.basename(zipPath)).toMatch(
      new RegExp(`^${pluginJson.id}-\\d+\\.\\d+\\.\\d+(-dev\\.\\d+)?-dwc${gen}\\.zip$`)
    )
  })

  it('contains plugin.json at root', () => {
    expect(zipEntries).toContain('plugin.json')
  })

  it('contains dsf/ directory with all Python backend files', () => {
    const dsfDir = path.join(ROOT, 'dsf')
    const expectedPy = fs.readdirSync(dsfDir).filter(f => f.endsWith('.py'))
    expect(expectedPy.length).toBeGreaterThan(0)

    for (const pyFile of expectedPy) {
      expect(zipEntries).toContain(`dsf/${pyFile}`)
    }
  })

  it('contains the main daemon executable in dsf/', () => {
    const pluginJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'plugin.json'), 'utf8'))
    expect(zipEntries).toContain(`dsf/${pluginJson.sbcExecutable}`)
  })

  it('contains dwc/src/ directory with frontend sources', () => {
    const dwcEntries = zipEntries.filter(e => e.startsWith('dwc/src/'))
    expect(dwcEntries.length).toBeGreaterThan(0)
  })

  it('contains the shared core', () => {
    expect(zipEntries).toContain('dwc/src/core/useConfigPage.js')
    expect(zipEntries).toContain('dwc/src/core/host.js')
  })

  it('includes every .vue file of this generation', () => {
    for (const vue of vueFilesOf(gen)) {
      expect(zipEntries).toContain(`dwc/src/ui${gen}/${vue.split(path.sep).join('/')}`)
    }
  })

  it('includes the generated entry point', () => {
    expect(zipEntries).toContain(`dwc/src/index.${ENTRY_EXT[gen]}`)
  })

  it('does not carry the other generation\'s UI', () => {
    const other = GENERATIONS.find(g => g !== gen)
    expect(zipEntries.filter(e => e.includes(`ui${other}/`))).toEqual([])
  })

  it('plugin.json inside ZIP is valid JSON with required fields', () => {
    const extracted = execSync(`unzip -p "${zipPath}" plugin.json`, { encoding: 'utf8' })
    const manifest = JSON.parse(extracted)

    expect(manifest.id).toBe('MeltingplotConfig')
    expect(manifest.name).toBeTruthy()
    expect(manifest.version).toMatch(/^\d+\.\d+\.\d+/)
    expect(manifest.sbcRequired).toBe(true)
    expect(manifest.sbcExecutable).toBeTruthy()
    expect(manifest.sbcPermissions).toContain('registerHttpEndpoints')
    expect(manifest.sbcPermissions).toContain('fileSystemAccess')
    expect(manifest.sbcPermissions).toContain('networkAccess')
  })

  it('does not contain test files, node_modules, or git metadata', () => {
    const forbidden = zipEntries.filter(e =>
      e.includes('node_modules/') ||
      e.includes('tests/') ||
      e.includes('.git/') ||
      e.includes('__pycache__/') ||
      e.endsWith('.pyc') ||
      e.endsWith('.test.js')
    )
    expect(forbidden).toEqual([])
  })

  it('does not contain test stubs (routes.js, store.js, __mocks__)', () => {
    const stubs = zipEntries.filter(e =>
      e.includes('__mocks__') ||
      e.endsWith('routes.js') ||
      e.endsWith('store.js')
    )
    expect(stubs).toEqual([])
  })

  it('does not contain a package.json, which would make DWC 3.7 npm install our Vue 2 deps', () => {
    expect(zipEntries.filter(e => e.endsWith('package.json'))).toEqual([])
  })
})
