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

const API_BASE = '/machine/MeltingplotConfig'

const FILE_STATUS = {
  modified: { color: 'warning', icon: 'mdi-file-document-edit' },
  missing: { color: 'info', icon: 'mdi-file-plus' },
  extra: { color: 'grey', icon: 'mdi-file-question' }
}

export default {
  name: 'ConfigDiff',
  props: {
    files: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false }
  },
  data() {
    return {
      expandedPanels: []
    }
  },
  computed: {
    changedFiles() {
      return this.files.filter(f => f.status !== 'unchanged')
    },
    /**
     * What the top-level apply button would send, derived from the
     * per-file and per-hunk checkboxes.
     *
     * - files: payload entries — a bare { file } applies the whole file,
     *   { file, hunks } applies only the selected hunks of that file
     * - excludedFiles: files the user dropped completely
     * - partialFiles: files where only some hunks are selected
     */
    selectionState() {
      const files = []
      let excludedFiles = 0
      let partialFiles = 0

      for (const file of this.changedFiles) {
        // 'extra' files exist only on the printer — nothing to apply
        if (file.status === 'extra') continue

        if (!this.fileChecked(file)) {
          excludedFiles++
          continue
        }

        if (file.status === 'modified' && this.hasHunkDetail(file)) {
          const selected = file.hunks.filter(h => h.selected)
          if (selected.length < file.hunks.length) {
            partialFiles++
            files.push({ file: file.file, hunks: selected.map(h => h.index) })
            continue
          }
        }

        files.push({ file: file.file })
      }

      return { files, excludedFiles, partialFiles }
    },
    isPartialApply() {
      return this.selectionState.excludedFiles > 0 || this.selectionState.partialFiles > 0
    },
    applyButtonLabel() {
      return this.isPartialApply ? 'Partially Apply' : 'Apply All'
    },
    applyDisabled() {
      return this.selectionState.files.length === 0
    }
  },
  watch: {
    files: {
      handler(files) {
        this.expandedPanels = []
        // Everything starts selected; the user opts changes out.
        files.forEach(file => {
          if (file.selected === undefined) {
            this.$set(file, 'selected', true)
          }
        })
      },
      immediate: true
    }
  },
  methods: {
    fileStatusColor(status) {
      return (FILE_STATUS[status] || FILE_STATUS.modified).color
    },
    fileStatusIcon(status) {
      return (FILE_STATUS[status] || FILE_STATUS.modified).icon
    },
    parseHunkHeader(header) {
      if (!header) return null
      const m = header.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/)
      if (!m) return null
      return {
        oldStart: parseInt(m[1]),
        oldCount: m[2] !== undefined ? parseInt(m[2]) : 1,
        newStart: parseInt(m[3]),
        newCount: m[4] !== undefined ? parseInt(m[4]) : 1
      }
    },
    skippedLinesBetween(file, hunkIdx) {
      const curr = this.parseHunkHeader(file.hunks[hunkIdx].header)
      if (!curr) return 0
      if (hunkIdx === 0) {
        return curr.oldStart > 1 ? curr.oldStart - 1 : 0
      }
      const prev = this.parseHunkHeader(file.hunks[hunkIdx - 1].header)
      if (!prev) return 0
      return curr.oldStart - (prev.oldStart + prev.oldCount)
    },
    sideBySideLines(hunk) {
      if (!hunk.lines) return []
      const parsed = this.parseHunkHeader(hunk.header)
      let leftLine = parsed ? parsed.oldStart : 1
      let rightLine = parsed ? parsed.newStart : 1

      const rows = []
      const removes = []
      const adds = []

      const flushPairs = () => {
        const max = Math.max(removes.length, adds.length)
        for (let i = 0; i < max; i++) {
          rows.push({
            leftLine: i < removes.length ? leftLine + i : null,
            left: i < removes.length ? removes[i].substring(1) : null,
            leftClass: i < removes.length ? 'diff-remove' : 'diff-empty',
            rightLine: i < adds.length ? rightLine + i : null,
            right: i < adds.length ? adds[i].substring(1) : null,
            rightClass: i < adds.length ? 'diff-add' : 'diff-empty'
          })
        }
        leftLine += removes.length
        rightLine += adds.length
        removes.length = 0
        adds.length = 0
      }

      for (const line of hunk.lines) {
        if (line.startsWith('-')) {
          removes.push(line)
        } else if (line.startsWith('+')) {
          adds.push(line)
        } else {
          flushPairs()
          const text = line.startsWith(' ') ? line.substring(1) : line
          rows.push({
            leftLine: leftLine,
            left: text,
            leftClass: 'diff-context',
            rightLine: rightLine,
            right: text,
            rightClass: 'diff-context'
          })
          leftLine++
          rightLine++
        }
      }
      flushPairs()
      return rows
    },
    async loadFileDetail(file) {
      if (file.status !== 'modified' && file.status !== 'missing') return
      // diff_all returns summary hunks (index + header only).
      // Skip fetch only if full detail (lines) is already loaded.
      if (file.hunks && file.hunks.length > 0 && file.hunks[0].lines) return
      this.$set(file, 'loadingDetail', true)
      try {
        const response = await fetch(`${API_BASE}/diff?file=${encodeURIComponent(file.file)}`)
        if (!response.ok) throw new Error(response.statusText)
        const data = await response.json()
        const selected = file.selected !== false
        this.$set(file, 'hunks', (data.hunks || []).map(h => ({ ...h, selected })))
      } catch {
        this.$set(file, 'hunks', [])
      } finally {
        this.$set(file, 'loadingDetail', false)
      }
    },
    hasHunkDetail(file) {
      // diff_all returns summary hunks (index + header); only detail
      // hunks carry `lines` and therefore a usable `selected` flag.
      return !!(file.hunks && file.hunks.length > 0 && file.hunks[0].lines)
    },
    fileChecked(file) {
      if (file.selected === false) return false
      if (file.status === 'modified' && this.hasHunkDetail(file)) {
        // Deselecting every hunk drops the file just like unchecking it
        return file.hunks.some(h => h.selected)
      }
      return true
    },
    fileIsPartial(file) {
      if (file.selected === false) return false
      if (file.status !== 'modified' || !this.hasHunkDetail(file)) return false
      const count = this.selectedHunkCount(file)
      return count > 0 && count < file.hunks.length
    },
    setFileSelected(file, value) {
      const selected = value !== false
      this.$set(file, 'selected', selected)
      if (this.hasHunkDetail(file)) {
        file.hunks.forEach(h => { this.$set(h, 'selected', selected) })
      }
    },
    selectAllFiles() {
      this.changedFiles
        .filter(f => f.status !== 'extra')
        .forEach(f => this.setFileSelected(f, true))
    },
    deselectAllFiles() {
      this.changedFiles
        .filter(f => f.status !== 'extra')
        .forEach(f => this.setFileSelected(f, false))
    },
    emitApply() {
      const { files, excludedFiles, partialFiles } = this.selectionState
      if (files.length === 0) return
      if (excludedFiles === 0 && partialFiles === 0) {
        this.$emit('apply-all')
      } else {
        this.$emit('apply-selection', { files, excludedFiles, partialFiles })
      }
    },
    selectAllHunks(file) {
      if (!file.hunks) return
      file.hunks.forEach(h => { h.selected = true })
    },
    deselectAllHunks(file) {
      if (!file.hunks) return
      file.hunks.forEach(h => { h.selected = false })
    },
    selectedHunkCount(file) {
      if (!file.hunks) return 0
      return file.hunks.filter(h => h.selected).length
    },
    emitApplyHunks(file) {
      const selectedIndices = file.hunks
        .filter(h => h.selected)
        .map(h => h.index)
      this.$emit('apply-hunks', { file: file.file, hunks: selectedIndices })
    }
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
