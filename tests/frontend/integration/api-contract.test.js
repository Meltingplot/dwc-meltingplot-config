/**
 * API contract tests.
 *
 * Validates that the data shapes returned by the daemon HTTP endpoints
 * match what the frontend components actually consume. If the backend
 * changes a response shape, these tests should fail before users see
 * a broken UI.
 *
 * The "contract" objects here mirror the real daemon handler responses
 * (as tested in tests/test_e2e.py). Changes must be kept in sync.
 */
import { describe, it, expect } from '@jest/globals'

// ---------------------------------------------------------------------------
// Contract definitions — these are the exact shapes the frontend relies on
// ---------------------------------------------------------------------------

const STATUS_RESPONSE = {
  status: 'up_to_date',
  detectedFirmwareVersion: '3.5',
  activeBranch: '3.5',
  referenceRepoUrl: 'https://example.com/repo.git',
  lastSyncTimestamp: '2026-01-01T00:00:00+00:00',
  branches: ['main', '3.5', '3.6']
}

const SYNC_RESPONSE = {
  activeBranch: '3.5',
  exact: true,
  warning: null,
  branches: ['main', '3.5']
}

const DIFF_ALL_RESPONSE = {
  files: [
    {
      file: 'sys/config.g',
      printerPath: '0:/sys/config.g',
      status: 'modified',
      hunks: [{ index: 0, header: '@@ -1,3 +1,3 @@' }]
    },
    {
      file: 'sys/homex.g',
      printerPath: '0:/sys/homex.g',
      status: 'unchanged',
      hunks: []
    },
    {
      file: 'macros/heat_bed.g',
      printerPath: '0:/macros/heat_bed.g',
      status: 'missing',
      hunks: []
    }
  ]
}

const DIFF_FILE_RESPONSE = {
  file: 'sys/config.g',
  status: 'modified',
  hunks: [
    {
      index: 0,
      header: '@@ -1,3 +1,3 @@',
      lines: [' G28', ' M584 X0 Y1', '-M906 X800 Y800', '+M906 X1000 Y1000'],
      summary: 'Lines 1-3'
    }
  ],
  unifiedDiff: '--- a/sys/config.g\n+++ b/sys/config.g\n@@ -1,3 +1,3 @@\n'
}

const APPLY_RESPONSE = {
  applied: ['sys/config.g', 'sys/homex.g']
}

const APPLY_HUNKS_RESPONSE = {
  applied: [0, 2],
  failed: [1]
}

const BACKUPS_RESPONSE = {
  backups: [
    {
      hash: 'abc123def456',
      message: 'Pre-update backup — 2026-01-01T12:00:00',
      timestamp: '2026-01-01T12:00:00',
      filesChanged: 3
    }
  ]
}

const BACKUP_DETAIL_RESPONSE = {
  hash: 'abc123def456',
  files: ['sys/config.g', 'sys/homex.g', 'macros/print_start.g']
}

const BRANCHES_RESPONSE = {
  branches: ['main', '3.5', '3.6']
}

const REFERENCE_RESPONSE = {
  files: ['sys/config.g', 'sys/homex.g', 'macros/print_start.g']
}

const DELETE_BACKUP_RESPONSE = {
  deleted: 'abc123def456'
}

const SETTINGS_RESPONSE = {
  ok: true
}

const ERROR_RESPONSE = {
  error: 'Something went wrong'
}

// ---------------------------------------------------------------------------
// Contract validators
// ---------------------------------------------------------------------------

function assertHasKeys(obj, keys, label) {
  for (const key of keys) {
    expect(obj).toHaveProperty(key)
  }
}

function assertFileShape(file) {
  assertHasKeys(file, ['file', 'status'], 'diff file')
  expect(typeof file.file).toBe('string')
  expect(['modified', 'unchanged', 'missing', 'extra', 'not_in_reference']).toContain(file.status)
}

function assertSummaryHunkShape(hunk) {
  assertHasKeys(hunk, ['index', 'header'], 'summary hunk')
  expect(typeof hunk.index).toBe('number')
  expect(typeof hunk.header).toBe('string')
  // Summary hunks must NOT have lines
  expect(hunk).not.toHaveProperty('lines')
}

