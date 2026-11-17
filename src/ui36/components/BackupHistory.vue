<template>
  <v-card-text>
    <v-toolbar flat dense class="mb-4">
      <v-toolbar-title class="subtitle-1">Backup History</v-toolbar-title>
      <v-spacer />
      <v-btn small color="primary" class="mr-2" :loading="creatingBackup" @click="createBackup">
        <v-icon left small>mdi-content-save</v-icon>
        Create Backup
      </v-btn>
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
              <span class="ml-2 caption">{{ backup.hash.substring(0, 8) }}</span>
            </v-list-item-subtitle>
          </v-list-item-content>

          <v-list-item-action class="flex-row">
            <v-btn icon small title="Download backup" @click.stop="$emit('download', backup.hash)">
              <v-icon small>mdi-download</v-icon>
            </v-btn>
            <v-btn icon small title="Restore this backup" @click.stop="$emit('restore', backup.hash)">
              <v-icon small>mdi-backup-restore</v-icon>
            </v-btn>
            <v-btn icon small title="Delete backup" @click.stop="$emit('delete', backup.hash)">
              <v-icon small color="error">mdi-delete</v-icon>
            </v-btn>
          </v-list-item-action>
        </v-list-item>

        <v-expand-transition :key="backup.hash + '-detail'">
          <div v-if="backup.expanded" class="px-4 pb-4">
            <div v-if="backup.loadingFiles" class="text-center pa-4">
              <v-progress-circular indeterminate size="24" />
            </div>

            <div v-else-if="displayFiles(backup).length > 0" class="backup-detail-panel">
              <v-row no-gutters>
                <!-- File tree (left) -->
                <v-col cols="3" class="backup-tree-col">
                  <div class="backup-tree-header caption font-weight-medium pa-2">
                    {{ backup.isFullBackup ? 'Files' : 'Changed Files' }}
                  </div>
                  <v-treeview
                    :items="buildFileTree(displayFiles(backup))"
                    item-key="id"
                    dense
                    open-all
                    activatable
                    :active.sync="backup.activeNodes"
                    @update:active="onFileSelected(backup, $event)"
                  >
                    <template #prepend="{ item }">
                      <v-icon small :color="item.children ? 'amber darken-2' : 'blue-grey'">
                        {{ item.children ? 'mdi-folder' : 'mdi-file-document-outline' }}
                      </v-icon>
                    </template>
                    <template #label="{ item }">
                      <span class="backup-tree-label">{{ item.name }}</span>
                    </template>
                  </v-treeview>
                </v-col>

                <!-- File viewer (right) -->
                <v-col cols="9" class="backup-diff-col">
                  <div v-if="backup.loadingDiff" class="text-center pa-8">
                    <v-progress-circular indeterminate size="24" />
                    <div class="mt-2 caption">Loading...</div>
                  </div>

                  <div v-else-if="backup.fileDiff || backup.fileContent" class="backup-diff-viewer">
                    <div class="backup-diff-file-header d-flex align-center pa-2">
                      <v-icon small class="mr-2">mdi-file-document-outline</v-icon>
                      <code class="backup-diff-filename">{{ backup.selectedFile }}</code>
                      <v-chip
                        v-if="backup.fileDiff && backup.viewMode === 'diff'"
                        x-small class="ml-2"
                        :color="diffStatusColor(backup.fileDiff.status)" outlined
                      >
                        {{ backup.fileDiff.status }}
                      </v-chip>
                      <v-spacer />
                      <v-btn-toggle
                        :value="backup.viewMode || 'diff'"
                        dense mandatory class="mr-1"
                        @change="switchViewMode(backup, $event)"
                      >
                        <v-btn x-small value="content" title="File content">
                          <v-icon x-small class="mr-1">mdi-file-document</v-icon>
                          Content
                        </v-btn>
                        <v-btn x-small value="diff" title="Changes diff">
                          <v-icon x-small class="mr-1">mdi-file-compare</v-icon>
                          Diff
                        </v-btn>
                      </v-btn-toggle>
                    </div>

                    <!-- Content view -->
                    <div v-if="(backup.viewMode || 'diff') === 'content'" class="file-content-block">
                      <div v-if="backup.loadingContent" class="text-center pa-8">
                        <v-progress-circular indeterminate size="24" />
                        <div class="mt-2 caption">Loading file content...</div>
                      </div>
                      <div v-else-if="backup.fileContent && backup.fileContent.content !== null">
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
                      <div v-else class="text-center pa-8 caption grey--text">
                        File not found in this backup.
                      </div>
                    </div>

                    <!-- Diff view -->
                    <div v-else-if="backup.fileDiff">
                      <div v-if="backup.fileDiff.hunks && backup.fileDiff.hunks.length > 0" class="diff-file-block">
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
                            <template v-for="hunk in backup.fileDiff.hunks">
                              <tr :key="'bsep-' + backup.hash + '-' + hunk.index" class="hunk-separator-row">
                                <td colspan="4" class="hunk-separator">
                                  <div class="d-flex align-center">
                                    <v-icon x-small class="mr-1 hunk-fold-icon">mdi-dots-vertical</v-icon>
                                    <code class="hunk-range">{{ hunk.header }}</code>
                                    <span v-if="hunk.summary" class="ml-2 caption grey--text">{{ hunk.summary }}</span>
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

                      <div v-else class="text-center pa-8 caption grey--text">
                        No changes in this file.
                      </div>
                    </div>
                  </div>

                  <div v-else class="text-center pa-8">
                    <v-icon large color="grey lighten-1">mdi-file-search</v-icon>
                    <div class="mt-2 caption grey--text">Select a file to view changes</div>
                  </div>
                </v-col>
              </v-row>
            </div>

            <div v-else-if="displayFiles(backup).length === 0" class="text-center pa-4 caption grey--text">
              No files in this backup.
            </div>
          </div>
        </v-expand-transition>

        <v-divider v-if="index < backups.length - 1" :key="'d-' + backup.hash" />
      </template>
    </v-list>
  </v-card-text>
