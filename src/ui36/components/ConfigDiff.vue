<template>
  <v-card-text>
    <div v-if="loading" class="text-center pa-8">
      <v-progress-circular indeterminate color="primary" />
      <div class="mt-2">Loading changes...</div>
    </div>

    <div v-else-if="changedFiles.length === 0" class="text-center pa-8">
      <v-icon large color="success">mdi-check-circle-outline</v-icon>
      <div class="mt-2 title">No changes detected</div>
      <div class="caption grey--text">
        Your printer config matches the reference configuration.
      </div>
    </div>

    <div v-else>
      <v-toolbar flat dense class="mb-4">
        <v-chip small class="mr-2" color="warning" outlined>
          {{ changedFiles.length }} file{{ changedFiles.length !== 1 ? 's' : '' }} changed
        </v-chip>
        <v-chip v-if="selectionState.excludedFiles > 0" small class="mr-2" outlined>
          {{ selectionState.excludedFiles }} excluded
        </v-chip>
        <v-chip v-if="selectionState.partialFiles > 0" small class="mr-2" color="primary" outlined>
          {{ selectionState.partialFiles }} partial
        </v-chip>
        <v-spacer />
        <v-btn x-small text class="mr-1" @click="selectAllFiles">Select all files</v-btn>
        <v-btn x-small text class="mr-2" @click="deselectAllFiles">Deselect all files</v-btn>
        <v-btn color="primary" small :disabled="applyDisabled" @click="emitApply">
          <v-icon left small>{{ isPartialApply ? 'mdi-check' : 'mdi-check-all' }}</v-icon>
          {{ applyButtonLabel }}
        </v-btn>
      </v-toolbar>

      <v-expansion-panels v-model="expandedPanels" multiple>
        <v-expansion-panel v-for="file in changedFiles" :key="file.file">
          <v-expansion-panel-header @click="loadFileDetail(file)">
            <div class="d-flex align-center">
              <!-- Clicks must not reach the header, which toggles the panel -->
              <div v-if="file.status !== 'extra'" class="mr-2" @click.stop>
                <v-checkbox
                  :input-value="fileChecked(file)"
                  :indeterminate="fileIsPartial(file)"
                  :title="fileChecked(file) ? 'Exclude this file from the apply' : 'Include this file in the apply'"
                  dense
                  hide-details
                  class="mt-0 pt-0"
                  @change="setFileSelected(file, $event)"
                />
              </div>
              <v-icon small :color="fileStatusColor(file.status)" class="mr-2">
                {{ fileStatusIcon(file.status) }}
              </v-icon>
              <span class="font-weight-medium" :class="{ 'file-excluded': !fileChecked(file) && file.status !== 'extra' }">
                {{ file.file }}
              </span>
              <v-chip x-small class="ml-2" :color="fileStatusColor(file.status)" outlined>
                {{ file.status }}
              </v-chip>
              <span v-if="file.hunks" class="ml-2 caption grey--text">
                {{ file.hunks.length }} change{{ file.hunks.length !== 1 ? 's' : '' }}
              </span>
              <v-chip
                v-if="file.status !== 'extra' && !fileChecked(file)"
                x-small
                class="ml-2"
                outlined
              >
                excluded
              </v-chip>
              <v-chip v-else-if="fileIsPartial(file)" x-small class="ml-2" color="primary" outlined>
                {{ selectedHunkCount(file) }} of {{ file.hunks.length }} selected
              </v-chip>
            </div>
          </v-expansion-panel-header>

          <v-expansion-panel-content>
            <div v-if="file.loadingDetail" class="text-center pa-4">
              <v-progress-circular indeterminate size="24" />
            </div>

            <div v-else-if="file.hunks && file.hunks.length > 0">
              <!-- Missing file: show info + create button above content -->
              <div v-if="file.status === 'missing'" class="pa-4 pb-2">
                <v-alert type="info" dense outlined>
                  This file exists in the reference config but not on the printer.
                </v-alert>
                <v-btn small color="primary" @click="$emit('apply-file', file.file)">
                  <v-icon left small>mdi-file-plus</v-icon>
                  Create File
                </v-btn>
              </div>
              <!-- Modified file: hunk selection toolbar -->
              <v-toolbar v-else flat dense class="mb-2">
                <!-- Hunk picking is inert while the whole file is excluded -->
                <v-btn x-small text :disabled="file.selected === false" @click="selectAllHunks(file)">
                  Select all
                </v-btn>
                <v-btn x-small text :disabled="file.selected === false" @click="deselectAllHunks(file)">
                  Deselect all
                </v-btn>
                <v-spacer />
                <v-btn
                  v-if="selectedHunkCount(file) > 0 && selectedHunkCount(file) < file.hunks.length"
                  small
                  color="primary"
                  @click="emitApplyHunks(file)"
                >
                  <v-icon left small>mdi-check</v-icon>
                  Apply {{ selectedHunkCount(file) }} of {{ file.hunks.length }} changes
                </v-btn>
                <v-btn v-else small color="primary" @click="$emit('apply-file', file.file)">
                  <v-icon left small>mdi-check</v-icon>
                  Apply File
                </v-btn>
              </v-toolbar>

              <div class="diff-file-block">
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
                      <th class="diff-col-header diff-col-left">Current (Printer)</th>
                      <th class="diff-col-header diff-col-linenum diff-col-right" />
                      <th class="diff-col-header diff-col-right">{{ file.status === 'missing' ? 'New File Content' : 'Reference (New)' }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="(hunk, hunkIdx) in file.hunks">
                      <tr :key="'sep-' + hunk.index" class="hunk-separator-row">
                        <td colspan="4" class="hunk-separator">
                          <div class="d-flex align-center">
                            <v-checkbox
                              v-if="file.status !== 'missing'"
                              v-model="hunk.selected"
                              :disabled="file.selected === false"
                              dense
                              hide-details
                              class="mt-0 pt-0 mr-2"
                            />
                            <v-icon x-small class="mr-1 hunk-fold-icon">mdi-dots-vertical</v-icon>
                            <code class="hunk-range">{{ hunk.header }}</code>
                            <span v-if="hunk.summary" class="ml-2 caption grey--text">{{ hunk.summary }}</span>
                            <span v-if="skippedLinesBetween(file, hunkIdx) > 0" class="ml-2 caption grey--text text--darken-1">
                              ({{ skippedLinesBetween(file, hunkIdx) }} lines hidden)
                            </span>
                          </div>
                        </td>
                      </tr>
                      <tr v-for="(row, i) in sideBySideLines(hunk)" :key="'line-' + hunk.index + '-' + i">
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
            </div>

            <div v-else-if="file.status === 'missing'" class="pa-4">
              <v-alert type="info" dense outlined>
                This file exists in the reference config but not on the printer.
              </v-alert>
              <v-btn small color="primary" @click="$emit('apply-file', file.file)">
                <v-icon left small>mdi-file-plus</v-icon>
                Create File
              </v-btn>
            </div>

            <div v-else-if="file.status === 'extra'" class="pa-4">
              <v-alert type="warning" dense outlined>
                This file exists on the printer but not in the reference config.
              </v-alert>
            </div>
          </v-expansion-panel-content>
        </v-expansion-panel>
      </v-expansion-panels>
    </div>
  </v-card-text>
</template>

<script>
'use strict'

import { toRef } from 'vue'
import { useConfigDiff } from '../../core/useConfigDiff'

export default {
  name: 'ConfigDiff',
  props: {
    files: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  setup(props, { emit }) {
    return useConfigDiff(toRef(props, 'files'), emit)
  }
}
</script>

<style scoped>
.file-excluded {
  text-decoration: line-through;
  opacity: 0.6;
}
.diff-file-block {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
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
/* Line number gutter */
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
/* Separator between hunks */
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
/* Content cells */
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
</style>
