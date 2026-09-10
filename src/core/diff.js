'use strict'

/**
 * Pure diff helpers shared by both DWC generations.
 *
 * Nothing in here touches Vue, DWC or the network — every function is a plain
 * transformation and is unit-tested as such.
 *
 * Reactivity rule (see the dual-build plan, §4): the `normalize*` functions
 * initialise **every** field an entry will ever carry. Vue 2.7 cannot observe
 * properties added later, so entries must be normalised before they are handed
 * to reactive state, and nothing may add a field to them afterwards.
 */

/** Colour and icon per file status reported by `GET /diff`. */
export const FILE_STATUS = {
  modified: { color: 'warning', icon: 'mdi-file-document-edit' },
  missing: { color: 'info', icon: 'mdi-file-plus' },
  extra: { color: 'grey', icon: 'mdi-file-question' }
}

/** Colour per per-file status reported by the backup diff endpoints. */
export const DIFF_STATUS_COLORS = {
  modified: 'warning',
  added: 'success',
  deleted: 'error',
  unchanged: 'grey',
  unknown: 'grey'
}

/**
 * @param {string} status File status
 * @returns {string} Vuetify colour name
 */
export function fileStatusColor(status) {
  return (FILE_STATUS[status] || FILE_STATUS.modified).color
}

/**
 * @param {string} status File status
 * @returns {string} Material Design icon name
 */
export function fileStatusIcon(status) {
  return (FILE_STATUS[status] || FILE_STATUS.modified).icon
}

/**
 * @param {string} status Backup file diff status
 * @returns {string} Vuetify colour name
 */
export function diffStatusColor(status) {
  return DIFF_STATUS_COLORS[status] || 'grey'
}

/**
 * Parse a unified-diff hunk header.
 *
 * @param {string} header e.g. `@@ -12,4 +12,6 @@`
 * @returns {{oldStart: number, oldCount: number, newStart: number, newCount: number}|null}
 */
export function parseHunkHeader(header) {
  if (!header) return null
  const m = header.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/)
  if (!m) return null
  return {
    oldStart: parseInt(m[1]),
    oldCount: m[2] !== undefined ? parseInt(m[2]) : 1,
    newStart: parseInt(m[3]),
    newCount: m[4] !== undefined ? parseInt(m[4]) : 1
  }
}

/**
 * How many unchanged lines the diff skipped before a hunk.
 *
 * @param {object} file File entry with a `hunks` array
 * @param {number} hunkIdx Index into `file.hunks`
 * @returns {number} Number of hidden lines (0 when unknown)
 */
export function skippedLinesBetween(file, hunkIdx) {
  const curr = parseHunkHeader(file.hunks[hunkIdx].header)
  if (!curr) return 0
  if (hunkIdx === 0) {
    return curr.oldStart > 1 ? curr.oldStart - 1 : 0
  }
  const prev = parseHunkHeader(file.hunks[hunkIdx - 1].header)
  if (!prev) return 0
  return curr.oldStart - (prev.oldStart + prev.oldCount)
}

/**
 * Turn a hunk's unified-diff lines into side-by-side table rows.
 *
 * Consecutive `-`/`+` runs are paired into left/right columns; context lines
 * appear on both sides. An unbalanced run leaves empty cells (`null` value,
 * `diff-empty` class).
 *
 * @param {object} hunk Detail hunk with a `lines` array
 * @returns {Array<object>} Rows with left/right text, line numbers and classes
 */
export function sideBySideLines(hunk) {
  if (!hunk.lines) return []
  const parsed = parseHunkHeader(hunk.header)
  let leftLine = parsed ? parsed.oldStart : 1
  let rightLine = parsed ? parsed.newStart : 1

  const rows = []
  const removes = []
  const adds = []

  const flushPairs = () => {
    const max = Math.max(removes.length, adds.length)
    for (let i = 0; i < max; i++) {
      rows.push({
        leftLine: i < removes.length ? leftLine + i : null,
        left: i < removes.length ? removes[i].substring(1) : null,
        leftClass: i < removes.length ? 'diff-remove' : 'diff-empty',
        rightLine: i < adds.length ? rightLine + i : null,
        right: i < adds.length ? adds[i].substring(1) : null,
        rightClass: i < adds.length ? 'diff-add' : 'diff-empty'
      })
    }
    leftLine += removes.length
    rightLine += adds.length
    removes.length = 0
    adds.length = 0
  }

  for (const line of hunk.lines) {
    if (line.startsWith('-')) {
      removes.push(line)
    } else if (line.startsWith('+')) {
      adds.push(line)
    } else {
      flushPairs()
      const text = line.startsWith(' ') ? line.substring(1) : line
      rows.push({
        leftLine: leftLine,
        left: text,
        leftClass: 'diff-context',
        rightLine: rightLine,
        right: text,
        rightClass: 'diff-context'
      })
      leftLine++
      rightLine++
    }
  }
  flushPairs()
  return rows
}

