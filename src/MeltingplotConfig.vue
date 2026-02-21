<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <v-card>
          <v-tabs v-model="activeTab">
            <v-tab key="status">
              <v-icon left>mdi-information-outline</v-icon>
              Status
            </v-tab>
            <v-tab key="changes">
              <v-icon left>mdi-file-compare</v-icon>
              Changes
              <v-chip v-if="changedFileCount > 0" small class="ml-2" color="warning">
                {{ changedFileCount }}
              </v-chip>
            </v-tab>
            <v-tab key="history">
              <v-icon left>mdi-history</v-icon>
              History
            </v-tab>
            <v-tab key="settings">
              <v-icon left>mdi-cog</v-icon>
              Settings
            </v-tab>
          </v-tabs>

          <v-tabs-items v-model="activeTab">
            <v-tab-item key="status">
              <config-status
                :status="pluginData.status"
                :firmware-version="pluginData.detectedFirmwareVersion"
                :active-branch="pluginData.activeBranch"
                :repo-url="pluginData.referenceRepoUrl"
                :last-sync="pluginData.lastSyncTimestamp"
                :syncing="syncing"
                @check-updates="checkForUpdates"
              />
            </v-tab-item>

            <v-tab-item key="changes">
              <config-diff
                :files="diffFiles"
                :loading="loadingDiff"
                @apply-all="applyAll"
                @apply-file="applyFile"
                @apply-hunks="applyHunks"
              />
            </v-tab-item>

            <v-tab-item key="history">
              <backup-history
                :backups="backups"
                :loading="loadingBackups"
                @restore="restoreBackup"
                @download="downloadBackup"
                @delete="deleteBackup"
                @refresh="loadBackups"
                @notify="onBackupNotify"
              />
            </v-tab-item>

            <v-tab-item key="settings">
              <v-card-text>
                <v-text-field
                  v-model="settings.referenceRepoUrl"
                  label="Reference Repository URL"
                  hint="Git repository URL for this printer model's config"
                  persistent-hint
                  outlined
                />
                <v-text-field
                  v-model="pluginData.detectedFirmwareVersion"
                  label="Detected Firmware Version"
                  readonly
                  outlined
                  disabled
                  class="mt-4"
                />
                <v-text-field
                  v-model="pluginData.activeBranch"
                  label="Active Branch"
                  readonly
                  outlined
                  disabled
                  class="mt-4"
                />
                <v-text-field
                  v-model="settings.firmwareBranchOverride"
                  label="Branch Override"
                  hint="Leave empty for auto-detection (recommended)"
                  persistent-hint
                  outlined
                  class="mt-4"
                />
                <v-select
                  v-model="settings.syncInterval"
                  :items="syncIntervalOptions"
                  label="Auto-sync Interval"
                  outlined
                  class="mt-4"
                />
                <div v-if="availableBranches.length > 0" class="mt-4">
                  <div class="subtitle-1 mb-2">Available Branches</div>
                  <v-chip
                    v-for="branch in availableBranches"
                    :key="branch"
                    class="mr-2 mb-2"
                    :color="branch === pluginData.activeBranch ? 'primary' : undefined"
                    small
                  >
                    {{ branch }}
                  </v-chip>
                </div>
                <v-btn color="primary" class="mt-4" :loading="savingSettings" @click="saveSettings">
                  Save Settings
                </v-btn>
              </v-card-text>
            </v-tab-item>
          </v-tabs-items>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="confirmDialog.show" max-width="500">
      <v-card>
        <v-card-title>{{ confirmDialog.title }}</v-card-title>
        <v-card-text>{{ confirmDialog.message }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn text @click="confirmDialog.show = false">Cancel</v-btn>
          <v-btn color="primary" @click="confirmDialog.show = false; confirmDialog.action()">Confirm</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="4000">
      {{ snackbar.text }}
      <template #action="{ attrs }">
        <v-btn text v-bind="attrs" @click="snackbar.show = false">Close</v-btn>
      </template>
    </v-snackbar>
  </v-container>
</template>

<script>
'use strict'

import { mapState } from 'vuex'
import ConfigStatus from './components/ConfigStatus.vue'
import ConfigDiff from './components/ConfigDiff.vue'
import BackupHistory from './components/BackupHistory.vue'

const API_BASE = '/machine/MeltingplotConfig'

export default {
  name: 'MeltingplotConfig',
  components: { ConfigStatus, ConfigDiff, BackupHistory },
  data() {
    return {
      activeTab: 0,
      syncing: false,
      loadingDiff: false,
      loadingBackups: false,
      backupsLoaded: false,
      savingSettings: false,
      diffFiles: [],
      backups: [],
      availableBranches: [],
      settings: {
        referenceRepoUrl: '',
        firmwareBranchOverride: '',
        syncInterval: 'manual'
      },
      syncIntervalOptions: [
        { text: 'Manual only', value: 'manual' },
        { text: 'On boot', value: 'boot' },
        { text: 'Daily', value: 'daily' }
      ],
      confirmDialog: {
        show: false,
        title: '',
        message: '',
        action: () => {}
      },
      snackbar: {
        show: false,
        text: '',
        color: 'info'
      }
    }
  },
  computed: {
    ...mapState('machine/model', {
      pluginData(state) {
        // In DWC 3.6, state.plugins is a Map keyed by plugin ID.
        // Each entry is a full Plugin object; custom data lives in plugin.data.
        const plugin = state.plugins instanceof Map
          ? state.plugins.get('MeltingplotConfig')
          : state.plugins?.['MeltingplotConfig']
        const data = plugin?.data || {}
        return {
          referenceRepoUrl: data.referenceRepoUrl || '',
          firmwareBranchOverride: data.firmwareBranchOverride || '',
          detectedFirmwareVersion: data.detectedFirmwareVersion || '',
          activeBranch: data.activeBranch || '',
          lastSyncTimestamp: data.lastSyncTimestamp || '',
          status: data.status || 'not_configured'
        }
      }
    }),
    changedFileCount() {
      return this.diffFiles.filter(f => f.status !== 'unchanged').length
    }
  },
  watch: {
    activeTab(val) {
      if (val === 2 && !this.backupsLoaded) {
        this.loadBackups()
      }
    },
    pluginData: {
      handler(val) {
        this.settings.referenceRepoUrl = val.referenceRepoUrl
        this.settings.firmwareBranchOverride = val.firmwareBranchOverride
      },
      immediate: true
    }
  },
  mounted() {
    this.loadStatus()
  },
  methods: {
    async apiGet(path) {
      const response = await fetch(API_BASE + path)
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || response.statusText)
      }
      return response.json()
    },
    async apiPost(path, body = null) {
      const options = { method: 'POST' }
      if (body !== null) {
        options.headers = { 'Content-Type': 'application/json' }
        options.body = JSON.stringify(body)
      }
      const response = await fetch(API_BASE + path, options)
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || response.statusText)
      }
      return response.json()
    },
    async loadStatus() {
      try {
        const status = await this.apiGet('/status')
        if (status.branches) {
          this.availableBranches = status.branches
        }
        // Auto-load diff when a reference repo is configured so changes
        // are visible immediately after a restart without a manual sync.
        if (status.referenceRepoUrl) {
          this.loadDiff()
        }
      } catch {
        // Status endpoint may not be available yet
      }
    },
    async checkForUpdates() {
      this.syncing = true
      try {
        await this.apiPost('/sync')
        await this.loadDiff()
        await this.loadBranches()
        this.notify('Sync complete', 'success')
      } catch (err) {
        this.notify('Sync failed: ' + err.message, 'error')
      } finally {
        this.syncing = false
      }
    },
    async loadDiff() {
      this.loadingDiff = true
      try {
        const data = await this.apiGet('/diff')
        this.diffFiles = data.files || []
      } catch (err) {
        this.notify('Failed to load diff: ' + err.message, 'error')
      } finally {
        this.loadingDiff = false
      }
    },
    async loadBranches() {
      try {
        const data = await this.apiGet('/branches')
        this.availableBranches = data.branches || []
      } catch {
        // Non-critical
      }
    },
    async loadBackups() {
      this.loadingBackups = true
      try {
        const data = await this.apiGet('/backups')
        this.backups = data.backups || []
        this.backupsLoaded = true
      } catch (err) {
        this.notify('Failed to load backups: ' + err.message, 'error')
      } finally {
        this.loadingBackups = false
      }
    },
    applyAll() {
      this.confirm(
        'Apply All Changes',
        'This will apply all reference config changes to the printer. A backup will be created first. Continue?',
        async () => {
          try {
            await this.apiPost('/apply')
            this.notify('All changes applied successfully', 'success')
            await this.loadDiff()
          } catch (err) {
            this.notify('Apply failed: ' + err.message, 'error')
          }
        }
      )
    },
    applyFile(file) {
      this.confirm(
        'Apply File',
        `Apply all changes to ${file}? A backup will be created first.`,
        async () => {
          try {
            await this.apiPost(`/apply?file=${encodeURIComponent(file)}`)
            this.notify(`Applied changes to ${file}`, 'success')
            await this.loadDiff()
          } catch (err) {
            this.notify('Apply failed: ' + err.message, 'error')
          }
        }
      )
    },
    applyHunks({ file, hunks }) {
      const count = hunks.length
      this.confirm(
        'Apply Selected Changes',
        `Apply ${count} selected change${count !== 1 ? 's' : ''} to ${file}? A backup will be created first.`,
        async () => {
          try {
            const result = await this.apiPost(
              `/applyHunks?file=${encodeURIComponent(file)}`,
              { hunks }
            )
            if (result.failed && result.failed.length > 0) {
              this.notify(
                `Applied ${result.applied.length} hunks, ${result.failed.length} failed (conflict)`,
                'warning'
              )
            } else {
              this.notify(`Applied ${count} change${count !== 1 ? 's' : ''} to ${file}`, 'success')
            }
            await this.loadDiff()
          } catch (err) {
            this.notify('Apply failed: ' + err.message, 'error')
          }
        }
      )
    },
    restoreBackup(commitHash) {
      this.confirm(
        'Restore Backup',
        'This will restore the printer config to the selected backup state. A backup of the current state will be created first. Continue?',
        async () => {
          try {
            await this.apiPost(`/restore?hash=${encodeURIComponent(commitHash)}`)
            this.notify('Backup restored successfully', 'success')
            await this.loadDiff()
          } catch (err) {
            this.notify('Restore failed: ' + err.message, 'error')
          }
        }
      )
    },
    deleteBackup(commitHash) {
      this.confirm(
        'Delete Backup',
        'Are you sure you want to permanently delete this backup? This action cannot be undone.',
        async () => {
          try {
            await this.apiPost(`/deleteBackup?hash=${encodeURIComponent(commitHash)}`)
            this.notify('Backup deleted', 'success')
            await this.loadBackups()
          } catch (err) {
            this.notify('Delete failed: ' + err.message, 'error')
          }
        }
      )
    },
    async downloadBackup(commitHash) {
      try {
        const response = await fetch(`${API_BASE}/backupDownload?hash=${encodeURIComponent(commitHash)}`)
        if (!response.ok) {
          throw new Error(response.statusText)
        }
        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `backup-${commitHash.substring(0, 8)}.zip`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      } catch (err) {
        this.notify('Download failed: ' + err.message, 'error')
      }
    },
    onBackupNotify({ text, color }) {
      this.notify(text, color)
    },
    async saveSettings() {
      this.savingSettings = true
      try {
        await this.apiPost('/settings', {
          referenceRepoUrl: this.settings.referenceRepoUrl,
          firmwareBranchOverride: this.settings.firmwareBranchOverride,
          syncInterval: this.settings.syncInterval
        })
        this.notify('Settings saved', 'success')
      } catch (err) {
        this.notify('Failed to save settings: ' + err.message, 'error')
      } finally {
        this.savingSettings = false
      }
    },
    confirm(title, message, action) {
      this.confirmDialog = { show: true, title, message, action }
    },
    notify(text, color = 'info') {
      this.snackbar = { show: true, text, color }
    }
  }
}
</script>
