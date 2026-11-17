<template>
  <v-container fluid>
    <v-alert v-if="backendRunning === false" type="warning" variant="tonal" class="mb-4">
      <div class="d-flex flex-wrap align-center ga-4">
        <div class="flex-grow-1">
          <div class="text-subtitle-1 font-weight-medium">Backend is not running</div>
          <div class="text-body-2">
            The SBC part of this plugin is stopped, so no configuration data can be
            loaded. This happens after a plugin update — DSF stops the old backend
            process and does not start the new one.
          </div>
        </div>
        <v-btn
          color="warning"
          prepend-icon="mdi-play"
          :loading="startingBackend"
          @click="startBackend()"
        >
          Start Backend
        </v-btn>
      </div>
    </v-alert>

    <v-card>
      <v-tabs v-model="activeTab">
        <v-tab :value="0" prepend-icon="mdi-information-outline">Status</v-tab>
        <v-tab :value="1" prepend-icon="mdi-file-compare">
          Changes
          <v-chip v-if="changedFileCount > 0" size="small" class="ml-2" color="warning">
            {{ changedFileCount }}
          </v-chip>
        </v-tab>
        <v-tab :value="2" prepend-icon="mdi-history">History</v-tab>
        <v-tab :value="3" prepend-icon="mdi-cog">Settings</v-tab>
      </v-tabs>

      <v-tabs-window v-model="activeTab">
        <v-tabs-window-item :value="0">
          <config-status
            :status="pluginData.status"
            :firmware-version="pluginData.detectedFirmwareVersion"
            :active-branch="pluginData.activeBranch"
            :repo-url="pluginData.referenceRepoUrl"
            :last-sync="pluginData.lastSyncTimestamp"
            :syncing="syncing"
            @check-updates="checkForUpdates()"
          />
        </v-tabs-window-item>

        <v-tabs-window-item :value="1">
          <config-diff
            :files="diffFiles"
            :loading="loadingDiff"
            @apply-all="applyAll()"
            @apply-file="applyFile"
            @apply-hunks="applyHunks"
            @apply-selection="applySelection"
          />
        </v-tabs-window-item>

        <v-tabs-window-item :value="2">
          <backup-history
            :backups="backups"
            :loading="loadingBackups"
            @restore="restoreBackup"
            @download="downloadBackup"
            @delete="deleteBackup"
            @refresh="loadBackups()"
            @notify="onBackupNotify"
          />
        </v-tabs-window-item>

        <v-tabs-window-item :value="3">
          <v-card-text>
            <v-text-field
              v-model="settings.referenceRepoUrl"
              label="Reference Repository URL"
              hint="Git repository URL for this printer model's config"
              persistent-hint
              variant="outlined"
            />
            <v-text-field
              :model-value="pluginData.detectedFirmwareVersion"
              label="Detected Firmware Version"
              readonly
              disabled
              variant="outlined"
              class="mt-4"
            />
            <v-text-field
              :model-value="pluginData.activeBranch"
              label="Active Branch"
              readonly
              disabled
              variant="outlined"
              class="mt-4"
            />
            <v-text-field
              v-model="settings.firmwareBranchOverride"
              label="Branch Override"
              hint="Leave empty for auto-detection (recommended)"
              persistent-hint
              variant="outlined"
              class="mt-4"
            />
            <v-select
              v-model="settings.syncInterval"
              :items="SYNC_INTERVAL_OPTIONS"
              item-title="text"
              item-value="value"
              label="Auto-sync Interval"
              variant="outlined"
              class="mt-4"
            />
            <div v-if="availableBranches.length > 0" class="mt-4">
              <div class="text-subtitle-1 mb-2">Available Branches</div>
              <v-chip
                v-for="branch in availableBranches"
                :key="branch"
                class="mr-2 mb-2"
                size="small"
                :color="branch === pluginData.activeBranch ? 'primary' : undefined"
              >
                {{ branch }}
              </v-chip>
            </div>
            <v-btn color="primary" class="mt-4" :loading="savingSettings" @click="saveSettings()">
              Save Settings
            </v-btn>
          </v-card-text>
        </v-tabs-window-item>
      </v-tabs-window>
    </v-card>

    <v-dialog v-model="confirmDialog.show" max-width="500">
      <v-card>
        <v-card-title>{{ confirmDialog.title }}</v-card-title>
        <v-card-text>{{ confirmDialog.message }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="confirmDialog.show = false">Cancel</v-btn>
          <v-btn color="primary" @click="runConfirmedAction()">Confirm</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="4000">
      {{ snackbar.text }}
      <template #actions>
        <v-btn variant="text" @click="snackbar.show = false">Close</v-btn>
      </template>
    </v-snackbar>
  </v-container>
</template>

<script setup lang="ts">
import BackupHistory from "./components/BackupHistory.vue";
import ConfigDiff from "./components/ConfigDiff.vue";
import ConfigStatus from "./components/ConfigStatus.vue";
import { createHost } from "./host";
import { useConfigPage } from "../core/useConfigPage";

const {
  SYNC_INTERVAL_OPTIONS,
  activeTab,
  syncing,
  loadingDiff,
  loadingBackups,
  savingSettings,
  startingBackend,
  diffFiles,
  backups,
  availableBranches,
  settings,
  confirmDialog,
  snackbar,
  pluginData,
  backendRunning,
  changedFileCount,
  loadBackups,
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
  saveSettings,
} = useConfigPage(createHost());

/** Close the dialog first, then run what the user confirmed. */
function runConfirmedAction() {
  confirmDialog.show = false;
  void confirmDialog.action();
}
</script>
