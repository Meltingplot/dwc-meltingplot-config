<template>
  <v-container fluid>
    <v-row v-if="backendRunning === false">
      <v-col cols="12">
        <v-alert type="warning" prominent text class="mb-0">
          <div class="d-flex flex-wrap align-center">
            <div class="flex-grow-1 mr-4">
              <div class="subtitle-1 font-weight-medium">Backend is not running</div>
              <div class="body-2">
                The SBC part of this plugin is stopped, so no configuration data can be
                loaded. This happens after a plugin update — DSF stops the old backend
                process and does not start the new one.
              </div>
            </div>
            <v-btn color="warning" :loading="startingBackend" @click="startBackend">
              <v-icon left>mdi-play</v-icon>
              Start Backend
            </v-btn>
          </div>
        </v-alert>
      </v-col>
    </v-row>

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
                @apply-selection="applySelection"
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
                  :items="SYNC_INTERVAL_OPTIONS"
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

import { getCurrentInstance } from 'vue'
import ConfigStatus from './components/ConfigStatus.vue'
import ConfigDiff from './components/ConfigDiff.vue'
import BackupHistory from './components/BackupHistory.vue'
import { createHost } from './host'
import { useConfigPage } from './core/useConfigPage'

export default {
  name: 'MeltingplotConfig',
  components: { ConfigStatus, ConfigDiff, BackupHistory },
  setup() {
    // The Vuex store is a singleton in DWC, but reading it off the instance
    // keeps the component mountable with a test store.
    const store = getCurrentInstance().proxy.$store
    return useConfigPage(createHost(store))
  }
}
</script>
