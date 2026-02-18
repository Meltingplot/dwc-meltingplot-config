import { mount, createLocalVue } from '@vue/test-utils'
import Vuex from 'vuex'
import Vuetify from 'vuetify'
import MeltingplotConfig from '../../../src/MeltingplotConfig.vue'
import { describe, it, expect, beforeEach, afterEach } from '@jest/globals'

const localVue = createLocalVue()
localVue.use(Vuex)

function createStore(pluginData = {}) {
  return new Vuex.Store({
    modules: {
      'machine/model': {
        namespaced: true,
        state: {
          plugins: {
            MeltingplotConfig: { data: pluginData }
          }
        }
      }
    }
  })
}

class MockBackend {
  constructor() {
    this.routes = {}
    this.requests = []
    global.fetch = jest.fn((url, opts) => {
      this.requests.push({ url, opts })
      for (const [pattern, handler] of Object.entries(this.routes)) {
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
        text: () => Promise.resolve('Not Found')
      })
    })
  }

  on(pattern, response) {
    this.routes[pattern] = response
    return this
  }

  requestsTo(pattern) {
    return this.requests.filter(r => r.url.includes(pattern))
  }

  lastRequestTo(pattern) {
    const matches = this.requestsTo(pattern)
    return matches[matches.length - 1]
  }
}

function flush(ms = 10) {
  return new Promise(r => setTimeout(r, ms))
}

describe('User flow: Sync and view diff', () => {
  let vuetify, backend

  beforeEach(() => {
    vuetify = new Vuetify()
    backend = new MockBackend()
  })

  afterEach(() => {
    delete global.fetch
  })

  it('full sync flow: click Check for Updates -> API calls -> diff displayed', async () => {
    backend
      .on('/status', { branches: ['main', '3.5'] })
      .on('/sync', { status: 'synced', activeBranch: '3.5' })
      .on('/diff', {
        files: [
          { file: 'sys/config.g', status: 'modified' },
          { file: 'sys/homex.g', status: 'missing' }
        ]
      })
      .on('/branches', { branches: ['main', '3.5', '3.5.1'] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git',
        status: 'updates_available',
        activeBranch: '3.5',
        detectedFirmwareVersion: '3.5.1'
      })
    })
    await flush()

    const syncBtn = wrapper.findAll('.v-btn').wrappers.find(
      b => b.text().includes('Check for Updates')
    )
    expect(syncBtn).toBeTruthy()
    await syncBtn.trigger('click')
    await flush()

    const syncReq = backend.lastRequestTo('/sync')
    expect(syncReq).toBeTruthy()
    expect(syncReq.opts.method).toBe('POST')

    expect(backend.requestsTo('/diff').length).toBeGreaterThan(0)
    expect(wrapper.vm.diffFiles.length).toBe(2)
    expect(wrapper.vm.syncing).toBe(false)
    expect(wrapper.vm.snackbar.show).toBe(true)
    expect(wrapper.vm.snackbar.color).toBe('success')

    const changesTab = wrapper.findAll('.v-tab').at(1)
    expect(changesTab.text()).toContain('2')

    wrapper.destroy()
  })

  it('sync error flow: network failure shows error notification', async () => {
    backend.on('/status', { branches: [] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git',
        status: 'not_configured'
      })
    })
    await flush()

    const syncBtn = wrapper.findAll('.v-btn').wrappers.find(
      b => b.text().includes('Check for Updates')
    )
    await syncBtn.trigger('click')
    await flush()

    expect(wrapper.vm.snackbar.show).toBe(true)
    expect(wrapper.vm.snackbar.color).toBe('error')
    expect(wrapper.vm.snackbar.text).toContain('Sync failed')
    expect(wrapper.vm.syncing).toBe(false)

    wrapper.destroy()
  })
})

describe('User flow: Apply changes', () => {
  let vuetify, backend

  beforeEach(() => {
    vuetify = new Vuetify()
    backend = new MockBackend()
  })

  afterEach(() => {
    delete global.fetch
  })

  it('apply all: confirm dialog -> API call -> success', async () => {
    backend
      .on('/status', { branches: [] })
      .on('/apply', { applied: ['sys/config.g'] })
      .on('/diff', { files: [] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git',
        status: 'updates_available'
      })
    })
    await flush()

    wrapper.vm.diffFiles = [{ file: 'sys/config.g', status: 'modified' }]
    await flush()

    const tabs = wrapper.findAll('.v-tab')
    await tabs.at(1).trigger('click')
    await flush()

    const applyBtn = wrapper.findAll('.v-btn').wrappers.find(
      b => b.text().includes('Apply All')
    )
    expect(applyBtn).toBeTruthy()
    await applyBtn.trigger('click')

    expect(wrapper.vm.confirmDialog.show).toBe(true)
    expect(wrapper.vm.confirmDialog.title).toBe('Apply All Changes')

    await wrapper.vm.confirmDialog.action()
    await flush()

    const applyReq = backend.lastRequestTo('/apply')
    expect(applyReq).toBeTruthy()
    expect(applyReq.opts.method).toBe('POST')
    expect(wrapper.vm.snackbar.color).toBe('success')

    wrapper.destroy()
  })

  it('apply single file: sends correct file path', async () => {
    backend
      .on('/status', { branches: [] })
      .on('/apply?file=', { applied: ['sys/config.g'] })
      .on('/diff', { files: [] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git'
      })
    })
    await flush()

    wrapper.vm.applyFile('sys/config.g')
    expect(wrapper.vm.confirmDialog.show).toBe(true)
    expect(wrapper.vm.confirmDialog.message).toContain('sys/config.g')

    await wrapper.vm.confirmDialog.action()
    await flush()

    const req = backend.requestsTo('/apply?file=').find(
      r => r.url.includes('sys%2Fconfig.g')
    )
    expect(req).toBeTruthy()

    wrapper.destroy()
  })

  it('apply hunks: sends correct hunk indices in POST body', async () => {
    backend
      .on('/status', { branches: [] })
      .on('/applyHunks', { applied: [0, 2], failed: [] })
      .on('/diff', { files: [] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git'
      })
    })
    await flush()

    wrapper.vm.applyHunks({ file: 'sys/config.g', hunks: [0, 2] })
    expect(wrapper.vm.confirmDialog.show).toBe(true)

    await wrapper.vm.confirmDialog.action()
    await flush()

    const req = backend.lastRequestTo('/applyHunks')
    expect(req).toBeTruthy()
    const body = JSON.parse(req.opts.body)
    expect(body.hunks).toEqual([0, 2])

    wrapper.destroy()
  })
})

