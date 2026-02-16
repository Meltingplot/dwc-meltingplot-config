/**
 * Integration test: End-to-end user flows.
 *
 * Simulates complete user journeys through the plugin with a mock
 * HTTP backend. These tests verify that clicking buttons triggers
 * the correct API calls and updates the UI accordingly — the same
 * flow that would happen on a real DWC instance with a real DSF backend.
 */
import { mount, createLocalVue } from '@vue/test-utils';
import Vuex from 'vuex';
import Vuetify from 'vuetify';
import MeltingplotConfig from '../../../src/MeltingplotConfig.vue';
import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';

const localVue = createLocalVue();
localVue.use(Vuex);

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
    });
}

/**
 * Stateful mock HTTP server that tracks request history
 * and returns different responses per endpoint.
 */
class MockBackend {
    constructor() {
        this.routes = {};
        this.requests = [];
        global.fetch = jest.fn((url, opts) => {
            this.requests.push({ url, opts });
            for (const [pattern, handler] of Object.entries(this.routes)) {
                if (url.includes(pattern)) {
                    const data = typeof handler === 'function' ? handler(url, opts) : handler;
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve(data),
                        text: () => Promise.resolve(JSON.stringify(data))
                    });
                }
            }
            return Promise.resolve({
                ok: false,
                status: 404,
                statusText: 'Not Found',
                text: () => Promise.resolve('Not Found')
            });
        });
    }

    on(pattern, response) {
        this.routes[pattern] = response;
        return this;
    }

    requestsTo(pattern) {
        return this.requests.filter(r => r.url.includes(pattern));
    }

    lastRequestTo(pattern) {
        const matches = this.requestsTo(pattern);
        return matches[matches.length - 1];
    }
}

function flush(ms = 10) {
    return new Promise(r => setTimeout(r, ms));
}

describe('User flow: Sync and view diff', () => {
    let vuetify, backend;

    beforeEach(() => {
        vuetify = new Vuetify();
        backend = new MockBackend();
    });

    afterEach(() => {
        delete global.fetch;
    });

    it('full sync flow: click Check for Updates → API calls → diff displayed', async () => {
        backend
            .on('/status', { branches: ['main', '3.5'] })
            .on('/sync', { status: 'synced', activeBranch: '3.5' })
            .on('/diff', {
                files: [
                    { file: 'sys/config.g', status: 'modified' },
                    { file: 'sys/homex.g', status: 'missing' }
                ]
            })
            .on('/branches', { branches: ['main', '3.5', '3.5.1'] });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git',
                status: 'updates_available',
                activeBranch: '3.5',
                detectedFirmwareVersion: '3.5.1'
            })
        });
        await flush();

        // 1. Click "Check for Updates"
        const syncBtn = wrapper.findAll('.v-btn').wrappers.find(
            b => b.text().includes('Check for Updates')
        );
        expect(syncBtn).toBeTruthy();
        await syncBtn.trigger('click');
        await flush();

        // 2. Verify /sync was called with POST
        const syncReq = backend.lastRequestTo('/sync');
        expect(syncReq).toBeTruthy();
        expect(syncReq.opts.method).toBe('POST');

        // 3. Verify /diff was called to load changes
        expect(backend.requestsTo('/diff').length).toBeGreaterThan(0);

        // 4. Verify internal state updated
        expect(wrapper.vm.diffFiles.length).toBe(2);
        expect(wrapper.vm.syncing).toBe(false);

        // 5. Verify success notification shown
        expect(wrapper.vm.snackbar.show).toBe(true);
        expect(wrapper.vm.snackbar.color).toBe('success');

        // 6. Navigate to Changes tab and verify badge
        const changesTab = wrapper.findAll('.v-tab').at(1);
        expect(changesTab.text()).toContain('2');

        wrapper.destroy();
    });

    it('sync error flow: network failure shows error notification', async () => {
        backend.on('/status', { branches: [] });
        // /sync will 404 since we don't register it

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git',
                status: 'not_configured'
            })
        });
        await flush();

        const syncBtn = wrapper.findAll('.v-btn').wrappers.find(
            b => b.text().includes('Check for Updates')
        );
        await syncBtn.trigger('click');
        await flush();

        expect(wrapper.vm.snackbar.show).toBe(true);
        expect(wrapper.vm.snackbar.color).toBe('error');
        expect(wrapper.vm.snackbar.text).toContain('Sync failed');
        expect(wrapper.vm.syncing).toBe(false);

        wrapper.destroy();
    });
});

