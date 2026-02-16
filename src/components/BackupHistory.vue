<template>
  <v-card-text>
    <v-toolbar flat dense class="mb-4">
      <v-toolbar-title class="subtitle-1">Backup History</v-toolbar-title>
      <v-spacer />
      <v-btn small text @click="$emit('refresh')">
        <v-icon left small>mdi-refresh</v-icon>
        Refresh
      </v-btn>
    </v-toolbar>

    <div v-if="loading" class="text-center pa-8">
      <v-progress-circular indeterminate color="primary" />
      <div class="mt-2">Loading backups...</div>
    </div>

    <div v-else-if="backups.length === 0" class="text-center pa-8">
      <v-icon large color="grey">mdi-history</v-icon>
      <div class="mt-2 title">No backups yet</div>
      <div class="caption grey--text">
        Backups are created automatically when config changes are applied.
      </div>
    </div>

    <v-list v-else two-line>
      <template v-for="(backup, index) in backups">
        <v-list-item :key="backup.hash" @click="toggleExpand(backup)">
          <v-list-item-icon>
            <v-icon>mdi-source-commit</v-icon>
          </v-list-item-icon>

          <v-list-item-content>
            <v-list-item-title>{{ backup.message }}</v-list-item-title>
            <v-list-item-subtitle>
              <v-icon x-small class="mr-1">mdi-clock-outline</v-icon>
              {{ backup.timestamp }}
              <span v-if="backup.filesChanged" class="ml-2">
                <v-icon x-small class="mr-1">mdi-file-multiple</v-icon>
                {{ backup.filesChanged }} file{{ backup.filesChanged !== 1 ? 's' : '' }}
              </span>
              <span class="ml-2 caption">
                {{ backup.hash.substring(0, 8) }}
              </span>
            </v-list-item-subtitle>
          </v-list-item-content>

          <v-list-item-action class="flex-row">
            <v-btn icon small title="Download backup" @click.stop="$emit('download', backup.hash)">
              <v-icon small>mdi-download</v-icon>
            </v-btn>
            <v-btn icon small title="Restore this backup" @click.stop="$emit('restore', backup.hash)">
              <v-icon small>mdi-backup-restore</v-icon>
            </v-btn>
          </v-list-item-action>
        </v-list-item>

        <!-- Expanded detail: files in this backup -->
        <v-expand-transition :key="backup.hash + '-detail'">
          <div v-if="backup.expanded" class="px-8 pb-4">
            <div v-if="backup.loadingFiles" class="text-center pa-2">
              <v-progress-circular indeterminate size="20" />
            </div>
            <v-chip
              v-for="file in backup.files"
              v-else
              :key="file"
              small
              outlined
              class="mr-1 mb-1"
            >
              {{ file }}
            </v-chip>
          </div>
        </v-expand-transition>

        <v-divider v-if="index < backups.length - 1" :key="'d-' + backup.hash" />
      </template>
    </v-list>
  </v-card-text>
</template>

<script>
'use strict'

const API_BASE = '/machine/MeltingplotConfig'

export default {
  name: 'BackupHistory',
  props: {
    backups: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  methods: {
    async toggleExpand(backup) {
      if (backup.expanded) {
        this.$set(backup, 'expanded', false)
        return
      }
      this.$set(backup, 'expanded', true)
      if (backup.files) return
      this.$set(backup, 'loadingFiles', true)
      try {
        const response = await fetch(`${API_BASE}/backup?hash=${encodeURIComponent(backup.hash)}`)
        if (!response.ok) throw new Error(response.statusText)
        const data = await response.json()
        this.$set(backup, 'files', data.files || [])
      } catch {
        this.$set(backup, 'files', [])
      } finally {
        this.$set(backup, 'loadingFiles', false)
      }
    }
  }
}
</script>
