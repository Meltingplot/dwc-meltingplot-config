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
        <v-spacer />
        <v-btn color="primary" small @click="$emit('apply-all')">
          <v-icon left small>mdi-check-all</v-icon>
          Apply All
        </v-btn>
      </v-toolbar>

      <v-expansion-panels v-model="expandedPanels" multiple>
        <v-expansion-panel v-for="file in changedFiles" :key="file.file">
          <v-expansion-panel-header @click="loadFileDetail(file)">
            <div class="d-flex align-center">
              <v-icon small :color="fileStatusColor(file.status)" class="mr-2">
                {{ fileStatusIcon(file.status) }}
              </v-icon>
              <span class="font-weight-medium">{{ file.file }}</span>
              <v-chip x-small class="ml-2" :color="fileStatusColor(file.status)" outlined>
                {{ file.status }}
              </v-chip>
              <span v-if="file.hunks" class="ml-2 caption grey--text">
                {{ file.hunks.length }} change{{ file.hunks.length !== 1 ? 's' : '' }}
              </span>
            </div>
          </v-expansion-panel-header>

          <v-expansion-panel-content>
            <div v-if="file.loadingDetail" class="text-center pa-4">
              <v-progress-circular indeterminate size="24" />
            </div>

            <div v-else-if="file.hunks && file.hunks.length > 0">
              <v-toolbar flat dense class="mb-2">
                <v-btn x-small text @click="selectAllHunks(file)">Select all</v-btn>
                <v-btn x-small text @click="deselectAllHunks(file)">Deselect all</v-btn>
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

              <div v-for="hunk in file.hunks" :key="hunk.index" class="hunk-block mb-3">
                <div class="hunk-header d-flex align-center pa-2">
                  <v-checkbox v-model="hunk.selected" dense hide-details class="mt-0 pt-0 mr-2" />
                  <code class="hunk-range">{{ hunk.header }}</code>
                  <span v-if="hunk.summary" class="ml-2 caption grey--text">{{ hunk.summary }}</span>
                </div>
                <table class="diff-table">
                  <thead>
                    <tr>
                      <th class="diff-col-header diff-col-left">Current (Printer)</th>
                      <th class="diff-col-header diff-col-right">Reference (New)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, i) in sideBySideLines(hunk)" :key="i">
                      <td :class="['diff-cell', row.leftClass]">
                        <code v-if="row.left !== null">{{ row.left }}</code>
                      </td>
                      <td :class="['diff-cell', row.rightClass]">
                        <code v-if="row.right !== null">{{ row.right }}</code>
                      </td>
                    </tr>
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
  watch: {
    files() {
      this.expandedPanels = []
    }
  },
  computed: {
    changedFiles() {
      return this.files.filter(f => f.status !== 'unchanged')
    }
  },
  methods: {
    fileStatusColor(status) {
      return (FILE_STATUS[status] || FILE_STATUS.modified).color
    },
    fileStatusIcon(status) {
      return (FILE_STATUS[status] || FILE_STATUS.modified).icon
    },
    sideBySideLines(hunk) {
      if (!hunk.lines) return []
      const rows = []
      const removes = []
      const adds = []

      const flushPairs = () => {
        const max = Math.max(removes.length, adds.length)
        for (let i = 0; i < max; i++) {
          rows.push({
            left: i < removes.length ? removes[i].substring(1) : null,
            leftClass: i < removes.length ? 'diff-remove' : 'diff-empty',
            right: i < adds.length ? adds[i].substring(1) : null,
            rightClass: i < adds.length ? 'diff-add' : 'diff-empty'
          })
        }
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
            left: text,
            leftClass: 'diff-context',
            right: text,
            rightClass: 'diff-context'
          })
        }
      }
      flushPairs()
      return rows
    },
    async loadFileDetail(file) {
      if (file.status !== 'modified') return
      // diff_all returns summary hunks (index + header only).
      // Skip fetch only if full detail (lines) is already loaded.
      if (file.hunks && file.hunks.length > 0 && file.hunks[0].lines) return
      this.$set(file, 'loadingDetail', true)
      try {
        const response = await fetch(`${API_BASE}/diff?file=${encodeURIComponent(file.file)}`)
        if (!response.ok) throw new Error(response.statusText)
        const data = await response.json()
        this.$set(file, 'hunks', (data.hunks || []).map(h => ({ ...h, selected: true })))
      } catch {
        this.$set(file, 'hunks', [])
      } finally {
        this.$set(file, 'loadingDetail', false)
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
.hunk-block {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  overflow: hidden;
}
.hunk-header {
  background-color: #f5f5f5;
  border-bottom: 1px solid #e0e0e0;
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
.diff-col-header {
  width: 50%;
  padding: 4px 8px;
  font-size: 0.8em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 2px solid #e0e0e0;
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
.diff-cell {
  width: 50%;
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