describe('User flow: Apply changes', () => {
    let vuetify, backend;

    beforeEach(() => {
        vuetify = new Vuetify();
        backend = new MockBackend();
    });

    afterEach(() => {
        delete global.fetch;
    });

    it('apply all: confirm dialog → API call → success', async () => {
        backend
            .on('/status', { branches: [] })
            .on('/apply', { applied: ['sys/config.g'] })
            .on('/diff', { files: [] });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git',
                status: 'updates_available'
            })
        });
        await flush();

        // Pre-populate diff files
        wrapper.vm.diffFiles = [
            { file: 'sys/config.g', status: 'modified' }
        ];
        await flush();

        // Navigate to Changes tab
        const tabs = wrapper.findAll('.v-tab');
        await tabs.at(1).trigger('click');
        await flush();

        // Click Apply All
        const applyBtn = wrapper.findAll('.v-btn').wrappers.find(
            b => b.text().includes('Apply All')
        );
        expect(applyBtn).toBeTruthy();
        await applyBtn.trigger('click');

        // Confirm dialog should appear
        expect(wrapper.vm.confirmDialog.show).toBe(true);
        expect(wrapper.vm.confirmDialog.title).toBe('Apply All Changes');

        // Click confirm
        await wrapper.vm.confirmDialog.action();
        await flush();

        // Verify /apply was called
        const applyReq = backend.lastRequestTo('/apply');
        expect(applyReq).toBeTruthy();
        expect(applyReq.opts.method).toBe('POST');

        // Verify success notification
        expect(wrapper.vm.snackbar.color).toBe('success');

        wrapper.destroy();
    });

    it('apply single file: sends correct file path', async () => {
        backend
            .on('/status', { branches: [] })
            .on('/apply?file=', { applied: ['sys/config.g'] })
            .on('/diff', { files: [] });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git'
            })
        });
        await flush();

        // Trigger applyFile programmatically (simulates child emit)
        wrapper.vm.applyFile('sys/config.g');
        expect(wrapper.vm.confirmDialog.show).toBe(true);
        expect(wrapper.vm.confirmDialog.message).toContain('sys/config.g');

        await wrapper.vm.confirmDialog.action();
        await flush();

        const req = backend.requestsTo('/apply?file=').find(
            r => r.url.includes('sys%2Fconfig.g')
        );
        expect(req).toBeTruthy();

        wrapper.destroy();
    });

    it('apply hunks: sends correct hunk indices in POST body', async () => {
        backend
            .on('/status', { branches: [] })
            .on('/applyHunks', { applied: [0, 2], failed: [] })
            .on('/diff', { files: [] });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git'
            })
        });
        await flush();

        // Simulate child component emitting apply-hunks
        wrapper.vm.applyHunks({ file: 'sys/config.g', hunks: [0, 2] });
        expect(wrapper.vm.confirmDialog.show).toBe(true);

        await wrapper.vm.confirmDialog.action();
        await flush();

        const req = backend.lastRequestTo('/applyHunks');
        expect(req).toBeTruthy();
        const body = JSON.parse(req.opts.body);
        expect(body.hunks).toEqual([0, 2]);

        wrapper.destroy();
    });
});