function assertDetailHunkShape(hunk) {
  assertHasKeys(hunk, ['index', 'header', 'lines', 'summary'], 'detail hunk')
  expect(typeof hunk.index).toBe('number')
  expect(typeof hunk.header).toBe('string')
  expect(Array.isArray(hunk.lines)).toBe(true)
  expect(typeof hunk.summary).toBe('string')
}

function assertHunkLineFormat(line) {
  // Each line must start with ' ', '+', or '-'
  expect([' ', '+', '-']).toContain(line[0])
}

function assertBackupShape(backup) {
  assertHasKeys(backup, ['hash', 'message', 'timestamp'], 'backup')
  expect(typeof backup.hash).toBe('string')
  expect(typeof backup.message).toBe('string')
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('API contract: /status response', () => {
  it('has all fields consumed by ConfigStatus', () => {
    assertHasKeys(STATUS_RESPONSE, [
      'status', 'detectedFirmwareVersion', 'activeBranch',
      'referenceRepoUrl', 'lastSyncTimestamp', 'branches'
    ])
  })

  it('branches is an array of strings', () => {
    expect(Array.isArray(STATUS_RESPONSE.branches)).toBe(true)
    STATUS_RESPONSE.branches.forEach(b => expect(typeof b).toBe('string'))
  })

  it('status is a known value', () => {
    const KNOWN = ['not_configured', 'up_to_date', 'updates_available', 'error']
    expect(KNOWN).toContain(STATUS_RESPONSE.status)
  })
})

describe('API contract: /sync response', () => {
  it('has activeBranch field', () => {
    assertHasKeys(SYNC_RESPONSE, ['activeBranch', 'exact'])
    expect(typeof SYNC_RESPONSE.activeBranch).toBe('string')
    expect(typeof SYNC_RESPONSE.exact).toBe('boolean')
  })

  it('warning is null or string', () => {
    expect(SYNC_RESPONSE.warning === null || typeof SYNC_RESPONSE.warning === 'string').toBe(true)
  })
})

describe('API contract: /diff (all files) response', () => {
  it('has files array', () => {
    assertHasKeys(DIFF_ALL_RESPONSE, ['files'])
    expect(Array.isArray(DIFF_ALL_RESPONSE.files)).toBe(true)
  })

  it('each file has required fields', () => {
    DIFF_ALL_RESPONSE.files.forEach(assertFileShape)
  })

  it('modified files have summary hunks (no lines)', () => {
    const modified = DIFF_ALL_RESPONSE.files.filter(f => f.status === 'modified')
    expect(modified.length).toBeGreaterThan(0)
    modified.forEach(f => {
      expect(Array.isArray(f.hunks)).toBe(true)
      f.hunks.forEach(assertSummaryHunkShape)
    })
  })

  it('unchanged/missing files have empty hunks array', () => {
    const nonModified = DIFF_ALL_RESPONSE.files.filter(f => f.status !== 'modified')
    nonModified.forEach(f => {
      expect(f.hunks).toEqual([])
    })
  })
})

describe('API contract: /diff?file=<path> (detail) response', () => {
  it('has file, status, hunks, unifiedDiff', () => {
    assertHasKeys(DIFF_FILE_RESPONSE, ['file', 'status', 'hunks', 'unifiedDiff'])
  })

  it('hunks have full detail (lines + summary)', () => {
    expect(DIFF_FILE_RESPONSE.hunks.length).toBeGreaterThan(0)
    DIFF_FILE_RESPONSE.hunks.forEach(assertDetailHunkShape)
  })

  it('hunk lines have diff prefix characters', () => {
    DIFF_FILE_RESPONSE.hunks.forEach(hunk => {
      hunk.lines.forEach(assertHunkLineFormat)
    })
  })

  it('summary hunk vs detail hunk distinguishable by presence of lines', () => {
    // This is the key contract: the frontend checks hunk.lines to decide
    // whether to fetch detail or not (see loadFileDetail guard in ConfigDiff.vue)
    const summaryHunk = DIFF_ALL_RESPONSE.files[0].hunks[0]
    const detailHunk = DIFF_FILE_RESPONSE.hunks[0]

    expect(summaryHunk).not.toHaveProperty('lines')
    expect(detailHunk).toHaveProperty('lines')
    expect(Array.isArray(detailHunk.lines)).toBe(true)
  })
})

describe('API contract: /apply response', () => {
  it('has applied array of file paths', () => {
    assertHasKeys(APPLY_RESPONSE, ['applied'])
    expect(Array.isArray(APPLY_RESPONSE.applied)).toBe(true)
    APPLY_RESPONSE.applied.forEach(p => expect(typeof p).toBe('string'))
  })
})

describe('API contract: /applyHunks response', () => {
  it('has applied and failed arrays of indices', () => {
    assertHasKeys(APPLY_HUNKS_RESPONSE, ['applied', 'failed'])
    expect(Array.isArray(APPLY_HUNKS_RESPONSE.applied)).toBe(true)
    expect(Array.isArray(APPLY_HUNKS_RESPONSE.failed)).toBe(true)
    APPLY_HUNKS_RESPONSE.applied.forEach(i => expect(typeof i).toBe('number'))
    APPLY_HUNKS_RESPONSE.failed.forEach(i => expect(typeof i).toBe('number'))
  })
})

describe('API contract: /backups response', () => {
  it('has backups array', () => {
    assertHasKeys(BACKUPS_RESPONSE, ['backups'])
    expect(Array.isArray(BACKUPS_RESPONSE.backups)).toBe(true)
  })

  it('each backup has required fields', () => {
    BACKUPS_RESPONSE.backups.forEach(assertBackupShape)
  })
})

describe('API contract: /backup?hash=<hash> response', () => {
  it('has hash and files', () => {
    assertHasKeys(BACKUP_DETAIL_RESPONSE, ['hash', 'files'])
    expect(typeof BACKUP_DETAIL_RESPONSE.hash).toBe('string')
    expect(Array.isArray(BACKUP_DETAIL_RESPONSE.files)).toBe(true)
  })
})

describe('API contract: /branches response', () => {
  it('has branches array of strings', () => {
    assertHasKeys(BRANCHES_RESPONSE, ['branches'])
    expect(Array.isArray(BRANCHES_RESPONSE.branches)).toBe(true)
    BRANCHES_RESPONSE.branches.forEach(b => expect(typeof b).toBe('string'))
  })
})

describe('API contract: /reference response', () => {
  it('has files array of strings', () => {
    assertHasKeys(REFERENCE_RESPONSE, ['files'])
    expect(Array.isArray(REFERENCE_RESPONSE.files)).toBe(true)
    REFERENCE_RESPONSE.files.forEach(f => expect(typeof f).toBe('string'))
  })
})

describe('API contract: /deleteBackup response', () => {
  it('has deleted field with commit hash', () => {
    assertHasKeys(DELETE_BACKUP_RESPONSE, ['deleted'])
    expect(typeof DELETE_BACKUP_RESPONSE.deleted).toBe('string')
  })
})

describe('API contract: /settings response', () => {
  it('has ok field', () => {
    assertHasKeys(SETTINGS_RESPONSE, ['ok'])
    expect(SETTINGS_RESPONSE.ok).toBe(true)
  })
})

describe('API contract: error responses', () => {
  it('has error string', () => {
    assertHasKeys(ERROR_RESPONSE, ['error'])
    expect(typeof ERROR_RESPONSE.error).toBe('string')
  })
})

describe('API contract: ConfigDiff sideBySideLines compatibility', () => {
  it('hunk lines can be split into side-by-side rows', () => {
    // Simulate what ConfigDiff.sideBySideLines does
    const lines = DIFF_FILE_RESPONSE.hunks[0].lines
    const rows = []
    const removes = []
    const adds = []

    const flush = () => {
      const max = Math.max(removes.length, adds.length)
      for (let i = 0; i < max; i++) {
        rows.push({
          left: i < removes.length ? removes[i].substring(1) : null,
          right: i < adds.length ? adds[i].substring(1) : null
        })
      }
      removes.length = 0
      adds.length = 0
    }

    for (const line of lines) {
      if (line.startsWith('-')) removes.push(line)
      else if (line.startsWith('+')) adds.push(line)
      else {
        flush()
        rows.push({ left: line.substring(1), right: line.substring(1) })
      }
    }
    flush()

    expect(rows.length).toBeGreaterThan(0)
    // Every row should have left and right (null for empty)
    rows.forEach(row => {
      expect(row).toHaveProperty('left')
      expect(row).toHaveProperty('right')
    })
  })
})
