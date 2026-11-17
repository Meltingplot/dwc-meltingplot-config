<template>
  <v-card-text>
    <v-toolbar flat density="compact" class="mb-4 bg-transparent">
      <v-toolbar-title class="text-subtitle-1">Backup History</v-toolbar-title>
      <v-spacer />
      <v-btn
        size="small"
        color="primary"
        class="mr-2"
        prepend-icon="mdi-content-save"
        :loading="creatingBackup"
        @click="createBackup()"
      >
        Create Backup
      </v-btn>
      <v-btn size="small" variant="text" prepend-icon="mdi-refresh" @click="emit('refresh')">
        Refresh
      </v-btn>
    </v-toolbar>

    <div v-if="loading" class="text-center pa-8">
      <v-progress-circular indeterminate color="primary" />
      <div class="mt-2">Loading backups...</div>
    </div>

    <div v-else-if="backups.length === 0" class="text-center pa-8">
      <v-icon size="large" color="grey">mdi-history</v-icon>
      <div class="mt-2 text-h6">No backups yet</div>
      <div class="text-caption text-medium-emphasis">
        Backups are created automatically when config changes are applied.
      </div>
    </div>

    <v-list v-else lines="two">
      <template v-for="(backup, index) in backups" :key="backup.hash">
        <v-list-item @click="toggleExpand(backup)">
          <template #prepend>
            <v-icon>mdi-source-commit</v-icon>
          </template>

          <v-list-item-title>{{ backup.message }}</v-list-item-title>
          <v-list-item-subtitle>
            <v-icon size="x-small" class="mr-1">mdi-clock-outline</v-icon>
            {{ backup.timestamp }}
            <span v-if="backup.filesChanged" class="ml-2">
              <v-icon size="x-small" class="mr-1">mdi-file-multiple</v-icon>
              {{ backup.filesChanged }} file{{ backup.filesChanged !== 1 ? 's' : '' }}
            </span>
            <span class="ml-2 text-caption">{{ backup.hash.substring(0, 8) }}</span>
          </v-list-item-subtitle>

          <template #append>
            <v-btn
              icon="mdi-download"
              size="small"
              variant="text"
              title="Download backup"
              @click.stop="emit('download', backup.hash)"
            />
            <v-btn
              icon="mdi-backup-restore"
              size="small"
              variant="text"
              title="Restore this backup"
              @click.stop="emit('restore', backup.hash)"
            />
            <v-btn
              icon="mdi-delete"
              size="small"
              variant="text"
              color="error"
              title="Delete backup"
              @click.stop="emit('delete', backup.hash)"
            />
          </template>
        </v-list-item>

        <v-expand-transition>
          <div v-if="backup.expanded" class="px-4 pb-4">
            <div v-if="backup.loadingFiles" class="text-center pa-4">
              <v-progress-circular indeterminate size="24" />
            </div>

            <div v-else-if="displayFiles(backup).length > 0" class="backup-detail-panel">
              <v-row no-gutters>
                <!-- File tree (left) -->
                <v-col cols="12" sm="4" md="3" class="backup-tree-col">
                  <div class="backup-tree-header text-caption font-weight-medium pa-2">
                    {{ backup.isFullBackup ? 'Files' : 'Changed Files' }}
                  </div>
                  <v-treeview
                    v-model:activated="backup.activeNodes"
                    :items="buildFileTree(displayFiles(backup))"
                    item-value="id"
                    item-title="name"
                    item-children="children"
                    density="compact"
                    open-all
                    activatable
                    @update:activated="onFileSelected(backup, $event)"
                  >
                    <template #prepend="{ item }">
                      <v-icon
                        size="small"
                        :color="item.children ? 'amber-darken-2' : 'blue-grey'"
                      >
                        {{ item.children ? 'mdi-folder' : 'mdi-file-document-outline' }}
                      </v-icon>
                    </template>
                  </v-treeview>
                </v-col>

                <!-- File viewer (right) -->
                <v-col cols="12" sm="8" md="9" class="backup-diff-col">
                  <div v-if="backup.loadingDiff" class="text-center pa-8">
                    <v-progress-circular indeterminate size="24" />
                    <div class="mt-2 text-caption">Loading...</div>
                  </div>

                  <div v-else-if="backup.fileDiff || backup.fileContent">
                    <div class="backup-diff-file-header d-flex align-center flex-wrap pa-2">
                      <v-icon size="small" class="mr-2">mdi-file-document-outline</v-icon>
                      <code class="backup-diff-filename">{{ backup.selectedFile }}</code>
                      <v-chip
                        v-if="backup.fileDiff && backup.viewMode === 'diff'"
                        size="x-small"
                        class="ml-2"
                        :color="diffStatusColor(backup.fileDiff.status)"
                        variant="outlined"
                      >
                        {{ backup.fileDiff.status }}
                      </v-chip>
                      <v-spacer />
                      <v-btn-toggle
                        :model-value="backup.viewMode"
                        density="compact"
                        mandatory
                        class="mr-1"
                        @update:model-value="switchViewMode(backup, $event)"
                      >
                        <v-btn size="x-small" value="content" title="File content">
                          <v-icon size="x-small" class="mr-1">mdi-file-document</v-icon>
                          Content
                        </v-btn>
                        <v-btn size="x-small" value="diff" title="Changes diff">
                          <v-icon size="x-small" class="mr-1">mdi-file-compare</v-icon>
                          Diff
                        </v-btn>
                      </v-btn-toggle>
                    </div>

                    <!-- Content view -->
                    <div v-if="backup.viewMode === 'content'" class="file-content-block">
                      <div v-if="backup.fileContent && backup.fileContent.content !== null">
                        <table class="content-table">
                          <tbody>
                            <tr
                              v-for="(line, i) in backup.fileContent.content.split('\n')"
                              :key="'cline-' + backup.hash + '-' + i"
                            >
                              <td class="content-linenum">
                                <code>{{ i + 1 }}</code>
                              </td>
                              <td class="content-cell">
                                <code>{{ line }}</code>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div v-else class="text-center pa-8 text-caption text-medium-emphasis">
                        File not found in this backup.
                      </div>
                    </div>

                    <!-- Diff view -->
                    <div v-else-if="backup.fileDiff">
                      <div
                        v-if="backup.fileDiff.hunks && backup.fileDiff.hunks.length > 0"
                        class="diff-file-block"
                      >
                        <table class="diff-table">
                          <colgroup>
                            <col class="col-linenum">
                            <col class="col-content">
                            <col class="col-linenum">
                            <col class="col-content">
                          </colgroup>
                          <thead>
                            <tr>
                              <th class="diff-col-header diff-col-linenum diff-col-left" />
                              <th class="diff-col-header diff-col-left">Before</th>
                              <th class="diff-col-header diff-col-linenum diff-col-right" />
                              <th class="diff-col-header diff-col-right">After</th>
                            </tr>
                          </thead>
                          <tbody>
                            <template
                              v-for="hunk in backup.fileDiff.hunks"
                              :key="'bhunk-' + backup.hash + '-' + hunk.index"
                            >
                              <tr class="hunk-separator-row">
                                <td colspan="4" class="hunk-separator">
                                  <div class="d-flex align-center">
                                    <v-icon size="x-small" class="mr-1 hunk-fold-icon">
                                      mdi-dots-vertical
                                    </v-icon>
                                    <code class="hunk-range">{{ hunk.header }}</code>
                                    <span
                                      v-if="hunk.summary"
                                      class="ml-2 text-caption text-medium-emphasis"
                                    >
                                      {{ hunk.summary }}
                                    </span>
                                  </div>
                                </td>
                              </tr>
                              <tr
                                v-for="(row, i) in sideBySideLines(hunk)"
                                :key="'bline-' + backup.hash + '-' + hunk.index + '-' + i"
                              >
                                <td :class="['diff-linenum', row.leftClass]">
                                  <code v-if="row.leftLine !== null">{{ row.leftLine }}</code>
                                </td>
                                <td :class="['diff-cell', row.leftClass]">
                                  <code v-if="row.left !== null">{{ row.left }}</code>
                                </td>
                                <td :class="['diff-linenum', row.rightClass]">
                                  <code v-if="row.rightLine !== null">{{ row.rightLine }}</code>
                                </td>
                                <td :class="['diff-cell', row.rightClass]">
                                  <code v-if="row.right !== null">{{ row.right }}</code>
                                </td>
                              </tr>
                            </template>
                          </tbody>
                        </table>
                      </div>

                      <div v-else class="text-center pa-8 text-caption text-medium-emphasis">
                        No changes in this file.
                      </div>
                    </div>
                  </div>

                  <div v-else class="text-center pa-8">
                    <v-icon size="large" color="grey-lighten-1">mdi-file-search</v-icon>
                    <div class="mt-2 text-caption text-medium-emphasis">
                      Select a file to view changes
                    </div>
                  </div>
                </v-col>
              </v-row>
            </div>

            <div v-else class="text-center pa-4 text-caption text-medium-emphasis">
              No files in this backup.
            </div>
          </div>
        </v-expand-transition>

        <v-divider v-if="index < backups.length - 1" />
      </template>
    </v-list>
  </v-card-text>
