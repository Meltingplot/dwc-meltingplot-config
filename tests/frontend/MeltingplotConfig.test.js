import { shallowMount, createLocalVue } from '@vue/test-utils';
import Vuex from 'vuex';
import MeltingplotConfig from '../../src/MeltingplotConfig.vue';

const localVue = createLocalVue();
localVue.use(Vuex);

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
    });
}

function mountComponent(options = {}) {
    const store = createStore(options.pluginData || {});
    // Stub child components to avoid rendering them
    return shallowMount(MeltingplotConfig, {
        localVue,
        store,
        vuetify: global.createVuetify(),
        stubs: {
            'config-status': true,
            'config-diff': true,
            'backup-history': true
        }
    });
}

// Helper: mock fetch to return JSON
function mockFetchSuccess(data) {
    global.fetch = jest.fn(() =>
        Promise.resolve({
            ok: true,
            json: () => Promise.resolve(data),
            text: () => Promise.resolve(JSON.stringify(data))
        })
    );
}

function mockFetchError(status = 500, text = 'Server Error') {
    global.fetch = jest.fn(() =>
        Promise.resolve({
            ok: false,
            status,
            statusText: text,
            text: () => Promise.resolve(text),
            json: () => Promise.resolve({ error: text })
        })
    );
}

afterEach(() => {
    if (global.fetch && global.fetch.mockRestore) {
        global.fetch.mockRestore();
    }
    delete global.fetch;
});

