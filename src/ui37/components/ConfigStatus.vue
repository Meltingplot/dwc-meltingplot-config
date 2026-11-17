<template>
  <v-card-text>
    <v-row>
      <v-col cols="12" md="6">
        <v-list density="compact">
          <v-list-item
            prepend-icon="mdi-chip"
            title="Firmware Version"
            :subtitle="firmwareVersion || 'Not detected'"
          />
          <v-list-item
            prepend-icon="mdi-source-branch"
            title="Active Branch"
            :subtitle="activeBranch || 'None'"
          />
          <v-list-item
            prepend-icon="mdi-git"
            title="Reference Repository"
            :subtitle="repoUrl || 'Not configured'"
          />
          <v-list-item
            prepend-icon="mdi-clock-outline"
            title="Last Sync"
            :subtitle="lastSync || 'Never'"
          />
        </v-list>
      </v-col>

      <v-col cols="12" md="6" class="d-flex flex-column align-center justify-center">
        <v-chip
          :color="statusInfo.color"
          :prepend-icon="statusInfo.icon"
          size="large"
          variant="flat"
          class="mb-4"
        >
          {{ statusInfo.label }}
        </v-chip>

        <v-btn
          color="primary"
          prepend-icon="mdi-refresh"
          :loading="syncing"
          :disabled="!repoUrl"
          @click="emit('check-updates')"
        >
          Check for Updates
        </v-btn>

        <div v-if="!repoUrl" class="mt-2 text-caption text-medium-emphasis">
          Configure a repository URL in Settings first
        </div>
      </v-col>
    </v-row>
  </v-card-text>
</template>

<script setup lang="ts">
import { computed } from "vue";

import { syncStatusInfo } from "../../core/status";

const props = withDefaults(
  defineProps<{
    status?: string;
    firmwareVersion?: string;
    activeBranch?: string;
    repoUrl?: string;
    lastSync?: string;
    syncing?: boolean;
  }>(),
  {
    status: "not_configured",
    firmwareVersion: "",
    activeBranch: "",
    repoUrl: "",
    lastSync: "",
    syncing: false,
  }
);

const emit = defineEmits<{ (e: "check-updates"): void }>();

const statusInfo = computed(() => syncStatusInfo(props.status));
</script>