</template>

<script setup lang="ts">
import { toRef } from "vue";

import { type Backup, useBackupHistory } from "../../core/useBackupHistory";

const props = withDefaults(
  defineProps<{
    backups?: Array<Backup>;
    loading?: boolean;
  }>(),
  { backups: () => [], loading: false }
);

const emit = defineEmits<{
  (e: "restore", hash: string): void;
  (e: "download", hash: string): void;
  (e: "delete", hash: string): void;
  (e: "refresh"): void;
  (e: "notify", payload: { text: string; color: string }): void;
}>();

const {
  creatingBackup,
  buildFileTree,
  displayFiles,
  diffStatusColor,
  sideBySideLines,
  createBackup,
  toggleExpand,
  onFileSelected,
  switchViewMode,
} = useBackupHistory(toRef(props, "backups"), emit);
</script>

<style scoped>
/* --- Tree + Diff split layout --- */
.backup-detail-panel {
  border: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  border-radius: 4px;
  overflow: hidden;
}
.backup-tree-col {
  border-right: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  background-color: rgba(var(--v-theme-on-surface), 0.03);
  min-height: 200px;
  max-height: 500px;
  overflow-y: auto;
}
.backup-tree-header {
  border-bottom: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 0.75em;
  opacity: 0.7;
}
.backup-diff-col {
  min-height: 200px;
  max-height: 500px;
  overflow-y: auto;
}
.backup-diff-file-header {
  border-bottom: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  background-color: rgba(var(--v-theme-on-surface), 0.03);
}
.backup-diff-filename {
  font-size: 0.85em;
  color: rgb(var(--v-theme-primary));
}

