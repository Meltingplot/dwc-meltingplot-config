import { mount, createLocalVue } from '@vue/test-utils'
import Vuex from 'vuex'
import Vuetify from 'vuetify'
import MeltingplotConfig from '../../../src/MeltingplotConfig.vue'
import { describe, it, expect, beforeEach, afterEach } from '@jest/globals'

const localVue = createLocalVue()
localVue.use(Vuex)

function createStore(sbcData = {}) {
  return new Vuex.Store({
    modules: {
      'machine/model': {
        namespaced: true,
        state: {
          plugins: {
            MeltingplotConfig: sbcData
          }
        }
      }
    }
  })
}

function createMockFetch(routes = {}) {
  return jest.fn((url, opts) => {
    for (const [pattern, handler] of Object.entries(routes)) {
      if (url.includes(pattern)) {
        const data = typeof handler === 'function' ? handler(url, opts) : handler
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(data),
          text: () => Promise.resolve(JSON.stringify(data))
        })
      }
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      text: () => Promise.resolve('Not Found'),
      json: () => Promise.resolve({ error: 'Not Found' })
    })
  })
}

function flush() {
  return new Promise(r => setTimeout(r, 0))
}

describe('Full-mount integration', () => {
  let vuetify

  beforeEach(() => {
    vuetify = new Vuetify()
  })

  afterEach(() => {
    delete global.fetch
  })

  describe('Component tree renders', () => {
    it('mounts without errors', () => {
      global.fetch = createMockFetch({ '/status': { branches: ['main'] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore({
          status: 'up_to_date',
          referenceRepoUrl: 'https://example.com/repo.git',
          detectedFirmwareVersion: '3.5.1',
          activeBranch: '3.5'
        })
      })
      expect(wrapper.exists()).toBe(true)
      wrapper.destroy()
    })

    it('renders all four tabs', () => {
      global.fetch = createMockFetch({ '/status': { branches: [] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore()
      })
      const tabs = wrapper.findAll('.v-tab')
      expect(tabs.length).toBe(4)
      const tabTexts = tabs.wrappers.map(t => t.text())
      expect(tabTexts).toEqual(
        expect.arrayContaining(['Status', 'Changes', 'History', 'Settings'])
      )
      wrapper.destroy()
    })

    it('renders ConfigStatus with real Vuetify list items', async () => {
      global.fetch = createMockFetch({ '/status': { branches: ['main', '3.5'] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore({
          detectedFirmwareVersion: '3.5.1',
          activeBranch: '3.5',
          referenceRepoUrl: 'https://example.com/repo.git',
          lastSyncTimestamp: '2024-01-15T10:30:00Z',
          status: 'up_to_date'
        })
      })
      await flush()

      const html = wrapper.html()
      expect(html).toContain('3.5.1')
      expect(html).toContain('https://example.com/repo.git')
      expect(html).toContain('Up to Date')
      wrapper.destroy()
    })

    it('renders Check for Updates button that is clickable when repo URL set', () => {
      global.fetch = createMockFetch({ '/status': { branches: [] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore({
          referenceRepoUrl: 'https://example.com/repo.git',
          status: 'up_to_date'
        })
      })
      const btn = wrapper.findAll('.v-btn').wrappers.find(
        b => b.text().includes('Check for Updates')
      )
      expect(btn).toBeTruthy()
      expect(btn.attributes('disabled')).toBeUndefined()
      wrapper.destroy()
    })

    it('disables Check for Updates button when no repo URL', () => {
      global.fetch = createMockFetch({ '/status': { branches: [] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore({ status: 'not_configured' })
      })
      const btn = wrapper.findAll('.v-btn').wrappers.find(
        b => b.text().includes('Check for Updates')
      )
      expect(btn).toBeTruthy()
      expect(btn.attributes('disabled')).toBe('disabled')
      wrapper.destroy()
    })
  })

  describe('Settings tab renders with real Vuetify inputs', () => {
    it('renders text fields and save button', async () => {
      global.fetch = createMockFetch({ '/status': { branches: [] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore({
          referenceRepoUrl: 'https://example.com/repo.git',
          firmwareBranchOverride: '',
          status: 'up_to_date'
        })
      })

      const tabs = wrapper.findAll('.v-tab')
      await tabs.at(3).trigger('click')
      await flush()

      const html = wrapper.html()
      expect(html).toContain('Reference Repository URL')
      expect(html).toContain('Branch Override')
      expect(html).toContain('Save Settings')
      wrapper.destroy()
    })
  })

  describe('ConfigDiff renders no-changes state', () => {
    it('shows "No changes detected" when diffFiles empty', async () => {
      global.fetch = createMockFetch({ '/status': { branches: [] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore()
      })

      const tabs = wrapper.findAll('.v-tab')
      await tabs.at(1).trigger('click')
      await flush()

      const html = wrapper.html()
      expect(html).toContain('No changes detected')
      wrapper.destroy()
    })
  })

  describe('BackupHistory renders empty state', () => {
    it('shows "No backups yet" when backups empty', async () => {
      global.fetch = createMockFetch({ '/status': { branches: [] } })
      const wrapper = mount(MeltingplotConfig, {
        localVue,
        vuetify,
        store: createStore()
      })

      const tabs = wrapper.findAll('.v-tab')
      await tabs.at(2).trigger('click')
      await flush()

      const html = wrapper.html()
      expect(html).toContain('No backups yet')
      wrapper.destroy()
    })
  })
})
