'use strict'

/**
 * State and actions of the plugin's main page.
 *
 * Framework-neutral: uses only the Composition API, which both Vue 2.7 and
 * Vue 3 expose from `vue`. The DWC-specific bits arrive through the host.
 */

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiBlob, apiGet, apiPost, downloadBlob, query } from './api'
import { PLUGIN_ID, isBackendRunning, readPluginData } from './host'
import { normalizeFile } from './diff'
import { normalizeBackup } from './useBackupHistory'
import { startBackend as startSbcBackend } from './backend'

/** How long to wait for the daemon to register its HTTP endpoints after start. */
const BACKEND_WAIT_ATTEMPTS = 15
const BACKEND_WAIT_INTERVAL = 1000

/** Tab index of the History tab, whose backups are fetched on first visit. */
const HISTORY_TAB = 2

/** Options of the auto-sync interval select. */
export const SYNC_INTERVAL_OPTIONS = [
  { text: 'Manual only', value: 'manual' },
  { text: 'On boot', value: 'boot' },
  { text: 'Daily', value: 'daily' }
]

/**
 * Build the main page's state and actions.
 *
 * The return type is deliberately left to inference: the DWC 3.7 templates are
 * type-checked against it by vue-tsc, and a `@returns {object}` annotation would
 * flatten it to `{}` and hide every binding.
 *
 * @param {import('./host').Host} host DWC host adapter
 */
