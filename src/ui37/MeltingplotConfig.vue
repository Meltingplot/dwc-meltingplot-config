<template>
  <v-container fluid>
    <v-alert
      v-if="backendRunning === false"
      type="warning"
      variant="tonal"
      class="mb-4"
    >
      <div class="d-flex flex-wrap align-center ga-4">
        <div class="flex-grow-1">
          <div class="text-subtitle-1 font-weight-medium">Backend is not running</div>
          <div class="text-body-2">
            The SBC part of this plugin is stopped, so no configuration data can be
            loaded. This happens after a plugin update — DSF stops the old backend
            process and does not start the new one.
          </div>
        </div>
        <v-btn color="warning" prepend-icon="mdi-play" :loading="startingBackend" @click="startBackend()">
          Start Backend
        </v-btn>
      </div>
    </v-alert>

    <v-card>
      <v-card-title>Meltingplot Config</v-card-title>
      <v-card-text>
        <v-alert type="info" variant="tonal" density="compact" class="mb-4">
          The DWC 3.7 interface is still being built. Sync status is shown below;
          use the DWC 3.6 package for diffing, applying and restoring for now.
        </v-alert>

        <v-chip :color="statusInfo.color" :prepend-icon="statusInfo.icon" class="mb-4">
          {{ statusInfo.label }}
        </v-chip>

        <v-list density="compact">
          <v-list-item
            prepend-icon="mdi-chip" title="Firmware Version"
            :subtitle="pluginData.detectedFirmwareVersion || 'Not detected'"
          />
          <v-list-item
            prepend-icon="mdi-source-branch" title="Active Branch"
            :subtitle="pluginData.activeBranch || 'None'"
          />
          <v-list-item
            prepend-icon="mdi-git" title="Reference Repository"
            :subtitle="pluginData.referenceRepoUrl || 'Not configured'"
          />
          <v-list-item
            prepend-icon="mdi-clock-outline" title="Last Sync"
            :subtitle="pluginData.lastSyncTimestamp || 'Never'"
          />
        </v-list>

        <v-btn
          color="primary"
          prepend-icon="mdi-refresh"
          class="mt-4"
          :loading="syncing"
          :disabled="!pluginData.referenceRepoUrl"
          @click="checkForUpdates()"
        >
          Check for Updates
        </v-btn>
      </v-card-text>
    </v-card>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="4000">
      {{ snackbar.text }}
      <template #actions>
        <v-btn variant="text" @click="snackbar.show = false">Close</v-btn>
      </template>
    </v-snackbar>
  </v-container>
</template>

<script setup lang="ts">
import { computed } from "vue";

import { syncStatusInfo } from "../core/status";
import { useConfigPage } from "../core/useConfigPage";
import { createHost } from "./host";

const { backendRunning, checkForUpdates, pluginData, snackbar, startBackend, startingBackend, syncing } =
	useConfigPage(createHost());

const statusInfo = computed(() => syncStatusInfo(pluginData.value.status));
</script>