/**
 * Give a hunk its `selected` flag up front.
 *
 * @param {object} hunk Summary or detail hunk from the daemon
 * @param {boolean} [selected] Initial selection state
 * @returns {object} A copy carrying `selected`
 */
export function normalizeHunk(hunk, selected = true) {
  return { ...hunk, selected: hunk.selected === undefined ? selected : hunk.selected }
}

/**
 * Give a diff file entry every field the UI will ever set on it.
 *
 * Call this on the entries coming out of `GET /diff` **before** they reach
 * reactive state. Existing fields are kept, so calling it twice is harmless.
 *
 * @param {object} file File entry from the daemon
 * @returns {object} Normalised copy
 */
export function normalizeFile(file) {
  const selected = file.selected === undefined ? true : file.selected
  return {
    ...file,
    selected,
    loadingDetail: file.loadingDetail === undefined ? false : file.loadingDetail,
    hunks: file.hunks ? file.hunks.map(h => normalizeHunk(h, selected)) : null
  }
}

/**
 * Whether a file entry carries full hunk detail.
 *
 * `GET /diff` returns summary hunks (`index` + `header` only); only the
 * per-file detail response carries `lines` and therefore usable per-hunk
 * checkboxes. A file whose panel was never expanded always applies as a whole.
 *
 * @param {object} file File entry
 * @returns {boolean} true when per-hunk selection is possible
 */
export function hasHunkDetail(file) {
  return !!(file.hunks && file.hunks.length > 0 && file.hunks[0].lines)
}

/**
 * @param {object} file File entry
 * @returns {number} Number of selected hunks
 */
export function selectedHunkCount(file) {
  if (!file.hunks) return 0
  return file.hunks.filter(h => h.selected).length
}

/**
 * Whether the file's checkbox reads as checked.
 *
 * Deselecting every hunk drops the file just like unchecking it.
 *
 * @param {object} file File entry
 * @returns {boolean} Checkbox state
 */
export function fileChecked(file) {
  if (file.selected === false) return false
  if (file.status === 'modified' && hasHunkDetail(file)) {
    return file.hunks.some(h => h.selected)
  }
  return true
}

/**
 * Whether the file's checkbox reads as indeterminate.
 *
 * @param {object} file File entry
 * @returns {boolean} true when only some hunks are selected
 */
export function fileIsPartial(file) {
  if (file.selected === false) return false
  if (file.status !== 'modified' || !hasHunkDetail(file)) return false
  const count = selectedHunkCount(file)
  return count > 0 && count < file.hunks.length
}

/**
 * Turn the per-file and per-hunk checkboxes into a `POST /applySelection` payload.
 *
 * - `files`: payload entries — a bare `{ file }` applies the whole file,
 *   `{ file, hunks }` applies only those hunk indices
 * - `excludedFiles`: files the user dropped completely
 * - `partialFiles`: files where only some hunks are selected
 *
 * @param {Array<object>} changedFiles Files with a status other than `unchanged`
 * @returns {{files: Array<object>, excludedFiles: number, partialFiles: number}}
 */
export function computeSelection(changedFiles) {
  const files = []
  let excludedFiles = 0
  let partialFiles = 0

  for (const file of changedFiles) {
    // 'extra' files exist only on the printer — nothing to apply
    if (file.status === 'extra') continue

    if (!fileChecked(file)) {
      excludedFiles++
      continue
    }

    if (file.status === 'modified' && hasHunkDetail(file)) {
      const selected = file.hunks.filter(h => h.selected)
      if (selected.length < file.hunks.length) {
        partialFiles++
        files.push({ file: file.file, hunks: selected.map(h => h.index) })
        continue
      }
    }

    files.push({ file: file.file })
  }

  return { files, excludedFiles, partialFiles }
}
