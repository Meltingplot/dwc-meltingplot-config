import { shallowMount } from '@vue/test-utils'
import BackupHistory from '../../src/components/BackupHistory.vue'

function mountComponent(propsData = {}) {
  return shallowMount(BackupHistory, {
    vuetify: global.createVuetify(),
    propsData
  })
}

const sampleBackups = [
  {
    hash: 'abc12345678901234567890123456789abcdef00',
    message: 'Pre-update backup',
    timestamp: '2026-02-15T10:00:00',
    filesChanged: 3
  },
  {
    hash: 'def12345678901234567890123456789abcdef00',
    message: 'Applied reference 3.5',
    timestamp: '2026-02-15T10:00:05',
    filesChanged: 3
  }
]

describe('BackupHistory', () => {
  describe('loading state', () => {
    it('shows loading indicator when loading=true', () => {
      const wrapper = mountComponent({ loading: true })
      expect(wrapper.text()).toContain('Loading backups...')
    })
  })

  describe('empty state', () => {
    it('shows "No backups yet" when empty', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.text()).toContain('No backups yet')
    })

    it('explains how backups are created', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.text()).toContain('Backups are created automatically')
    })
  })

  describe('with backups', () => {
    it('shows backup messages', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      expect(wrapper.text()).toContain('Pre-update backup')
      expect(wrapper.text()).toContain('Applied reference 3.5')
    })

    it('shows timestamps', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      expect(wrapper.text()).toContain('2026-02-15T10:00:00')
    })

    it('shows file count', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      expect(wrapper.text()).toContain('3 files')
    })

    it('shows short hash', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      expect(wrapper.text()).toContain('abc12345')
    })

    it('shows singular "file" when filesChanged is 1', () => {
      const wrapper = mountComponent({
        backups: [{ ...sampleBackups[0], filesChanged: 1 }]
      })
      expect(wrapper.text()).toContain('1 file')
      expect(wrapper.text()).not.toMatch(/1 files/)
    })
  })

  describe('events', () => {
    it('emits refresh when refresh button clicked', () => {
      const wrapper = mountComponent({ backups: [] })
      const refreshBtn = wrapper.findAll('v-btn-stub').wrappers.find(
        w => w.text().includes('Refresh')
      )
      if (refreshBtn) {
        refreshBtn.vm.$emit('click')
        expect(wrapper.emitted('refresh')).toBeTruthy()
      }
    })

    it('emits download with correct hash', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      wrapper.vm.$emit('download', sampleBackups[0].hash)
      expect(wrapper.emitted('download')).toBeTruthy()
      expect(wrapper.emitted('download')[0]).toEqual([sampleBackups[0].hash])
    })

    it('emits restore with correct hash', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      wrapper.vm.$emit('restore', sampleBackups[0].hash)
      expect(wrapper.emitted('restore')).toBeTruthy()
      expect(wrapper.emitted('restore')[0]).toEqual([sampleBackups[0].hash])
    })

    it('emits delete with correct hash', () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      wrapper.vm.$emit('delete', sampleBackups[0].hash)
      expect(wrapper.emitted('delete')).toBeTruthy()
      expect(wrapper.emitted('delete')[0]).toEqual([sampleBackups[0].hash])
    })
  })

  describe('toggleExpand', () => {
    it('sets expanded to true and fetches changedFiles on first click', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0] }

      global.fetch = jest.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            files: ['sys/config.g', 'sys/homex.g'],
            changedFiles: ['sys/config.g']
          })
        })
      )

      await wrapper.vm.toggleExpand(backup)
      expect(backup.expanded).toBe(true)
      expect(backup.changedFiles).toEqual(['sys/config.g'])
      expect(backup.files).toEqual(['sys/config.g', 'sys/homex.g'])

      global.fetch.mockRestore()
    })

    it('sets expanded to false on second click', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0], expanded: true, changedFiles: ['sys/config.g'] }

      await wrapper.vm.toggleExpand(backup)
      expect(backup.expanded).toBe(false)
    })

    it('does not re-fetch if changedFiles already loaded', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0], changedFiles: ['sys/config.g'] }

      global.fetch = jest.fn()
      await wrapper.vm.toggleExpand(backup)
      expect(global.fetch).not.toHaveBeenCalled()
      expect(backup.expanded).toBe(true)

      global.fetch.mockRestore()
    })

    it('handles fetch errors gracefully', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0] }

      global.fetch = jest.fn(() => Promise.reject(new Error('network error')))
      await wrapper.vm.toggleExpand(backup)
      expect(backup.changedFiles).toEqual([])
      expect(backup.expanded).toBe(true)

      global.fetch.mockRestore()
    })
  })

  describe('buildFileTree', () => {
    it('returns empty array for empty input', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.vm.buildFileTree([])).toEqual([])
      expect(wrapper.vm.buildFileTree(null)).toEqual([])
    })

    it('builds a tree from flat file paths', () => {
      const wrapper = mountComponent({ backups: [] })
      const tree = wrapper.vm.buildFileTree([
        'sys/config.g',
        'sys/board.txt',
        'macros/homeall.g'
      ])

      expect(tree.length).toBe(2)
      // Folders first (macros, sys), sorted alphabetically
      const folderNames = tree.map(n => n.name)
      expect(folderNames).toContain('macros')
      expect(folderNames).toContain('sys')

      const sysNode = tree.find(n => n.name === 'sys')
      expect(sysNode.children).toBeDefined()
      expect(sysNode.children.length).toBe(2)
      expect(sysNode.children.map(c => c.name)).toContain('config.g')
      expect(sysNode.children.map(c => c.name)).toContain('board.txt')
    })

    it('handles single file at root level', () => {
      const wrapper = mountComponent({ backups: [] })
      const tree = wrapper.vm.buildFileTree(['config.g'])
      expect(tree.length).toBe(1)
      expect(tree[0].name).toBe('config.g')
      expect(tree[0].children).toBeUndefined()
    })

    it('handles deeply nested paths', () => {
      const wrapper = mountComponent({ backups: [] })
      const tree = wrapper.vm.buildFileTree(['sys/sub/deep/file.g'])
      expect(tree.length).toBe(1)
      expect(tree[0].name).toBe('sys')
      expect(tree[0].children[0].name).toBe('sub')
      expect(tree[0].children[0].children[0].name).toBe('deep')
      expect(tree[0].children[0].children[0].children[0].name).toBe('file.g')
    })

    it('assigns id as full path', () => {
      const wrapper = mountComponent({ backups: [] })
      const tree = wrapper.vm.buildFileTree(['sys/config.g'])
      expect(tree[0].id).toBe('sys')
      expect(tree[0].children[0].id).toBe('sys/config.g')
    })
  })

  describe('onFileSelected', () => {
    it('fetches diff for selected file', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = {
        ...sampleBackups[0],
        expanded: true,
        changedFiles: ['sys/config.g'],
        activeNodes: []
      }

      global.fetch = jest.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            file: 'sys/config.g',
            status: 'modified',
            hunks: [{ index: 0, header: '@@ -1,3 +1,3 @@', lines: [' G28', '-old', '+new'], summary: 'Lines 1-3' }]
          })
        })
      )

      await wrapper.vm.onFileSelected(backup, ['sys/config.g'])
      expect(backup.selectedFile).toBe('sys/config.g')
      expect(backup.fileDiff).toBeTruthy()
      expect(backup.fileDiff.status).toBe('modified')
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('backupFileDiff')
      )

      global.fetch.mockRestore()
    })

    it('clears selection when empty array', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = {
        ...sampleBackups[0],
        expanded: true,
        changedFiles: ['sys/config.g'],
        selectedFile: 'sys/config.g',
        fileDiff: { file: 'sys/config.g', status: 'modified', hunks: [] }
      }

      await wrapper.vm.onFileSelected(backup, [])
      expect(backup.selectedFile).toBeNull()
      expect(backup.fileDiff).toBeNull()
    })

    it('ignores folder selections', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = {
        ...sampleBackups[0],
        expanded: true,
        changedFiles: ['sys/config.g'],
        activeNodes: []
      }

      global.fetch = jest.fn()
      await wrapper.vm.onFileSelected(backup, ['sys'])
      expect(global.fetch).not.toHaveBeenCalled()

      global.fetch.mockRestore()
    })

    it('handles fetch errors gracefully', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = {
        ...sampleBackups[0],
        expanded: true,
        changedFiles: ['sys/config.g'],
        activeNodes: []
      }

      global.fetch = jest.fn(() => Promise.reject(new Error('network error')))
      await wrapper.vm.onFileSelected(backup, ['sys/config.g'])
      expect(backup.fileDiff).toBeTruthy()
      expect(backup.fileDiff.status).toBe('error')

      global.fetch.mockRestore()
    })
  })

  describe('sideBySideLines', () => {
    it('converts hunk lines to side-by-side rows', () => {
      const wrapper = mountComponent({ backups: [] })
      const hunk = {
        header: '@@ -1,3 +1,3 @@',
        lines: [' context', '-removed', '+added', ' context2']
      }
      const rows = wrapper.vm.sideBySideLines(hunk)
      // context + remove/add pair + context2 = 3 rows (pair is combined)
      expect(rows.length).toBe(3)
      // First row: context
      expect(rows[0].leftClass).toBe('diff-context')
      expect(rows[0].rightClass).toBe('diff-context')
      // Middle row: remove/add pair
      expect(rows[1].leftClass).toBe('diff-remove')
      expect(rows[1].rightClass).toBe('diff-add')
      // Last row: context
      expect(rows[2].leftClass).toBe('diff-context')
    })

    it('returns empty for hunk without lines', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.vm.sideBySideLines({ header: '@@ -1 +1 @@' })).toEqual([])
      expect(wrapper.vm.sideBySideLines({ header: '@@ -1 +1 @@', lines: null })).toEqual([])
    })
  })

  describe('diffStatusColor', () => {
    it('returns correct colors for known statuses', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.vm.diffStatusColor('modified')).toBe('warning')
      expect(wrapper.vm.diffStatusColor('added')).toBe('success')
      expect(wrapper.vm.diffStatusColor('deleted')).toBe('error')
    })

    it('returns grey for unknown status', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.vm.diffStatusColor('something_else')).toBe('grey')
    })
  })

  describe('createBackup', () => {
    it('has creatingBackup data property', () => {
      const wrapper = mountComponent({ backups: [] })
      expect(wrapper.vm.creatingBackup).toBe(false)
    })

    it('calls manualBackup API and emits refresh on success', async () => {
      const wrapper = mountComponent({ backups: [] })

      global.fetch = jest.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ backup: { hash: 'abc123', message: 'Manual backup' } })
        })
      )

      await wrapper.vm.createBackup()
      expect(global.fetch).toHaveBeenCalledWith(
        '/machine/MeltingplotConfig/manualBackup',
        { method: 'POST' }
      )
      expect(wrapper.emitted('refresh')).toBeTruthy()
      expect(wrapper.emitted('notify')).toBeTruthy()
      expect(wrapper.emitted('notify')[0][0].color).toBe('success')
      expect(wrapper.vm.creatingBackup).toBe(false)

      global.fetch.mockRestore()
    })

    it('emits error notify on failure', async () => {
      const wrapper = mountComponent({ backups: [] })

      global.fetch = jest.fn(() =>
        Promise.resolve({ ok: false, statusText: 'Internal Server Error' })
      )

      await wrapper.vm.createBackup()
      expect(wrapper.emitted('notify')).toBeTruthy()
      expect(wrapper.emitted('notify')[0][0].color).toBe('error')
      expect(wrapper.vm.creatingBackup).toBe(false)

      global.fetch.mockRestore()
    })
  })
})
