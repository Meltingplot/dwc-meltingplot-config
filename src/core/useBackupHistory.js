'use strict'

/**
 * State and actions of the backup history list.
 *
 * A backup row expands into a file tree plus a viewer that shows either the
 * file's content at that commit or the diff the commit introduced.
 */

import { computed, ref, watch } from 'vue'
import { apiGet, apiPost, query } from './api'
import { diffStatusColor, parseHunkHeader, sideBySideLines } from './diff'

/**
 * A backup commit, as the history list works with it.
 *
 * Everything below `isFullBackup` is UI bookkeeping that `normalizeBackup`
 * initialises up front — Vue 2.7 cannot observe a property added later.
 *
 * @typedef {object} Backup
 * @property {string} hash Backup commit hash
 * @property {string} [message] Commit message
 * @property {string} [timestamp] When the backup was taken
 * @property {number} [filesChanged] Number of files the commit touched
 * @property {boolean} [isFullBackup] Whether it snapshots every tracked file
 * @property {boolean} expanded Whether the row's detail panel is open
 * @property {boolean} loadingFiles Whether the file list fetch is in flight
 * @property {boolean} loadingDiff Whether a file's diff or content is loading
 * @property {boolean} loadingContent Reserved for a separate content spinner
 * @property {Array<string>|null} changedFiles Files the commit touched
 * @property {Array<string>|null} files Every file in the commit
 * @property {Array<string>} activeNodes Selected tree node ids
 * @property {string|null} selectedFile Path shown in the viewer
 * @property {BackupFileDiff|null} fileDiff Diff of the selected file
 * @property {BackupFileContent|null} fileContent Content of the selected file
 * @property {string} viewMode `content` or `diff`
 */

/**
 * The diff a backup commit introduced for one file.
 *
 * @typedef {object} BackupFileDiff
 * @property {string} file Path within the backup
 * @property {string} status `modified`, `added`, `deleted`, `unchanged` or `error`
 * @property {Array<import('./diff').DiffHunk>} hunks Detail hunks
 */

/**
 * A file's content as of a backup commit.
 *
 * @typedef {object} BackupFileContent
 * @property {string} file Path within the backup
 * @property {string} [status] `not_found` when the file is absent
 * @property {string|null} content File content, or null when absent
 */

/**
 * One node of the backup file tree.
 *
 * @typedef {object} TreeItem
 * @property {string} id Full path — what the viewer looks the file up by
 * @property {string} name Path segment shown in the tree
 * @property {Array<TreeItem>} [children] Present on folders only
 */

/**
 * Give a backup entry every field the history UI will ever set on it.
 *
 * Same reactivity rule as `normalizeFile` — Vue 2.7 cannot observe properties
 * added after the object became reactive.
 *
 * @param {object} backup Backup entry from `GET /backups`
 * @returns {Backup} Normalised copy
 */
export function normalizeBackup(backup) {
  return {
    expanded: false,
    loadingFiles: false,
    loadingDiff: false,
    loadingContent: false,
    changedFiles: null,
    files: null,
    activeNodes: [],
    selectedFile: null,
    fileDiff: null,
    fileContent: null,
    viewMode: 'diff',
    ...backup
  }
}

/**
 * Turn a flat list of file paths into a nested tree for `v-treeview`.
 *
 * Folders sort before files, both alphabetically. Node ids are the full path,
 * which is what the viewer looks the selected file up by.
 *
 * @param {Array<string>} files Slash-separated paths
 * @returns {Array<TreeItem>} Tree items with `id`, `name` and optional `children`
 */
export function buildFileTree(files) {
  if (!files || files.length === 0) return []

  const root = {}
  for (const filePath of files) {
    const parts = filePath.split('/')
    let current = root
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      if (!current[part]) {
        current[part] = { _children: {} }
      }
      if (i < parts.length - 1) {
        current = current[part]._children
      } else {
        current[part]._isFile = true
      }
    }
  }

  const toItems = (obj, prefix) => {
    const items = []
    for (const [name, data] of Object.entries(obj)) {
      const fullPath = prefix ? prefix + '/' + name : name
      const item = { id: fullPath, name }
      const childEntries = Object.entries(data._children || {})
      if (!data._isFile && childEntries.length > 0) {
        item.children = toItems(data._children, fullPath)
      }
      items.push(item)
    }
    return items.sort((a, b) => {
      const aFolder = !!a.children
      const bFolder = !!b.children
      if (aFolder !== bFolder) return aFolder ? -1 : 1
      return a.name.localeCompare(b.name)
    })
  }

  return toItems(root, '')
}

/**
 * Which file list a backup row shows: everything for a full backup, only the
 * touched files for an incremental one.
 *
 * @param {Backup} backup Backup entry
 * @returns {Array<string>} File paths
 */
export function displayFiles(backup) {
  if (backup.isFullBackup) {
    return backup.files || []
  }
  return backup.changedFiles || []
}