export function useConfigPage(host) {
  const activeTab = ref(0)
  const syncing = ref(false)
  const loadingDiff = ref(false)
  const loadingBackups = ref(false)
  const backupsLoaded = ref(false)
  const savingSettings = ref(false)
  const startingBackend = ref(false)
  const diffFiles = ref([])
  const backups = ref([])
  const availableBranches = ref([])

  // A ref rather than a reactive object: assigning a whole new settings object
  // (`page.settings = {...}`) has to keep working, which `reactive` would not.
  const settings = ref({
    referenceRepoUrl: '',
    firmwareBranchOverride: '',
    syncInterval: 'manual'
  })

  const confirmDialog = reactive({
    show: false,
    title: '',
    message: '',
    action: () => {}
  })

  const snackbar = reactive({
    show: false,
    text: '',
    color: 'info'
  })

  const pluginData = computed(() => readPluginData(host.model()))

  // true / false, or null while the object model has not reported a PID yet
  const backendRunning = computed(() => isBackendRunning(host.model()))

  const changedFileCount = computed(
    () => diffFiles.value.filter(f => f.status !== 'unchanged').length
  )

  /**
   * Show a message in the snackbar.
   *
   * @param {string} text Message
   * @param {string} [color] Vuetify colour name
   */
  function notify(text, color = 'info') {
    snackbar.show = true
    snackbar.text = text
    snackbar.color = color
  }

  /**
   * Open the confirmation dialog for a destructive action.
   *
   * @param {string} title Dialog title
   * @param {string} message Dialog body
   * @param {Function} action Runs when the user confirms
   */
  function confirm(title, message, action) {
    confirmDialog.show = true
    confirmDialog.title = title
    confirmDialog.message = message
    confirmDialog.action = action
  }

  /**
   * Report a failed action in the snackbar.
   *
   * @param {string} prefix Leading text, e.g. `Apply failed`
   * @param {Error|*} err The rejection value
   */
  function notifyError(prefix, err) {
    notify(`${prefix}: ${err && err.message ? err.message : err}`, 'error')
  }

  async function loadDiff() {
    loadingDiff.value = true
    try {
      const data = await apiGet('/diff')
      diffFiles.value = (data.files || []).map(normalizeFile)
    } catch (err) {
      notifyError('Failed to load diff', err)
    } finally {
      loadingDiff.value = false
    }
  }

  async function loadBranches() {
    try {
      const data = await apiGet('/branches')
      availableBranches.value = data.branches || []
    } catch {
      // Non-critical
    }
  }

  async function loadBackups() {
    loadingBackups.value = true
    try {
      const data = await apiGet('/backups')
      backups.value = (data.backups || []).map(normalizeBackup)
      backupsLoaded.value = true
    } catch (err) {
      notifyError('Failed to load backups', err)
    } finally {
      loadingBackups.value = false
    }
  }

  async function loadStatus() {
    try {
      const status = await apiGet('/status')
      if (status.branches) {
        availableBranches.value = status.branches
      }
      // Auto-load diff when a reference repo is configured so changes are
      // visible immediately after a restart without a manual sync.
      if (status.referenceRepoUrl) {
        loadDiff()
      }
    } catch {
      // Status endpoint may not be available yet
    }
  }

  /**
   * Poll `/status` until the freshly started daemon answers.
   *
   * @param {number} [attempts] Number of tries
   * @param {number} [delay] Delay between tries in ms
   * @returns {Promise<boolean>} Whether the backend came up
   */
  async function waitForBackend(attempts = BACKEND_WAIT_ATTEMPTS, delay = BACKEND_WAIT_INTERVAL) {
    // The daemon needs a moment to connect to DSF and register its endpoints
    for (let i = 0; i < attempts; i++) {
      try {
        await apiGet('/status')
        return true
      } catch {
        await new Promise(resolve => setTimeout(resolve, delay))
      }
    }
    return false
  }

  /**
   * Start the SBC backend and wait for its endpoints to answer.
   *
   * @param {object} [wait] Override the poll budget (used by tests)
   * @param {number} [wait.attempts] Number of tries
   * @param {number} [wait.delay] Delay between tries in ms
   * @returns {Promise<void>} Resolves once the outcome has been reported
   */
  async function startBackend(wait = {}) {
    startingBackend.value = true
    try {
      await startSbcBackend(host)
      if (!await waitForBackend(wait.attempts, wait.delay)) {
        throw new Error('backend did not come up in time')
      }
      await loadStatus()
      notify('Backend started', 'success')
    } catch (err) {
      notifyError('Failed to start backend', err)
    } finally {
      startingBackend.value = false
    }
  }

  async function checkForUpdates() {
    syncing.value = true
    try {
      await apiPost('/sync')
      await loadDiff()
      await loadBranches()
      notify('Sync complete', 'success')
    } catch (err) {
      notifyError('Sync failed', err)
    } finally {
      syncing.value = false
    }
  }

  function applyAll() {
    confirm(
      'Apply All Changes',
      'This will apply all reference config changes to the printer. A backup will be created first. Continue?',
      async () => {
        try {
          await apiPost('/apply')
          notify('All changes applied successfully', 'success')
          await loadDiff()
        } catch (err) {
          notifyError('Apply failed', err)
        }
      }
    )
  }

  /**
   * Apply a mixed file/hunk selection in one pass.
   *
   * @param {object} selection Payload from `computeSelection()`
   */
  function applySelection({ files, excludedFiles, partialFiles }) {
    const count = files.length
    const notes = []
    if (excludedFiles > 0) {
      notes.push(`${excludedFiles} file${excludedFiles !== 1 ? 's' : ''} stay${excludedFiles === 1 ? 's' : ''} untouched`)
    }
    if (partialFiles > 0) {
      notes.push(`${partialFiles} file${partialFiles !== 1 ? 's' : ''} only get${partialFiles === 1 ? 's' : ''} the selected changes`)
    }
    confirm(
      'Partially Apply Changes',
      `Apply the current selection to ${count} file${count !== 1 ? 's' : ''}? ` +
        (notes.length > 0 ? notes.join(', ') + '. ' : '') +
        'A backup will be created first.',
      async () => {
        try {
          const result = await apiPost('/applySelection', { files })
          const applied = (result.applied || []).length
          const skipped = (result.skipped || []).length
          const failedHunks = Object.keys(result.partial || {}).reduce(
            (sum, key) => sum + ((result.partial[key].failed || []).length), 0
          )
          if (skipped > 0 || failedHunks > 0) {
            const problems = []
            if (skipped > 0) {
              problems.push(`${skipped} file${skipped !== 1 ? 's' : ''} skipped`)
            }
            if (failedHunks > 0) {
              problems.push(`${failedHunks} change${failedHunks !== 1 ? 's' : ''} failed (conflict)`)
            }
            notify(
              `Applied ${applied} file${applied !== 1 ? 's' : ''}, ${problems.join(', ')}`,
              'warning'
            )
          } else {
            notify(`Applied changes to ${applied} file${applied !== 1 ? 's' : ''}`, 'success')
          }
          await loadDiff()
        } catch (err) {
          notifyError('Apply failed', err)
        }
      }
    )
  }

  /**
   * Apply every change of a single file.
   *
   * @param {string} file Reference-repo relative path
   */
  function applyFile(file) {
    confirm(
      'Apply File',
      `Apply all changes to ${file}? A backup will be created first.`,
      async () => {
        try {
          await apiPost(`/apply?${query({ file })}`)
          notify(`Applied changes to ${file}`, 'success')
          await loadDiff()
        } catch (err) {
          notifyError('Apply failed', err)
        }
      }
    )
  }

  /**
   * Apply selected hunks of a single file.
   *
   * @param {object} payload `{ file, hunks }` with hunk indices
   */
  function applyHunks({ file, hunks }) {
    const count = hunks.length
    confirm(
      'Apply Selected Changes',
      `Apply ${count} selected change${count !== 1 ? 's' : ''} to ${file}? A backup will be created first.`,
      async () => {
        try {
          const result = await apiPost(`/applyHunks?${query({ file })}`, { hunks })
          if (result.failed && result.failed.length > 0) {
            notify(
              `Applied ${result.applied.length} hunks, ${result.failed.length} failed (conflict)`,
              'warning'
            )
          } else {
            notify(`Applied ${count} change${count !== 1 ? 's' : ''} to ${file}`, 'success')
          }
          await loadDiff()
        } catch (err) {
          notifyError('Apply failed', err)
        }
      }
    )
  }

  /**
   * Restore the printer config from a backup commit.
   *
   * @param {string} commitHash Backup commit hash
   */
  function restoreBackup(commitHash) {
    confirm(
      'Restore Backup',
      'This will restore the printer config to the selected backup state. A backup of the current state will be created first. Continue?',
      async () => {
        try {
          await apiPost(`/restore?${query({ hash: commitHash })}`)
          notify('Backup restored successfully', 'success')
          await loadDiff()
        } catch (err) {
          notifyError('Restore failed', err)
        }
      }
    )
  }

  /**
   * Permanently delete a backup commit.
   *
   * @param {string} commitHash Backup commit hash
   */
  function deleteBackup(commitHash) {
    confirm(
      'Delete Backup',
      'Are you sure you want to permanently delete this backup? This action cannot be undone.',
      async () => {
        try {
          await apiPost(`/deleteBackup?${query({ hash: commitHash })}`)
          notify('Backup deleted', 'success')
          await loadBackups()
        } catch (err) {
          notifyError('Delete failed', err)
        }
      }
    )
  }

  /**
   * Download a backup as a ZIP.
   *
   * @param {string} commitHash Backup commit hash
   */
  async function downloadBackup(commitHash) {
    try {
      const blob = await apiBlob(`/backupDownload?${query({ hash: commitHash })}`)
      downloadBlob(blob, `backup-${commitHash.substring(0, 8)}.zip`)
    } catch (err) {
      notifyError('Download failed', err)
    }
  }

  /**
   * Relay a notification raised by the history child component.
   *
   * @param {object} payload `{ text, color }`
   */
  function onBackupNotify({ text, color }) {
    notify(text, color)
  }

  async function saveSettings() {
    savingSettings.value = true
    try {
      await apiPost('/settings', {
        referenceRepoUrl: settings.value.referenceRepoUrl,
        firmwareBranchOverride: settings.value.firmwareBranchOverride,
        syncInterval: settings.value.syncInterval
      })
      notify('Settings saved', 'success')
    } catch (err) {
      notifyError('Failed to save settings', err)
    } finally {
      savingSettings.value = false
    }
  }

  watch(activeTab, val => {
    if (val === HISTORY_TAB && !backupsLoaded.value) {
      loadBackups()
    }
  })

  watch(pluginData, val => {
    settings.value.referenceRepoUrl = val.referenceRepoUrl
    settings.value.firmwareBranchOverride = val.firmwareBranchOverride
  }, { immediate: true })

  watch(backendRunning, (val, oldVal) => {
    // Pick the data up once the backend comes back (started here or elsewhere)
    if (val === true && oldVal === false) {
      loadStatus()
    }
  })

  onMounted(loadStatus)

  return {
    PLUGIN_ID,
    SYNC_INTERVAL_OPTIONS,
    // state
    activeTab,
    syncing,
    loadingDiff,
    loadingBackups,
    backupsLoaded,
    savingSettings,
    startingBackend,
    diffFiles,
    backups,
    availableBranches,
    settings,
    confirmDialog,
    snackbar,
    // computed
    pluginData,
    backendRunning,
    changedFileCount,
    // actions
    apiGet,
    apiPost,
    notify,
    confirm,
    loadStatus,
    loadDiff,
    loadBranches,
    loadBackups,
    waitForBackend,
    startBackend,
    checkForUpdates,
    applyAll,
    applySelection,
    applyFile,
    applyHunks,
    restoreBackup,
    deleteBackup,
    downloadBackup,
    onBackupNotify,
    saveSettings
  }
}