describe('MeltingplotConfig', () => {
    describe('initial state', () => {
        it('has correct default data values', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            expect(wrapper.vm.activeTab).toBe(0);
            expect(wrapper.vm.syncing).toBe(false);
            expect(wrapper.vm.loadingDiff).toBe(false);
            expect(wrapper.vm.loadingBackups).toBe(false);
            expect(wrapper.vm.diffFiles).toEqual([]);
            expect(wrapper.vm.backups).toEqual([]);
        });

        it('calls loadStatus on mount', () => {
            mockFetchSuccess({ branches: ['main', '3.5'] });
            const wrapper = mountComponent();
            expect(global.fetch).toHaveBeenCalled();
            const url = global.fetch.mock.calls[0][0];
            expect(url).toContain('/status');
        });
    });

    describe('pluginData computed', () => {
        it('extracts data from vuex store', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent({
                pluginData: {
                    referenceRepoUrl: 'https://example.com/repo.git',
                    detectedFirmwareVersion: '3.5.1',
                    activeBranch: '3.5',
                    status: 'up_to_date'
                }
            });
            expect(wrapper.vm.pluginData.referenceRepoUrl).toBe('https://example.com/repo.git');
            expect(wrapper.vm.pluginData.detectedFirmwareVersion).toBe('3.5.1');
            expect(wrapper.vm.pluginData.activeBranch).toBe('3.5');
            expect(wrapper.vm.pluginData.status).toBe('up_to_date');
        });

        it('provides safe defaults when plugin data missing', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent({ pluginData: {} });
            expect(wrapper.vm.pluginData.referenceRepoUrl).toBe('');
            expect(wrapper.vm.pluginData.status).toBe('not_configured');
        });
    });

    describe('changedFileCount', () => {
        it('counts files with non-unchanged status', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.diffFiles = [
                { file: 'sys/config.g', status: 'modified' },
                { file: 'sys/homex.g', status: 'unchanged' },
                { file: 'sys/homey.g', status: 'missing' }
            ];
            expect(wrapper.vm.changedFileCount).toBe(2);
        });

        it('returns 0 when all files unchanged', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.diffFiles = [
                { file: 'sys/config.g', status: 'unchanged' }
            ];
            expect(wrapper.vm.changedFileCount).toBe(0);
        });
    });

    describe('apiGet', () => {
        it('fetches and returns JSON', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchSuccess({ key: 'value' });
            const result = await wrapper.vm.apiGet('/test');
            expect(result.key).toBe('value');
        });

        it('throws on non-ok response', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchError(404, 'Not Found');
            await expect(wrapper.vm.apiGet('/bad')).rejects.toThrow('Not Found');
        });
    });

    describe('apiPost', () => {
        it('posts with JSON body', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchSuccess({ ok: true });
            await wrapper.vm.apiPost('/test', { key: 'value' });

            const lastCall = global.fetch.mock.calls[global.fetch.mock.calls.length - 1];
            const opts = lastCall[1];
            expect(opts.method).toBe('POST');
            expect(opts.headers['Content-Type']).toBe('application/json');
            expect(JSON.parse(opts.body)).toEqual({ key: 'value' });
        });

        it('posts without body when null', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchSuccess({ ok: true });
            await wrapper.vm.apiPost('/test');

            const lastCall = global.fetch.mock.calls[global.fetch.mock.calls.length - 1];
            const opts = lastCall[1];
            expect(opts.method).toBe('POST');
            expect(opts.headers).toBeUndefined();
            expect(opts.body).toBeUndefined();
        });

        it('throws on non-ok response', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchError(500, 'Internal Error');
            await expect(wrapper.vm.apiPost('/bad')).rejects.toThrow('Internal Error');
        });
    });

    describe('loadStatus', () => {
        it('populates availableBranches', async () => {
            mockFetchSuccess({ branches: ['main', '3.5'] });
            const wrapper = mountComponent();
            await wrapper.vm.$nextTick();
            // Wait for the loadStatus promise
            await new Promise(r => setTimeout(r, 0));
            expect(wrapper.vm.availableBranches).toEqual(['main', '3.5']);
        });

        it('silently handles errors', async () => {
            mockFetchError(500, 'Server Error');
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));
            // Should not throw, branches remain empty
            expect(wrapper.vm.availableBranches).toEqual([]);
        });

        it('auto-loads diff when referenceRepoUrl is configured', async () => {
            mockFetchSuccess({
                branches: ['main'],
                referenceRepoUrl: 'https://example.com/repo.git',
                status: 'up_to_date'
            });
            const wrapper = mountComponent();
            await wrapper.vm.$nextTick();
            await new Promise(r => setTimeout(r, 10));
            // loadStatus should have triggered loadDiff
            const diffCalls = global.fetch.mock.calls.filter(c => c[0].includes('/diff'));
            expect(diffCalls.length).toBeGreaterThan(0);
        });

        it('does not load diff when referenceRepoUrl is empty', async () => {
            mockFetchSuccess({
                branches: ['main'],
                referenceRepoUrl: '',
                status: 'not_configured'
            });
            const wrapper = mountComponent();
            await wrapper.vm.$nextTick();
            await new Promise(r => setTimeout(r, 10));
            // No diff call should have been made
            const diffCalls = global.fetch.mock.calls.filter(c => c[0].includes('/diff'));
            expect(diffCalls.length).toBe(0);
        });

        it('populates diffFiles on startup when repo is configured', async () => {
            const files = [
                { file: 'sys/config.g', status: 'modified', hunks: [] },
                { file: 'sys/homex.g', status: 'unchanged', hunks: [] }
            ];
            // Mock returns the same response for all calls; loadDiff
            // will parse `files` from it.
            mockFetchSuccess({
                branches: ['main'],
                referenceRepoUrl: 'https://example.com/repo.git',
                status: 'up_to_date',
                files
            });
            const wrapper = mountComponent();
            await wrapper.vm.$nextTick();
            await new Promise(r => setTimeout(r, 10));
            expect(wrapper.vm.diffFiles).toEqual(files);
        });
    });

    describe('checkForUpdates', () => {
        it('sets syncing during operation', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ activeBranch: '3.5', branches: ['main', '3.5'] });
            const promise = wrapper.vm.checkForUpdates();
            expect(wrapper.vm.syncing).toBe(true);
            await promise;
            expect(wrapper.vm.syncing).toBe(false);
        });

        it('shows success notification on sync', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ files: [], branches: ['main'] });
            await wrapper.vm.checkForUpdates();
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('success');
        });

        it('shows error notification on failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchError(500, 'Sync failed');
            await wrapper.vm.checkForUpdates();
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('error');
            expect(wrapper.vm.snackbar.text).toContain('Sync failed');
        });
    });

    describe('loadDiff', () => {
        it('loads diff files', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            const files = [
                { file: 'sys/config.g', status: 'modified', hunks: [] }
            ];
            mockFetchSuccess({ files });
            await wrapper.vm.loadDiff();
            expect(wrapper.vm.diffFiles).toEqual(files);
            expect(wrapper.vm.loadingDiff).toBe(false);
        });

        it('sets loadingDiff during operation', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ files: [] });
            const promise = wrapper.vm.loadDiff();
            expect(wrapper.vm.loadingDiff).toBe(true);
            await promise;
            expect(wrapper.vm.loadingDiff).toBe(false);
        });

        it('shows error notification on failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchError(500, 'Diff error');
            await wrapper.vm.loadDiff();
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('error');
        });
    });

    describe('loadBranches', () => {
        it('populates availableBranches', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ branches: ['main', '3.5', '3.5.1'] });
            await wrapper.vm.loadBranches();
            expect(wrapper.vm.availableBranches).toEqual(['main', '3.5', '3.5.1']);
        });

        it('silently handles errors', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            mockFetchError(500, 'error');
            // Should not throw
            await wrapper.vm.loadBranches();
            // Should not have crashed — snackbar should remain unchanged (non-critical)
            expect(wrapper.vm.snackbar.show).toBe(false);
        });
    });

    describe('loadBackups', () => {
        it('loads backup list', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            const backups = [{ hash: 'abc', message: 'backup' }];
            mockFetchSuccess({ backups });
            await wrapper.vm.loadBackups();
            expect(wrapper.vm.backups).toEqual(backups);
        });

        it('sets loadingBackups during operation', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ backups: [] });
            const promise = wrapper.vm.loadBackups();
            expect(wrapper.vm.loadingBackups).toBe(true);
            await promise;
            expect(wrapper.vm.loadingBackups).toBe(false);
        });

        it('shows error notification on failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchError(500, 'backup error');
            await wrapper.vm.loadBackups();
            expect(wrapper.vm.snackbar.color).toBe('error');
        });
    });

    describe('applyAll', () => {
        it('opens confirmation dialog', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyAll();
            expect(wrapper.vm.confirmDialog.show).toBe(true);
            expect(wrapper.vm.confirmDialog.title).toBe('Apply All Changes');
        });

        it('calls API on confirm', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyAll();

            mockFetchSuccess({ applied: ['sys/config.g'] });
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('success');
        });
    });

    describe('applyFile', () => {
        it('opens confirmation dialog with file name', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyFile('sys/config.g');
            expect(wrapper.vm.confirmDialog.show).toBe(true);
            expect(wrapper.vm.confirmDialog.message).toContain('sys/config.g');
        });

        it('encodes file path in API call', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            wrapper.vm.applyFile('sys/config.g');

            mockFetchSuccess({ applied: ['sys/config.g'] });
            await wrapper.vm.confirmDialog.action();

            // Find the apply call among all fetch calls
            const applyCalls = global.fetch.mock.calls.filter(c => c[0].includes('/apply?file='));
            expect(applyCalls.length).toBeGreaterThan(0);
            expect(applyCalls[0][0]).toContain('/apply?file=sys%2Fconfig.g');
        });
    });

    describe('applyHunks', () => {
        it('opens confirmation with hunk count', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyHunks({ file: 'sys/config.g', hunks: [0, 2] });
            expect(wrapper.vm.confirmDialog.show).toBe(true);
            expect(wrapper.vm.confirmDialog.message).toContain('2');
        });

        it('shows warning on partial failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyHunks({ file: 'sys/config.g', hunks: [0, 1] });

            mockFetchSuccess({ applied: [0], failed: [1] });
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('warning');
            expect(wrapper.vm.snackbar.text).toContain('failed');
        });

        it('shows success when all hunks applied', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyHunks({ file: 'sys/config.g', hunks: [0, 1] });

            mockFetchSuccess({ applied: [0, 1], failed: [] });
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('success');
        });

        it('uses singular for single change', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.applyHunks({ file: 'sys/config.g', hunks: [0] });
            expect(wrapper.vm.confirmDialog.message).toContain('1 selected change ');
        });
    });

    describe('restoreBackup', () => {
        it('opens confirmation dialog', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.restoreBackup('abc123');
            expect(wrapper.vm.confirmDialog.show).toBe(true);
            expect(wrapper.vm.confirmDialog.title).toBe('Restore Backup');
        });

        it('calls restore API on confirm', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.restoreBackup('abc123');

            mockFetchSuccess({ restored: ['sys/config.g'] });
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('success');
        });

        it('shows error on failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.restoreBackup('abc123');

            mockFetchError(500, 'Restore failed');
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('error');
        });
    });

    describe('deleteBackup', () => {
        it('opens confirmation dialog', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.deleteBackup('abc123');
            expect(wrapper.vm.confirmDialog.show).toBe(true);
            expect(wrapper.vm.confirmDialog.title).toBe('Delete Backup');
        });

        it('calls deleteBackup API on confirm', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.deleteBackup('abc123');

            mockFetchSuccess({ deleted: 'abc123' });
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('success');
            expect(wrapper.vm.snackbar.text).toContain('deleted');
        });

        it('shows error on failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.deleteBackup('abc123');

            mockFetchError(400, 'Cannot delete the only backup');
            await wrapper.vm.confirmDialog.action();
            expect(wrapper.vm.snackbar.color).toBe('error');
        });
    });

    describe('downloadBackup', () => {
        it('fetches ZIP and triggers download with .zip filename', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            const mockBlob = new Blob(['PK'], { type: 'application/zip' });
            const mockUrl = 'blob:http://localhost/fake-url';
            global.fetch = jest.fn().mockResolvedValue({
                ok: true,
                blob: () => Promise.resolve(mockBlob),
            });
            URL.createObjectURL = jest.fn().mockReturnValue(mockUrl);
            URL.revokeObjectURL = jest.fn();

            const clickSpy = jest.fn();
            const origCreateElement = document.createElement.bind(document);
            jest.spyOn(document, 'createElement').mockImplementation((tag) => {
                const el = origCreateElement(tag);
                if (tag === 'a') {
                    el.click = clickSpy;
                }
                return el;
            });

            await wrapper.vm.downloadBackup('abc123def456');

            expect(global.fetch).toHaveBeenCalledWith(
                expect.stringContaining('/backupDownload?hash=abc123def456')
            );
            expect(clickSpy).toHaveBeenCalled();
            expect(URL.revokeObjectURL).toHaveBeenCalledWith(mockUrl);

            document.createElement.mockRestore();
        });
    });

    describe('saveSettings', () => {
        it('posts settings to API', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.settings = {
                referenceRepoUrl: 'https://example.com/repo.git',
                firmwareBranchOverride: 'custom',
                syncInterval: 'daily'
            };

            mockFetchSuccess({ ok: true });
            await wrapper.vm.saveSettings();

            const lastCall = global.fetch.mock.calls[global.fetch.mock.calls.length - 1];
            const body = JSON.parse(lastCall[1].body);
            expect(body.referenceRepoUrl).toBe('https://example.com/repo.git');
            expect(body.firmwareBranchOverride).toBe('custom');
            expect(body.syncInterval).toBe('daily');
        });

        it('sets savingSettings during operation', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ ok: true });
            const promise = wrapper.vm.saveSettings();
            expect(wrapper.vm.savingSettings).toBe(true);
            await promise;
            expect(wrapper.vm.savingSettings).toBe(false);
        });

        it('shows success notification', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchSuccess({ ok: true });
            await wrapper.vm.saveSettings();
            expect(wrapper.vm.snackbar.color).toBe('success');
            expect(wrapper.vm.snackbar.text).toContain('Settings saved');
        });

        it('shows error on failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();

            mockFetchError(500, 'Save failed');
            await wrapper.vm.saveSettings();
            expect(wrapper.vm.snackbar.color).toBe('error');
        });
    });

    describe('confirm helper', () => {
        it('sets dialog properties', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            const action = jest.fn();
            wrapper.vm.confirm('Title', 'Message', action);
            expect(wrapper.vm.confirmDialog.show).toBe(true);
            expect(wrapper.vm.confirmDialog.title).toBe('Title');
            expect(wrapper.vm.confirmDialog.message).toBe('Message');
            expect(wrapper.vm.confirmDialog.action).toBe(action);
        });
    });

    describe('notify helper', () => {
        it('sets snackbar properties', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.notify('Test message', 'warning');
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.text).toBe('Test message');
            expect(wrapper.vm.snackbar.color).toBe('warning');
        });

        it('defaults to info color', () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            wrapper.vm.notify('Info message');
            expect(wrapper.vm.snackbar.color).toBe('info');
        });
    });

    describe('fetch network rejection (TypeError)', () => {
        function mockFetchReject() {
            global.fetch = jest.fn(() => Promise.reject(new TypeError('Failed to fetch')));
        }

        it('apiGet rejects on network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchReject();
            await expect(wrapper.vm.apiGet('/test')).rejects.toThrow('Failed to fetch');
        });

        it('apiPost rejects on network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            mockFetchReject();
            await expect(wrapper.vm.apiPost('/test')).rejects.toThrow('Failed to fetch');
        });

        it('loadStatus silently handles network failure', async () => {
            mockFetchReject();
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 10));
            // Should not throw — branches remain empty
            expect(wrapper.vm.availableBranches).toEqual([]);
            // No error notification (loadStatus silently catches)
            expect(wrapper.vm.snackbar.show).toBe(false);
        });

        it('checkForUpdates shows error on network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            mockFetchReject();
            await wrapper.vm.checkForUpdates();
            expect(wrapper.vm.syncing).toBe(false);
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('error');
            expect(wrapper.vm.snackbar.text).toContain('Failed to fetch');
        });

        it('loadDiff shows error and resets loading flag on network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            mockFetchReject();
            await wrapper.vm.loadDiff();
            expect(wrapper.vm.loadingDiff).toBe(false);
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('error');
        });

        it('loadBackups shows error and resets loading flag on network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            mockFetchReject();
            await wrapper.vm.loadBackups();
            expect(wrapper.vm.loadingBackups).toBe(false);
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('error');
        });

        it('loadBranches silently handles network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            mockFetchReject();
            await wrapper.vm.loadBranches();
            // loadBranches silently catches (non-critical)
            expect(wrapper.vm.snackbar.show).toBe(false);
        });

        it('saveSettings shows error on network failure', async () => {
            mockFetchSuccess({ branches: [] });
            const wrapper = mountComponent();
            await new Promise(r => setTimeout(r, 0));

            mockFetchReject();
            await wrapper.vm.saveSettings();
            expect(wrapper.vm.savingSettings).toBe(false);
            expect(wrapper.vm.snackbar.show).toBe(true);
            expect(wrapper.vm.snackbar.color).toBe('error');
        });
    });
});
