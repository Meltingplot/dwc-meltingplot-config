'use strict'

/**
 * Selection state and on-demand detail loading for the diff viewer.
 *
 * The parent hands in the file list from `GET /diff`. Those entries carry
 * summary hunks only (`index` + `header`); the full hunk `lines` — and with
 * them the per-hunk checkboxes — are fetched when a panel is expanded.
 */

import { computed, ref, watch } from 'vue'
import { apiGet, query } from './api'
import {
  computeSelection,
  fileChecked,
  fileIsPartial,
  fileStatusColor,
  fileStatusIcon,
  hasHunkDetail,
  normalizeFile,
  normalizeHunk,
  parseHunkHeader,
  selectedHunkCount,
  sideBySideLines,
  skippedLinesBetween
} from './diff'

/**
 * Build the diff viewer's state and actions.
 *
 * @param {import('vue').Ref<Array<object>>|Function} filesRef Reactive source
 *   of the file list (a ref, or a getter returning it)
 * @param {(event: string, payload?: *) => void} emit Component emit function
 * @returns {object} Refs, computeds and actions to expose from `setup()`
 */
export function useConfigDiff(filesRef, emit) {
  const expandedPanels = ref([])

  const files = computed(() =>
    (typeof filesRef === 'function' ? filesRef() : filesRef.value) || []
  )

  const changedFiles = computed(() => files.value.filter(f => f.status !== 'unchanged'))

  const selectionState = computed(() => computeSelection(changedFiles.value))

  const isPartialApply = computed(
    () => selectionState.value.excludedFiles > 0 || selectionState.value.partialFiles > 0
  )

  const applyButtonLabel = computed(() => (isPartialApply.value ? 'Partially Apply' : 'Apply All'))

  const applyDisabled = computed(() => selectionState.value.files.length === 0)

  /**
   * Fetch the full hunks of a file the first time its panel is expanded.
   *
   * @param {object} file File entry
   */
  async function loadFileDetail(file) {
    if (file.status !== 'modified' && file.status !== 'missing') return
    // GET /diff returns summary hunks (index + header only).
    // Skip the fetch only if full detail (lines) is already loaded.
    if (hasHunkDetail(file)) return
    file.loadingDetail = true
    try {
      const data = await apiGet(`/diff?${query({ file: file.file })}`)
      const selected = file.selected !== false
      file.hunks = (data.hunks || []).map(h => normalizeHunk(h, selected))
    } catch {
      file.hunks = []
    } finally {
      file.loadingDetail = false
    }
  }

  /**
   * Include or exclude a whole file, carrying the state into its hunks.
   *
   * @param {object} file File entry
   * @param {boolean|null} value New checkbox value
   */
  function setFileSelected(file, value) {
    const selected = value !== false
    file.selected = selected
    if (hasHunkDetail(file)) {
      file.hunks.forEach(h => { h.selected = selected })
    }
  }

  function selectAllFiles() {
    changedFiles.value
      .filter(f => f.status !== 'extra')
      .forEach(f => setFileSelected(f, true))
  }

  function deselectAllFiles() {
    changedFiles.value
      .filter(f => f.status !== 'extra')
      .forEach(f => setFileSelected(f, false))
  }

  /**
   * @param {object} file File entry
   */
  function selectAllHunks(file) {
    if (!file.hunks) return
    file.hunks.forEach(h => { h.selected = true })
  }

  /**
   * @param {object} file File entry
   */
  function deselectAllHunks(file) {
    if (!file.hunks) return
    file.hunks.forEach(h => { h.selected = false })
  }

  /** Emit the top-level apply, as a full or a partial apply. */
  function emitApply() {
    const { files: payload, excludedFiles, partialFiles } = selectionState.value
    if (payload.length === 0) return
    if (excludedFiles === 0 && partialFiles === 0) {
      emit('apply-all')
    } else {
      emit('apply-selection', { files: payload, excludedFiles, partialFiles })
    }
  }

  /**
   * Emit a per-file hunk apply.
   *
   * @param {object} file File entry
   */
  function emitApplyHunks(file) {
    const selectedIndices = file.hunks.filter(h => h.selected).map(h => h.index)
    emit('apply-hunks', { file: file.file, hunks: selectedIndices })
  }

  watch(files, list => {
    expandedPanels.value = []
    // Everything starts selected; the user opts changes out. Entries that came
    // through loadDiff() are already normalised, so this only fills in a list
    // handed to the component directly.
    //
    // The entries are replaced rather than patched: Vue 2.7 cannot observe a
    // property added to an already-reactive object, so assigning the missing
    // fields in place would leave the checkboxes non-reactive. Splicing swaps
    // in fully-formed objects, which Vue then observes completely.
    if (list.some(file => file.selected === undefined || file.loadingDetail === undefined)) {
      list.splice(0, list.length, ...list.map(normalizeFile))
    }
  }, { immediate: true })

  return {
    expandedPanels,
    changedFiles,
    selectionState,
    isPartialApply,
    applyButtonLabel,
    applyDisabled,
    // pure helpers, re-exported for the template
    fileStatusColor,
    fileStatusIcon,
    parseHunkHeader,
    skippedLinesBetween,
    sideBySideLines,
    hasHunkDetail,
    fileChecked,
    fileIsPartial,
    selectedHunkCount,
    // actions
    loadFileDetail,
    setFileSelected,
    selectAllFiles,
    deselectAllFiles,
    selectAllHunks,
    deselectAllHunks,
    emitApply,
    emitApplyHunks
  }
}
