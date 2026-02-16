import { shallowMount } from '@vue/test-utils';
import ConfigDiff from '../../src/components/ConfigDiff.vue';

function mountComponent(propsData = {}) {
    return shallowMount(ConfigDiff, {
        vuetify: global.createVuetify(),
        propsData
    });
}

describe('ConfigDiff — loadFileDetail', () => {
    afterEach(() => {
        if (global.fetch && global.fetch.mockRestore) {
            global.fetch.mockRestore();
        }
        delete global.fetch;
    });

    describe('loadFileDetail', () => {
        it('fetches hunks for modified file', async () => {
            const wrapper = mountComponent();
            const file = { file: 'sys/config.g', status: 'modified' };

            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({
                        hunks: [
                            { index: 0, header: '@@ -1,3 +1,3 @@', lines: [' line1', '-old', '+new'], summary: 'Line 1' },
                            { index: 1, header: '@@ -5,2 +5,2 @@', lines: [' line5', '-old2', '+new2'], summary: 'Line 5' }
                        ]
                    })
                })
            );

            await wrapper.vm.loadFileDetail(file);

            expect(global.fetch).toHaveBeenCalledTimes(1);
            const url = global.fetch.mock.calls[0][0];
            expect(url).toContain('/diff/');
            expect(url).toContain('sys%2Fconfig.g');

            expect(file.hunks).toHaveLength(2);
            // All hunks should have selected=true by default
            expect(file.hunks[0].selected).toBe(true);
            expect(file.hunks[1].selected).toBe(true);
            expect(file.loadingDetail).toBe(false);
        });

        it('skips fetch if hunks already loaded', async () => {
            const wrapper = mountComponent();
            const file = {
                file: 'sys/config.g',
                status: 'modified',
                hunks: [{ index: 0, selected: true }]
            };

            global.fetch = jest.fn();
            await wrapper.vm.loadFileDetail(file);
            expect(global.fetch).not.toHaveBeenCalled();
        });

        it('skips fetch for non-modified files', async () => {
            const wrapper = mountComponent();
            const file = { file: 'sys/homex.g', status: 'missing' };

            global.fetch = jest.fn();
            await wrapper.vm.loadFileDetail(file);
            expect(global.fetch).not.toHaveBeenCalled();
        });

        it('sets empty hunks on fetch error', async () => {
            const wrapper = mountComponent();
            const file = { file: 'sys/config.g', status: 'modified' };

            global.fetch = jest.fn(() => Promise.reject(new Error('network error')));

            await wrapper.vm.loadFileDetail(file);
            expect(file.hunks).toEqual([]);
            expect(file.loadingDetail).toBe(false);
        });

        it('sets empty hunks on non-ok response', async () => {
            const wrapper = mountComponent();
            const file = { file: 'sys/config.g', status: 'modified' };

            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: false,
                    statusText: 'Not Found'
                })
            );

            await wrapper.vm.loadFileDetail(file);
            expect(file.hunks).toEqual([]);
        });

        it('handles response with empty hunks array', async () => {
            const wrapper = mountComponent();
            const file = { file: 'sys/config.g', status: 'modified' };

            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ hunks: [] })
                })
            );

            await wrapper.vm.loadFileDetail(file);
            expect(file.hunks).toEqual([]);
        });

        it('handles response with null hunks', async () => {
            const wrapper = mountComponent();
            const file = { file: 'sys/config.g', status: 'modified' };

            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ hunks: null })
                })
            );

            await wrapper.vm.loadFileDetail(file);
            expect(file.hunks).toEqual([]);
        });
    });

    describe('selectAllHunks with no hunks', () => {
        it('does not throw when hunks is undefined', () => {
            const wrapper = mountComponent();
            const file = {};
            expect(() => wrapper.vm.selectAllHunks(file)).not.toThrow();
        });
    });

    describe('deselectAllHunks with no hunks', () => {
        it('does not throw when hunks is undefined', () => {
            const wrapper = mountComponent();
            const file = {};
            expect(() => wrapper.vm.deselectAllHunks(file)).not.toThrow();
        });
    });
});