describe('User flow: Backup and restore', () => {
  let vuetify, backend

  beforeEach(() => {
    vuetify = new Vuetify()
    backend = new MockBackend()
  })

  afterEach(() => {
    delete global.fetch
  })

  it('load backups -> display -> restore flow', async () => {
    backend
      .on('/status', { branches: [] })
      .on('/backups', {
        backups: [
          {
            hash: 'abc123def456',
            message: 'Pre-apply backup',
            timestamp: '2024-01-15T10:30:00Z',
            filesChanged: 3
          }
        ]
      })
      .on('/restore', { restored: ['sys/config.g'] })
      .on('/diff', { files: [] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git'
      })
    })
    await flush()

    const tabs = wrapper.findAll('.v-tab')
    await tabs.at(2).trigger('click')
    await flush()

    await wrapper.vm.loadBackups()
    await flush()

    expect(wrapper.vm.backups.length).toBe(1)
    expect(wrapper.vm.backups[0].hash).toBe('abc123def456')

    const html = wrapper.html()
    expect(html).toContain('Pre-apply backup')
    expect(html).toContain('abc123de')

    wrapper.vm.restoreBackup('abc123def456')
    expect(wrapper.vm.confirmDialog.show).toBe(true)

    await wrapper.vm.confirmDialog.action()
    await flush()

    const req = backend.lastRequestTo('/restore?hash=')
    expect(req).toBeTruthy()
    expect(req.url).toContain('abc123def456')
    expect(wrapper.vm.snackbar.color).toBe('success')

    wrapper.destroy()
  })

  it('download backup fetches ZIP with .zip filename', async () => {
    backend.on('/status', { branches: [] })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore()
    })
    await flush()

    const mockBlob = new Blob(['PK'], { type: 'application/zip' })
    const origFetch = global.fetch
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
    })
    URL.createObjectURL = jest.fn().mockReturnValue('blob:fake')
    URL.revokeObjectURL = jest.fn()

    const clickSpy = jest.fn()
    const origCreateElement = document.createElement.bind(document)
    jest.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreateElement(tag)
      if (tag === 'a') {
        el.click = clickSpy
      }
      return el
    })

    await wrapper.vm.downloadBackup('abc123')

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/backupDownload?hash=abc123')
    )
    expect(clickSpy).toHaveBeenCalled()

    document.createElement.mockRestore()
    global.fetch = origFetch

    wrapper.destroy()
  })
})

describe('User flow: Save settings', () => {
  let vuetify, backend

  beforeEach(() => {
    vuetify = new Vuetify()
    backend = new MockBackend()
  })

  afterEach(() => {
    delete global.fetch
  })

  it('enter settings -> save -> verify POST body', async () => {
    backend
      .on('/status', { branches: [] })
      .on('/settings', { ok: true })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://old.com/repo.git',
        firmwareBranchOverride: ''
      })
    })
    await flush()

    const tabs = wrapper.findAll('.v-tab')
    await tabs.at(3).trigger('click')
    await flush()

    wrapper.vm.settings.referenceRepoUrl = 'https://new.com/repo.git'
    wrapper.vm.settings.firmwareBranchOverride = '3.5'
    wrapper.vm.settings.syncInterval = 'daily'

    await wrapper.vm.saveSettings()
    await flush()

    const req = backend.lastRequestTo('/settings')
    expect(req).toBeTruthy()
    const body = JSON.parse(req.opts.body)
    expect(body.referenceRepoUrl).toBe('https://new.com/repo.git')
    expect(body.firmwareBranchOverride).toBe('3.5')
    expect(body.syncInterval).toBe('daily')

    expect(wrapper.vm.snackbar.color).toBe('success')

    wrapper.destroy()
  })
})

describe('User flow: Tab navigation preserves state', () => {
  let vuetify, backend

  beforeEach(() => {
    vuetify = new Vuetify()
    backend = new MockBackend()
  })

  afterEach(() => {
    delete global.fetch
  })

  it('diff state persists when switching between tabs', async () => {
    backend
      .on('/status', { branches: [] })
      .on('/diff', {
        files: [
          { file: 'sys/config.g', status: 'modified' },
          { file: 'sys/homex.g', status: 'modified' }
        ]
      })

    const wrapper = mount(MeltingplotConfig, {
      localVue,
      vuetify,
      store: createStore({
        referenceRepoUrl: 'https://example.com/repo.git'
      })
    })
    await flush()

    await wrapper.vm.loadDiff()
    expect(wrapper.vm.diffFiles.length).toBe(2)

    const tabs = wrapper.findAll('.v-tab')
    await tabs.at(3).trigger('click')
    await flush()

    await tabs.at(1).trigger('click')
    await flush()

    expect(wrapper.vm.diffFiles.length).toBe(2)
    expect(wrapper.vm.changedFileCount).toBe(2)

    wrapper.destroy()
  })
})
