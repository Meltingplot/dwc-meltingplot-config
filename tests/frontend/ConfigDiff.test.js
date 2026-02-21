import { shallowMount } from '@vue/test-utils'
import ConfigDiff from '../../src/components/ConfigDiff.vue'

function mountComponent(propsData = {}) {
  return shallowMount(ConfigDiff, {
    vuetify: global.createVuetify(),
    propsData
  })
}

describe('ConfigDiff', () => {
  describe('loading state', () => {
    it('shows loading indicator when loading=true', () => {
      const wrapper = mountComponent({ loading: true })
      expect(wrapper.text()).toContain('Loading changes...')
    })
  })

  describe('empty state', () => {
    it('shows "No changes detected" when no changed files', () => {
      const wrapper = mountComponent({
        files: [{ file: 'sys/config.g', status: 'unchanged', hunks: [] }]
      })
      expect(wrapper.text()).toContain('No changes detected')
    })

    it('shows "No changes detected" with empty files array', () => {
      const wrapper = mountComponent({ files: [] })
      expect(wrapper.text()).toContain('No changes detected')
    })
  })

  describe('changed files', () => {
    const files = [
      { file: 'sys/config.g', status: 'modified', hunks: [] },
      { file: 'sys/homex.g', status: 'missing', hunks: [] },
      { file: 'sys/unchanged.g', status: 'unchanged', hunks: [] }
    ]

    it('filters out unchanged files', () => {
      const wrapper = mountComponent({ files })
      expect(wrapper.vm.changedFiles).toHaveLength(2)
    })

    it('shows file count summary', () => {
      const wrapper = mountComponent({ files })
      expect(wrapper.text()).toContain('2 files changed')
    })

    it('shows singular "file" for one change', () => {
      const wrapper = mountComponent({
        files: [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
      })
      expect(wrapper.text()).toContain('1 file changed')
    })
  })

  describe('computed methods', () => {
    it('fileStatusColor returns correct colors', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.fileStatusColor('modified')).toBe('warning')
      expect(wrapper.vm.fileStatusColor('missing')).toBe('info')
      expect(wrapper.vm.fileStatusColor('extra')).toBe('grey')
      expect(wrapper.vm.fileStatusColor('unknown')).toBe('warning')
    })

    it('fileStatusIcon returns correct icons', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.fileStatusIcon('modified')).toBe('mdi-file-document-edit')
      expect(wrapper.vm.fileStatusIcon('missing')).toBe('mdi-file-plus')
      expect(wrapper.vm.fileStatusIcon('extra')).toBe('mdi-file-question')
    })

    it('parseHunkHeader parses standard hunk header', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.parseHunkHeader('@@ -10,7 +10,8 @@')).toEqual({
        oldStart: 10, oldCount: 7, newStart: 10, newCount: 8
      })
    })

    it('parseHunkHeader parses single-line hunk header', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.parseHunkHeader('@@ -5 +5 @@')).toEqual({
        oldStart: 5, oldCount: 1, newStart: 5, newCount: 1
      })
    })

    it('parseHunkHeader returns null for invalid input', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.parseHunkHeader(null)).toBeNull()
      expect(wrapper.vm.parseHunkHeader('')).toBeNull()
      expect(wrapper.vm.parseHunkHeader('not a header')).toBeNull()
    })

    it('sideBySideLines pairs removed and added lines with line numbers', () => {
      const wrapper = mountComponent()
      const hunk = {
        header: '@@ -10,3 +20,3 @@',
        lines: [' context', '-old line', '+new line', ' end']
      }
      const rows = wrapper.vm.sideBySideLines(hunk)
      expect(rows).toHaveLength(3)
      // Context line appears on both sides with line numbers
      expect(rows[0]).toEqual({ leftLine: 10, left: 'context', leftClass: 'diff-context', rightLine: 20, right: 'context', rightClass: 'diff-context' })
      // Removed on left, added on right
      expect(rows[1]).toEqual({ leftLine: 11, left: 'old line', leftClass: 'diff-remove', rightLine: 21, right: 'new line', rightClass: 'diff-add' })
      // Trailing context
      expect(rows[2]).toEqual({ leftLine: 12, left: 'end', leftClass: 'diff-context', rightLine: 22, right: 'end', rightClass: 'diff-context' })
    })

    it('sideBySideLines handles unbalanced removes and adds with line numbers', () => {
      const wrapper = mountComponent()
      const hunk = {
        header: '@@ -5,2 +5,1 @@',
        lines: ['-removed1', '-removed2', '+added1']
      }
      const rows = wrapper.vm.sideBySideLines(hunk)
      expect(rows).toHaveLength(2)
      expect(rows[0]).toEqual({ leftLine: 5, left: 'removed1', leftClass: 'diff-remove', rightLine: 5, right: 'added1', rightClass: 'diff-add' })
      expect(rows[1]).toEqual({ leftLine: 6, left: 'removed2', leftClass: 'diff-remove', rightLine: null, right: null, rightClass: 'diff-empty' })
    })

    it('sideBySideLines handles only adds with line numbers', () => {
      const wrapper = mountComponent()
      const hunk = { header: '@@ -1,0 +1,2 @@', lines: ['+new1', '+new2'] }
      const rows = wrapper.vm.sideBySideLines(hunk)
      expect(rows).toHaveLength(2)
      expect(rows[0].leftLine).toBeNull()
      expect(rows[0].left).toBeNull()
      expect(rows[0].leftClass).toBe('diff-empty')
      expect(rows[0].rightLine).toBe(1)
      expect(rows[0].right).toBe('new1')
      expect(rows[0].rightClass).toBe('diff-add')
    })

    it('sideBySideLines defaults to line 1 without header', () => {
      const wrapper = mountComponent()
      const hunk = { lines: [' context'] }
      const rows = wrapper.vm.sideBySideLines(hunk)
      expect(rows).toHaveLength(1)
      expect(rows[0].leftLine).toBe(1)
      expect(rows[0].rightLine).toBe(1)
    })

    it('sideBySideLines returns empty array for hunk without lines', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.sideBySideLines({})).toEqual([])
      expect(wrapper.vm.sideBySideLines({ lines: null })).toEqual([])
    })

    it('skippedLinesBetween returns gap before first hunk', () => {
      const wrapper = mountComponent()
      const file = {
        hunks: [{ index: 0, header: '@@ -10,3 +10,3 @@' }]
      }
      expect(wrapper.vm.skippedLinesBetween(file, 0)).toBe(9)
    })

    it('skippedLinesBetween returns 0 when first hunk starts at line 1', () => {
      const wrapper = mountComponent()
      const file = {
        hunks: [{ index: 0, header: '@@ -1,3 +1,3 @@' }]
      }
      expect(wrapper.vm.skippedLinesBetween(file, 0)).toBe(0)
    })

    it('skippedLinesBetween returns gap between hunks', () => {
      const wrapper = mountComponent()
      const file = {
        hunks: [
          { index: 0, header: '@@ -1,3 +1,3 @@' },
          { index: 1, header: '@@ -10,3 +10,3 @@' }
        ]
      }
      // Hunk 0 covers lines 1-3, hunk 1 starts at 10, so gap = 10 - (1+3) = 6
      expect(wrapper.vm.skippedLinesBetween(file, 1)).toBe(6)
    })
  })

  describe('hunk selection', () => {
    it('selectAllHunks sets all to selected', () => {
      const wrapper = mountComponent()
      const file = {
        hunks: [
          { index: 0, selected: false },
          { index: 1, selected: false }
        ]
      }
      wrapper.vm.selectAllHunks(file)
      expect(file.hunks[0].selected).toBe(true)
      expect(file.hunks[1].selected).toBe(true)
    })

    it('deselectAllHunks sets all to not selected', () => {
      const wrapper = mountComponent()
      const file = {
        hunks: [
          { index: 0, selected: true },
          { index: 1, selected: true }
        ]
      }
      wrapper.vm.deselectAllHunks(file)
      expect(file.hunks[0].selected).toBe(false)
      expect(file.hunks[1].selected).toBe(false)
    })

    it('selectedHunkCount counts selected hunks', () => {
      const wrapper = mountComponent()
      const file = {
        hunks: [
          { index: 0, selected: true },
          { index: 1, selected: false },
          { index: 2, selected: true }
        ]
      }
      expect(wrapper.vm.selectedHunkCount(file)).toBe(2)
    })

    it('selectedHunkCount returns 0 when no hunks', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.selectedHunkCount({})).toBe(0)
    })

    it('emitApplyHunks emits correct indices', () => {
      const wrapper = mountComponent()
      const file = {
        file: 'sys/config.g',
        hunks: [
          { index: 0, selected: true },
          { index: 1, selected: false },
          { index: 2, selected: true }
        ]
      }
      wrapper.vm.emitApplyHunks(file)
      expect(wrapper.emitted('apply-hunks')).toHaveLength(1)
      expect(wrapper.emitted('apply-hunks')[0]).toEqual([
        { file: 'sys/config.g', hunks: [0, 2] }
      ])
    })
  })

  describe('apply-all event', () => {
    it('emits apply-all when button clicked', () => {
      const files = [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
      const wrapper = mountComponent({ files })
      const btns = wrapper.findAll('v-btn-stub')
      const applyAllBtn = btns.wrappers.find(w => w.text().includes('Apply All'))
      if (applyAllBtn) {
        applyAllBtn.vm.$emit('click')
        expect(wrapper.emitted('apply-all')).toBeTruthy()
      }
    })
  })

  describe('loadFileDetail', () => {
    afterEach(() => {
      delete global.fetch
    })

    it('fetches detail for modified file without lines', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'modified', hunks: [{ index: 0, header: '@@ -1 +1 @@' }] }
      global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          hunks: [{ index: 0, header: '@@ -1 +1 @@', lines: [' line1', '-old', '+new'], summary: 'Line 1' }]
        })
      }))
      await wrapper.vm.loadFileDetail(file)
      expect(file.hunks).toHaveLength(1)
      expect(file.hunks[0].lines).toBeDefined()
      expect(file.hunks[0].selected).toBe(true)
      expect(file.loadingDetail).toBe(false)
    })

    it('skips fetch for unchanged files', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'unchanged', hunks: [] }
      global.fetch = jest.fn()
      await wrapper.vm.loadFileDetail(file)
      expect(global.fetch).not.toHaveBeenCalled()
    })

    it('fetches detail for missing files', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/homex.g', status: 'missing', hunks: [{ index: 0, header: '@@ -0,0 +1,2 @@' }] }
      global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          hunks: [{ index: 0, header: '@@ -0,0 +1,2 @@', lines: ['+G91', '+G1 H1 X-300 F3000'], summary: 'Lines 0-0' }]
        })
      }))
      await wrapper.vm.loadFileDetail(file)
      expect(global.fetch).toHaveBeenCalledTimes(1)
      expect(file.hunks).toHaveLength(1)
      expect(file.hunks[0].lines).toBeDefined()
      expect(file.hunks[0].selected).toBe(true)
    })

    it('skips fetch when detail is already loaded', async () => {
      const wrapper = mountComponent()
      const file = {
        file: 'sys/config.g',
        status: 'modified',
        hunks: [{ index: 0, header: '@@ -1 +1 @@', lines: [' existing'], selected: true }]
      }
      global.fetch = jest.fn()
      await wrapper.vm.loadFileDetail(file)
      expect(global.fetch).not.toHaveBeenCalled()
    })

    it('defaults hunks to empty array on HTTP error', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'modified', hunks: [] }
      global.fetch = jest.fn(() => Promise.resolve({
        ok: false,
        status: 500,
        statusText: 'Server Error'
      }))
      await wrapper.vm.loadFileDetail(file)
      expect(file.hunks).toEqual([])
      expect(file.loadingDetail).toBe(false)
    })

    it('defaults hunks to empty array on network failure', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'modified', hunks: [] }
      global.fetch = jest.fn(() => Promise.reject(new TypeError('Failed to fetch')))
      await wrapper.vm.loadFileDetail(file)
      expect(file.hunks).toEqual([])
      expect(file.loadingDetail).toBe(false)
    })

    it('handles response missing hunks field', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'modified', hunks: [] }
      global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({})
      }))
      await wrapper.vm.loadFileDetail(file)
      expect(file.hunks).toEqual([])
      expect(file.loadingDetail).toBe(false)
    })

    it('handles null hunks in response', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/config.g', status: 'modified', hunks: [] }
      global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ hunks: null })
      }))
      await wrapper.vm.loadFileDetail(file)
      expect(file.hunks).toEqual([])
      expect(file.loadingDetail).toBe(false)
    })
  })

  describe('expandedPanels reset', () => {
    it('resets expandedPanels when files prop changes', async () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: [] },
        { file: 'sys/homex.g', status: 'missing', hunks: [] }
      ]
      const wrapper = mountComponent({ files })
      wrapper.vm.expandedPanels = [0, 1]
      expect(wrapper.vm.expandedPanels).toEqual([0, 1])

      await wrapper.setProps({
        files: [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
      })
      expect(wrapper.vm.expandedPanels).toEqual([])
    })
  })

  describe('protected files', () => {
    it('shows protected files in changedFiles', () => {
      const files = [
        { file: 'sys/config.g', status: 'modified', hunks: [] },
        { file: 'sys/meltingplot/machine-override.g', status: 'protected', hunks: [] },
        { file: 'sys/unchanged.g', status: 'unchanged', hunks: [] }
      ]
      const wrapper = mountComponent({ files })
      expect(wrapper.vm.changedFiles).toHaveLength(2)
      expect(wrapper.vm.changedFiles.map(f => f.status)).toContain('protected')
    })

    it('fileStatusColor returns grey for protected', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.fileStatusColor('protected')).toBe('grey')
    })

    it('fileStatusIcon returns lock for protected', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.fileStatusIcon('protected')).toBe('mdi-lock')
    })

    it('loadFileDetail skips fetch for protected files', async () => {
      const wrapper = mountComponent()
      const file = { file: 'sys/dsf-config-override.g', status: 'protected', hunks: [] }
      global.fetch = jest.fn()
      await wrapper.vm.loadFileDetail(file)
      expect(global.fetch).not.toHaveBeenCalled()
    })
  })

  describe('hunk selection edge cases', () => {
    it('selectAllHunks does nothing when hunks is undefined', () => {
      const wrapper = mountComponent()
      const file = {}
      wrapper.vm.selectAllHunks(file)
      expect(file.hunks).toBeUndefined()
    })

    it('deselectAllHunks does nothing when hunks is undefined', () => {
      const wrapper = mountComponent()
      const file = {}
      wrapper.vm.deselectAllHunks(file)
      expect(file.hunks).toBeUndefined()
    })

    it('selectedHunkCount returns 0 when hunks is undefined', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.selectedHunkCount({})).toBe(0)
    })

    it('selectedHunkCount returns 0 for empty hunks array', () => {
      const wrapper = mountComponent()
      expect(wrapper.vm.selectedHunkCount({ hunks: [] })).toBe(0)
    })
  })
})