/* --- Diff table (mirrors ConfigDiff) --- */
.diff-file-block {
  border-top: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  overflow-x: auto;
}
.hunk-range {
  font-size: 0.8em;
  color: rgb(var(--v-theme-primary));
}
.diff-table,
.content-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 0.85em;
  line-height: 1.5;
}
.col-linenum {
  width: 48px;
}
.col-content {
  width: calc(50% - 48px);
}
.diff-col-header {
  padding: 4px 8px;
  font-size: 0.8em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 2px solid rgb(var(--v-border-color), var(--v-border-opacity));
}
.diff-col-linenum {
  width: 48px;
  text-align: center;
}
.diff-col-left {
  background-color: rgba(var(--v-theme-warning), 0.12);
  color: rgb(var(--v-theme-warning));
  border-right: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
}
.diff-col-right {
  background-color: rgba(var(--v-theme-success), 0.12);
  color: rgb(var(--v-theme-success));
}
.diff-linenum {
  width: 48px;
  padding: 1px 6px;
  text-align: right;
  vertical-align: top;
  user-select: none;
  opacity: 0.6;
}
.diff-linenum code {
  font-size: 0.8em;
  white-space: nowrap;
}
.hunk-separator-row td {
  border-top: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  border-bottom: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
}
.hunk-separator {
  background-color: rgba(var(--v-theme-primary), 0.06);
  padding: 4px 8px;
}
.hunk-fold-icon {
  color: rgb(var(--v-theme-primary));
}
.diff-cell {
  padding: 1px 8px;
  vertical-align: top;
}
.diff-cell code {
  white-space: pre;
  font-size: inherit;
  word-break: break-all;
}
.diff-remove {
  background-color: rgba(var(--v-theme-error), 0.12);
}
.diff-cell.diff-remove code {
  color: rgb(var(--v-theme-error));
}
.diff-add {
  background-color: rgba(var(--v-theme-success), 0.12);
}
.diff-cell.diff-add code {
  color: rgb(var(--v-theme-success));
}
.diff-context,
.diff-empty {
  background-color: rgba(var(--v-theme-on-surface), 0.03);
}
.diff-linenum.diff-remove,
.diff-linenum.diff-context,
.diff-linenum.diff-empty,
.diff-cell.diff-remove,
.diff-cell.diff-context,
.diff-cell.diff-empty {
  border-right: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
}

/* --- File content table --- */
.file-content-block {
  border-top: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  overflow-x: auto;
}
.content-linenum {
  width: 56px;
  padding: 1px 8px 1px 4px;
  text-align: right;
  vertical-align: top;
  border-right: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  background-color: rgba(var(--v-theme-on-surface), 0.03);
  user-select: none;
  opacity: 0.6;
}
.content-linenum code {
  font-size: 0.8em;
  white-space: nowrap;
}
.content-cell {
  padding: 1px 8px;
  vertical-align: top;
}
.content-cell code {
  white-space: pre;
  font-size: inherit;
  word-break: break-all;
}
</style>
