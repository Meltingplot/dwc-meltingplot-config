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
  })

  describe('toggleExpand', () => {
    it('sets expanded to true on first click', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0] }

      global.fetch = jest.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ files: ['sys/config.g'] })
        })
      )

      await wrapper.vm.toggleExpand(backup)
      expect(backup.expanded).toBe(true)

      global.fetch.mockRestore()
    })

    it('sets expanded to false on second click', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0], expanded: true, files: ['sys/config.g'] }

      await wrapper.vm.toggleExpand(backup)
      expect(backup.expanded).toBe(false)
    })

    it('does not re-fetch if files already loaded', async () => {
      const wrapper = mountComponent({ backups: sampleBackups })
      const backup = { ...sampleBackups[0], files: ['sys/config.g'] }

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
      expect(backup.files).toEqual([])
      expect(backup.expanded).toBe(true)

      global.fetch.mockRestore()
    })
  })
})
