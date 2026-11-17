<template>
  <v-card-text>
    <div v-if="loading" class="text-center pa-8">
      <v-progress-circular indeterminate color="primary" />
      <div class="mt-2">Loading changes...</div>
    </div>

    <div v-else-if="changedFiles.length === 0" class="text-center pa-8">
      <v-icon size="large" color="success">mdi-check-circle-outline</v-icon>
      <div class="mt-2 text-h6">No changes detected</div>
      <div class="text-caption text-medium-emphasis">
        Your printer config matches the reference configuration.
      </div>
    </div>

    <div v-else>
      <v-toolbar flat density="compact" class="mb-4 bg-transparent">
        <v-chip size="small" class="mr-2" color="warning" variant="outlined">
          {{ changedFiles.length }} file{{ changedFiles.length !== 1 ? 's' : '' }} changed
        </v-chip>
        <v-chip v-if="selectionState.excludedFiles > 0" size="small" class="mr-2" variant="outlined">
          {{ selectionState.excludedFiles }} excluded
        </v-chip>
        <v-chip v-if="selectionState.partialFiles > 0" size="small" class="mr-2" color="primary" variant="outlined">
          {{ selectionState.partialFiles }} partial
        </v-chip>
        <v-spacer />
        <v-btn size="x-small" variant="text" class="mr-1" @click="selectAllFiles()">Select all files</v-btn>
        <v-btn size="x-small" variant="text" class="mr-2" @click="deselectAllFiles()">Deselect all files</v-btn>
        <v-btn
          color="primary"
          size="small"
          :prepend-icon="isPartialApply ? 'mdi-check' : 'mdi-check-all'"
          :disabled="applyDisabled"
          @click="emitApply()"
        >
          {{ applyButtonLabel }}
        </v-btn>
      </v-toolbar>

      <v-expansion-panels v-model="expandedPanels" multiple>
        <v-expansion-panel v-for="file in changedFiles" :key="file.file">
          <v-expansion-panel-title @click="loadFileDetail(file)">
            <div class="d-flex align-center flex-wrap">
              <!-- Clicks must not reach the title, which toggles the panel -->
              <div v-if="file.status !== 'extra'" class="mr-2" @click.stop>
                <v-checkbox
                  :model-value="fileChecked(file)"
                  :indeterminate="fileIsPartial(file)"
                  :title="fileChecked(file) ? 'Exclude this file from the apply' : 'Include this file in the apply'"
                  density="compact"
                  hide-details
                  @update:model-value="setFileSelected(file, $event)"
                />
              </div>
              <v-icon size="small" :color="fileStatusColor(file.status)" class="mr-2">
                {{ fileStatusIcon(file.status) }}
              </v-icon>
              <span
                class="font-weight-medium"
                :class="{ 'file-excluded': !fileChecked(file) && file.status !== 'extra' }"
              >
                {{ file.file }}
              </span>
              <v-chip size="x-small" class="ml-2" :color="fileStatusColor(file.status)" variant="outlined">
                {{ file.status }}
              </v-chip>
              <span v-if="file.hunks" class="ml-2 text-caption text-medium-emphasis">
                {{ file.hunks.length }} change{{ file.hunks.length !== 1 ? 's' : '' }}
              </span>
              <v-chip
                v-if="file.status !== 'extra' && !fileChecked(file)"
                size="x-small"
                class="ml-2"
                variant="outlined"
              >
                excluded
              </v-chip>
              <v-chip
                v-else-if="fileIsPartial(file)"
                size="x-small"
                class="ml-2"
                color="primary"
                variant="outlined"
              >
                {{ selectedHunkCount(file) }} of {{ file.hunks?.length }} selected
              </v-chip>
            </div>
          </v-expansion-panel-title>

          <v-expansion-panel-text>
            <div v-if="file.loadingDetail" class="text-center pa-4">
              <v-progress-circular indeterminate size="24" />
            </div>

            <div v-else-if="file.hunks && file.hunks.length > 0">
              <!-- Missing file: show info + create button above content -->
              <div v-if="file.status === 'missing'" class="pa-4 pb-2">
                <v-alert type="info" variant="tonal" density="compact" class="mb-2">
                  This file exists in the reference config but not on the printer.
                </v-alert>
                <v-btn
                  size="small"
                  color="primary"
                  prepend-icon="mdi-file-plus"
                  @click="emit('apply-file', file.file)"
                >
                  Create File
                </v-btn>
              </div>
              <!-- Modified file: hunk selection toolbar -->
              <v-toolbar v-else flat density="compact" class="mb-2 bg-transparent">
                <!-- Hunk picking is inert while the whole file is excluded -->
                <v-btn
                  size="x-small"
                  variant="text"
                  :disabled="file.selected === false"
                  @click="selectAllHunks(file)"
                >
                  Select all
                </v-btn>
                <v-btn
                  size="x-small"
                  variant="text"
                  :disabled="file.selected === false"
                  @click="deselectAllHunks(file)"
                >
                  Deselect all
                </v-btn>
                <v-spacer />
                <v-btn
                  v-if="selectedHunkCount(file) > 0 && selectedHunkCount(file) < file.hunks.length"
                  size="small"
                  color="primary"
                  prepend-icon="mdi-check"
                  @click="emitApplyHunks(file)"
                >
                  Apply {{ selectedHunkCount(file) }} of {{ file.hunks.length }} changes
                </v-btn>
                <v-btn
                  v-else
                  size="small"
                  color="primary"
                  prepend-icon="mdi-check"
                  @click="emit('apply-file', file.file)"
                >
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
                      <th class="diff-col-header diff-col-right">
                        {{ file.status === 'missing' ? 'New File Content' : 'Reference (New)' }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="(hunk, hunkIdx) in file.hunks" :key="'hunk-' + hunk.index">
                      <tr class="hunk-separator-row">
                        <td colspan="4" class="hunk-separator">
                          <div class="d-flex align-center">
                            <v-checkbox
                              v-if="file.status !== 'missing'"
                              v-model="hunk.selected"
                              :disabled="file.selected === false"
                              density="compact"
                              hide-details
                              class="mr-2"
                            />
                            <v-icon size="x-small" class="mr-1 hunk-fold-icon">mdi-dots-vertical</v-icon>
                            <code class="hunk-range">{{ hunk.header }}</code>
                            <span v-if="hunk.summary" class="ml-2 text-caption text-medium-emphasis">
                              {{ hunk.summary }}
                            </span>
                            <span
                              v-if="skippedLinesBetween(file, hunkIdx) > 0"
                              class="ml-2 text-caption text-medium-emphasis"
                            >
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
              <v-alert type="info" variant="tonal" density="compact" class="mb-2">
                This file exists in the reference config but not on the printer.
              </v-alert>
              <v-btn
                size="small"
                color="primary"
                prepend-icon="mdi-file-plus"
                @click="emit('apply-file', file.file)"
              >
                Create File
              </v-btn>
            </div>

            <div v-else-if="file.status === 'extra'" class="pa-4">
              <v-alert type="warning" variant="tonal" density="compact">
                This file exists on the printer but not in the reference config.
              </v-alert>
            </div>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </div>
  </v-card-text>
</template>

<script setup lang="ts">
import { toRef } from "vue";

import type { DiffFile } from "../../core/diff";
import { useConfigDiff } from "../../core/useConfigDiff";

const props = withDefaults(
  defineProps<{
    files?: Array<DiffFile>;
    loading?: boolean;
  }>(),
  { files: () => [], loading: false }
);

const emit = defineEmits<{
  (e: "apply-all"): void;
  (e: "apply-file", file: string): void;
  (e: "apply-hunks", payload: { file: string; hunks: Array<number> }): void;
  (e: "apply-selection", payload: { files: Array<object>; excludedFiles: number; partialFiles: number }): void;
}>();

const {
  expandedPanels,
  changedFiles,
  selectionState,
  isPartialApply,
  applyButtonLabel,
  applyDisabled,
  fileStatusColor,
  fileStatusIcon,
  skippedLinesBetween,
  sideBySideLines,
  fileChecked,
  fileIsPartial,
  selectedHunkCount,
  loadFileDetail,
  setFileSelected,
  selectAllFiles,
  deselectAllFiles,
  selectAllHunks,
  deselectAllHunks,
  emitApply,
  emitApplyHunks,
} = useConfigDiff(toRef(props, "files"), emit);
</script>

<style scoped>
.file-excluded {
  text-decoration: line-through;
  opacity: 0.6;
}
.diff-file-block {
  border: 1px solid rgb(var(--v-border-color), var(--v-border-opacity));
  border-radius: 4px;
  overflow-x: auto;
}
.hunk-range {
  font-size: 0.8em;
  color: rgb(var(--v-theme-primary));
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
/* Line number gutter */
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
/* Separator between hunks */
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
/* Content cells */
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
</style>
