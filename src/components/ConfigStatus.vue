<template>
  <v-card-text>
    <v-row>
      <v-col cols="12" md="6">
        <v-list dense>
          <v-list-item>
            <v-list-item-icon>
              <v-icon>mdi-chip</v-icon>
            </v-list-item-icon>
            <v-list-item-content>
              <v-list-item-title>Firmware Version</v-list-item-title>
              <v-list-item-subtitle>
                {{ firmwareVersion || 'Not detected' }}
              </v-list-item-subtitle>
            </v-list-item-content>
          </v-list-item>

          <v-list-item>
            <v-list-item-icon>
              <v-icon>mdi-source-branch</v-icon>
            </v-list-item-icon>
            <v-list-item-content>
              <v-list-item-title>Active Branch</v-list-item-title>
              <v-list-item-subtitle>
                {{ activeBranch || 'None' }}
              </v-list-item-subtitle>
            </v-list-item-content>
          </v-list-item>

          <v-list-item>
            <v-list-item-icon>
              <v-icon>mdi-git</v-icon>
            </v-list-item-icon>
            <v-list-item-content>
              <v-list-item-title>Reference Repository</v-list-item-title>
              <v-list-item-subtitle>
                {{ repoUrl || 'Not configured' }}
              </v-list-item-subtitle>
            </v-list-item-content>
          </v-list-item>

          <v-list-item>
            <v-list-item-icon>
              <v-icon>mdi-clock-outline</v-icon>
            </v-list-item-icon>
            <v-list-item-content>
              <v-list-item-title>Last Sync</v-list-item-title>
              <v-list-item-subtitle>
                {{ lastSync || 'Never' }}
              </v-list-item-subtitle>
            </v-list-item-content>
          </v-list-item>
        </v-list>
      </v-col>

      <v-col cols="12" md="6" class="d-flex flex-column align-center justify-center">
        <v-chip
          :color="statusColor"
          text-color="white"
          large
          class="mb-4"
        >
          <v-icon left>{{ statusIcon }}</v-icon>
          {{ statusLabel }}
        </v-chip>

        <v-btn
          color="primary"
          :loading="syncing"
          :disabled="!repoUrl"
          @click="$emit('check-updates')"
        >
          <v-icon left>mdi-refresh</v-icon>
          Check for Updates
        </v-btn>

        <div v-if="!repoUrl" class="mt-2 caption grey--text">
          Configure a repository URL in Settings first
        </div>
      </v-col>
    </v-row>
  </v-card-text>
</template>

<script>
'use strict'

const STATUS_MAP = {
  not_configured: { color: 'grey', icon: 'mdi-help-circle', label: 'Not Configured' },
  up_to_date: { color: 'success', icon: 'mdi-check-circle', label: 'Up to Date' },
  updates_available: { color: 'warning', icon: 'mdi-alert-circle', label: 'Updates Available' },
  error: { color: 'error', icon: 'mdi-alert', label: 'Error' }
}

export default {
  name: 'ConfigStatus',
  props: {
    status: { type: String, default: 'not_configured' },
    firmwareVersion: { type: String, default: '' },
    activeBranch: { type: String, default: '' },
    repoUrl: { type: String, default: '' },
    lastSync: { type: String, default: '' },
    syncing: { type: Boolean, default: false }
  },
  computed: {
    statusInfo() {
      return STATUS_MAP[this.status] || STATUS_MAP.not_configured
    },
    statusColor() {
      return this.statusInfo.color
    },
    statusIcon() {
      return this.statusInfo.icon
    },
    statusLabel() {
      return this.statusInfo.label
    }
  }
}
</script>