/**
 * Build the backup history's state and actions.
 *
 * @param {import('vue').Ref<Array<Backup>>|(() => Array<Backup>)} backupsRef Reactive
 *   source of the backup list (a ref, or a getter returning it)
 * The return type is left to inference — see the note in `useConfigPage.js`.
 *
 * @param {(event: any, payload?: any) => void} emit Component emit function
 */
export function useBackupHistory(backupsRef, emit) {
  const creatingBackup = ref(false)

  const backups = computed(() =>
    (typeof backupsRef === 'function' ? backupsRef() : backupsRef.value) || []
  )

  /** Take a manual snapshot of the current printer config. */
  async function createBackup() {
    creatingBackup.value = true
    try {
      await apiPost('/manualBackup')
      emit('refresh')
      emit('notify', { text: 'Backup created successfully', color: 'success' })
    } catch (err) {
      emit('notify', { text: 'Failed to create backup: ' + err.message, color: 'error' })
    } finally {
      creatingBackup.value = false
    }
  }

  /**
   * Expand or collapse a backup row, fetching its file list on first expand.
   *
   * @param {Backup} backup Backup entry
   */
  async function toggleExpand(backup) {
    if (backup.expanded) {
      backup.expanded = false
      return
    }
    backup.expanded = true
    if (backup.changedFiles) return

    backup.loadingFiles = true
    backup.activeNodes = []
    backup.selectedFile = null
    backup.fileDiff = null
    backup.fileContent = null
    try {
      const data = await apiGet(`/backup?${query({ hash: backup.hash })}`)
      backup.changedFiles = data.changedFiles || []
      backup.files = data.files || []
    } catch {
      backup.changedFiles = []
      backup.files = []
    } finally {
      backup.loadingFiles = false
    }
  }

  /**
   * Load the diff a backup commit introduced for one file.
   *
   * @param {object} backup Backup entry
   * @param {string} filePath File to load
   */
  async function fetchFileDiff(backup, filePath) {
    backup.loadingDiff = true
    try {
      backup.fileDiff = await apiGet(
        `/backupFileDiff?${query({ hash: backup.hash, file: filePath })}`
      )
    } catch {
      backup.fileDiff = { file: filePath, status: 'error', hunks: [] }
    } finally {
      backup.loadingDiff = false
    }
  }

  /**
   * Load a file's content as of a backup commit.
   *
   * @param {object} backup Backup entry
   * @param {string} filePath File to load
   */
  async function fetchFileContent(backup, filePath) {
    backup.loadingDiff = true
    try {
      backup.fileContent = await apiGet(
        `/backupFileContent?${query({ hash: backup.hash, file: filePath })}`
      )
    } catch {
      backup.fileContent = { file: filePath, status: 'not_found', content: null }
    } finally {
      backup.loadingDiff = false
    }
  }

  /**
   * React to a click in the file tree.
   *
   * @param {object} backup Backup entry
   * @param {Array<string>} activeIds Ids of the activated tree nodes
   */
  async function onFileSelected(backup, activeIds) {
    if (!activeIds || activeIds.length === 0) {
      backup.selectedFile = null
      backup.fileDiff = null
      backup.fileContent = null
      return
    }

    const selectedId = activeIds[0]
    // Only fetch for leaf nodes (actual files, not folders)
    if (!displayFiles(backup).includes(selectedId)) {
      return
    }

    backup.selectedFile = selectedId
    backup.fileDiff = null
    backup.fileContent = null

    // Default view mode: content for full backups, diff for partial
    const defaultMode = backup.isFullBackup ? 'content' : 'diff'
    backup.viewMode = defaultMode

    if (defaultMode === 'content') {
      await fetchFileContent(backup, selectedId)
    } else {
      await fetchFileDiff(backup, selectedId)
    }
  }

  /**
   * Switch a row between the content and the diff view.
   *
   * @param {object} backup Backup entry
   * @param {string} mode `content` or `diff`
   */
  async function switchViewMode(backup, mode) {
    if (!backup.selectedFile) return
    backup.viewMode = mode
    if (mode === 'content' && !backup.fileContent) {
      await fetchFileContent(backup, backup.selectedFile)
    } else if (mode === 'diff' && !backup.fileDiff) {
      await fetchFileDiff(backup, backup.selectedFile)
    }
  }

  watch(backups, list => {
    // Entries that came through loadBackups() are already normalised; this
    // only fills in a list handed to the component directly. They are replaced
    // rather than patched for the same reason as in useConfigDiff: Vue 2.7
    // cannot observe properties added after an object became reactive.
    if (list.some(backup => backup.expanded === undefined)) {
      list.splice(0, list.length, ...list.map(normalizeBackup))
    }
  }, { immediate: true })

  return {
    creatingBackup,
    // pure helpers, re-exported for the template
    buildFileTree,
    displayFiles,
    diffStatusColor,
    parseHunkHeader,
    sideBySideLines,
    // actions
    createBackup,
    toggleExpand,
    fetchFileDiff,
    fetchFileContent,
    onFileSelected,
    switchViewMode
  }
}