describe('User flow: Backup and restore', () => {
    let vuetify, backend;

    beforeEach(() => {
        vuetify = new Vuetify();
        backend = new MockBackend();
    });

    afterEach(() => {
        delete global.fetch;
    });

    it('load backups → display → restore flow', async () => {
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
            .on('/diff', { files: [] });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git'
            })
        });
        await flush();

        // Navigate to History tab
        const tabs = wrapper.findAll('.v-tab');
        await tabs.at(2).trigger('click');
        await flush();

        // Load backups
        await wrapper.vm.loadBackups();
        await flush();

        // Verify backup data loaded
        expect(wrapper.vm.backups.length).toBe(1);
        expect(wrapper.vm.backups[0].hash).toBe('abc123def456');

        // Verify backup info rendered
        const html = wrapper.html();
        expect(html).toContain('Pre-apply backup');
        expect(html).toContain('abc123de'); // hash truncated to 8 chars

        // Restore backup
        wrapper.vm.restoreBackup('abc123def456');
        expect(wrapper.vm.confirmDialog.show).toBe(true);

        await wrapper.vm.confirmDialog.action();
        await flush();

        const req = backend.lastRequestTo('/restore?hash=');
        expect(req).toBeTruthy();
        expect(req.url).toContain('abc123def456');
        expect(wrapper.vm.snackbar.color).toBe('success');

        wrapper.destroy();
    });

    it('download backup opens correct URL', async () => {
        backend.on('/status', { branches: [] });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore()
        });
        await flush();

        window.open = jest.fn();
        wrapper.vm.downloadBackup('abc123');
        expect(window.open).toHaveBeenCalledWith(
            expect.stringContaining('/backupDownload?hash=abc123'),
            '_blank'
        );

        wrapper.destroy();
    });
});

describe('User flow: Save settings', () => {
    let vuetify, backend;

    beforeEach(() => {
        vuetify = new Vuetify();
        backend = new MockBackend();
    });

    afterEach(() => {
        delete global.fetch;
    });

    it('enter settings → save → verify POST body', async () => {
        backend
            .on('/status', { branches: [] })
            .on('/settings', { ok: true });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://old.com/repo.git',
                firmwareBranchOverride: ''
            })
        });
        await flush();

        // Navigate to Settings tab
        const tabs = wrapper.findAll('.v-tab');
        await tabs.at(3).trigger('click');
        await flush();

        // Modify settings via vm (simulates user typing)
        wrapper.vm.settings.referenceRepoUrl = 'https://new.com/repo.git';
        wrapper.vm.settings.firmwareBranchOverride = '3.5';
        wrapper.vm.settings.syncInterval = 'daily';

        // Click Save
        await wrapper.vm.saveSettings();
        await flush();

        const req = backend.lastRequestTo('/settings');
        expect(req).toBeTruthy();
        const body = JSON.parse(req.opts.body);
        expect(body.referenceRepoUrl).toBe('https://new.com/repo.git');
        expect(body.firmwareBranchOverride).toBe('3.5');
        expect(body.syncInterval).toBe('daily');

        expect(wrapper.vm.snackbar.color).toBe('success');

        wrapper.destroy();
    });
});

describe('User flow: Tab navigation preserves state', () => {
    let vuetify, backend;

    beforeEach(() => {
        vuetify = new Vuetify();
        backend = new MockBackend();
    });

    afterEach(() => {
        delete global.fetch;
    });

    it('diff state persists when switching between tabs', async () => {
        backend
            .on('/status', { branches: [] })
            .on('/diff', {
                files: [
                    { file: 'sys/config.g', status: 'modified' },
                    { file: 'sys/homex.g', status: 'modified' }
                ]
            });

        const wrapper = mount(MeltingplotConfig, {
            localVue,
            vuetify,
            store: createStore({
                referenceRepoUrl: 'https://example.com/repo.git'
            })
        });
        await flush();

        // Load diff
        await wrapper.vm.loadDiff();
        expect(wrapper.vm.diffFiles.length).toBe(2);

        // Switch to Settings tab
        const tabs = wrapper.findAll('.v-tab');
        await tabs.at(3).trigger('click');
        await flush();

        // Switch back to Changes tab
        await tabs.at(1).trigger('click');
        await flush();

        // Diff data should still be there
        expect(wrapper.vm.diffFiles.length).toBe(2);
        expect(wrapper.vm.changedFileCount).toBe(2);

        wrapper.destroy();
    });
});