</template>

<script>
'use strict'

import { toRef } from 'vue'
import { useBackupHistory } from '../../core/useBackupHistory'

export default {
  name: 'BackupHistory',
  props: {
    backups: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  setup(props, { emit }) {
    return useBackupHistory(toRef(props, 'backups'), emit)
  }
}
</script>

<style scoped>
/* --- Tree + Diff split layout --- */
.backup-detail-panel {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  overflow: hidden;
}
.backup-tree-col {
  border-right: 1px solid #e0e0e0;
  background-color: #fafafa;
  min-height: 200px;
  max-height: 500px;
  overflow-y: auto;
}
.backup-tree-header {
  border-bottom: 1px solid #e0e0e0;
  background-color: #f5f5f5;
  color: #616161;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 0.75em;
}
.backup-tree-label {
  font-size: 0.85em;
}
.backup-diff-col {
  min-height: 200px;
  max-height: 500px;
  overflow-y: auto;
}
.backup-diff-file-header {
  border-bottom: 1px solid #e0e0e0;
  background-color: #f5f5f5;
}
.backup-diff-filename {
  font-size: 0.85em;
  color: #1565c0;
}

/* --- Diff table (shared with ConfigDiff) --- */
.diff-file-block {
  border-top: 1px solid #e0e0e0;
  overflow: hidden;
}
.hunk-range {
  font-size: 0.8em;
  color: #7b1fa2;
}
.diff-table {
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
  border-bottom: 2px solid #e0e0e0;
}
.diff-col-linenum {
  width: 48px;
  text-align: center;
}
.diff-col-left {
  background-color: #fff3e0;
  color: #e65100;
  border-right: 1px solid #e0e0e0;
}
.diff-col-right {
  background-color: #e8f5e9;
  color: #1b5e20;
}
.diff-linenum {
  width: 48px;
  padding: 1px 6px;
  text-align: right;
  vertical-align: top;
  border-bottom: 1px solid #f0f0f0;
  user-select: none;
}
.diff-linenum code {
  font-size: 0.8em;
  color: #9e9e9e;
  white-space: nowrap;
}
.diff-linenum.diff-remove {
  background-color: #fce4ec;
  border-right: 1px solid #e0e0e0;
}
.diff-linenum.diff-add {
  background-color: #e0f2e9;
}
.diff-linenum.diff-context {
  background-color: #f5f5f5;
  border-right: 1px solid #e0e0e0;
}
.diff-linenum.diff-empty {
  background-color: #f5f5f5;
  border-right: 1px solid #e0e0e0;
}
.hunk-separator-row td {
  border-top: 1px solid #e0e0e0;
  border-bottom: 1px solid #e0e0e0;
}
.hunk-separator {
  background-color: #f0f4ff;
  padding: 4px 8px;
}
.hunk-fold-icon {
  color: #7b1fa2;
}
.diff-cell {
  padding: 1px 8px;
  vertical-align: top;
  border-bottom: 1px solid #f0f0f0;
}
.diff-cell code {
  white-space: pre;
  font-size: inherit;
  word-break: break-all;
}
.diff-cell.diff-remove {
  background-color: #ffebee;
  border-right: 1px solid #e0e0e0;
}
.diff-cell.diff-remove code {
  color: #b71c1c;
}
.diff-cell.diff-add {
  background-color: #e8f5e9;
}
.diff-cell.diff-add code {
  color: #1b5e20;
}
.diff-cell.diff-context {
  background-color: #fafafa;
  border-right: 1px solid #e0e0e0;
  color: #616161;
}
.diff-cell.diff-context code {
  color: #616161;
}
.diff-cell.diff-empty {
  background-color: #f5f5f5;
  border-right: 1px solid #e0e0e0;
}

/* --- File content table --- */
.file-content-block {
  border-top: 1px solid #e0e0e0;
  overflow: hidden;
}
.content-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 0.85em;
  line-height: 1.5;
}
.content-linenum {
  width: 56px;
  padding: 1px 8px 1px 4px;
  text-align: right;
  vertical-align: top;
  border-bottom: 1px solid #f0f0f0;
  border-right: 1px solid #e0e0e0;
  background-color: #f5f5f5;
  user-select: none;
}
.content-linenum code {
  font-size: 0.8em;
  color: #9e9e9e;
  white-space: nowrap;
}
.content-cell {
  padding: 1px 8px;
  vertical-align: top;
  border-bottom: 1px solid #f0f0f0;
  background-color: #fafafa;
}
.content-cell code {
  white-space: pre;
  font-size: inherit;
  word-break: break-all;
  color: #212121;
}
</style>
