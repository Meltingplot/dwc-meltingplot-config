import { shallowMount } from '@vue/test-utils';
import ConfigDiff from '../../src/components/ConfigDiff.vue';

function mountComponent(propsData = {}) {
    return shallowMount(ConfigDiff, {
        vuetify: global.createVuetify(),
        propsData
    });
}

describe('ConfigDiff', () => {
    describe('loading state', () => {
        it('shows loading indicator when loading=true', () => {
            const wrapper = mountComponent({ loading: true });
            expect(wrapper.text()).toContain('Loading changes...');
        });
    });

    describe('empty state', () => {
        it('shows "No changes detected" when no changed files', () => {
            const wrapper = mountComponent({
                files: [
                    { file: 'sys/config.g', status: 'unchanged', hunks: [] }
                ]
            });
            expect(wrapper.text()).toContain('No changes detected');
        });

        it('shows "No changes detected" with empty files array', () => {
            const wrapper = mountComponent({ files: [] });
            expect(wrapper.text()).toContain('No changes detected');
        });
    });

    describe('changed files', () => {
        const files = [
            { file: 'sys/config.g', status: 'modified', hunks: [] },
            { file: 'sys/homex.g', status: 'missing', hunks: [] },
            { file: 'sys/unchanged.g', status: 'unchanged', hunks: [] }
        ];

        it('filters out unchanged files', () => {
            const wrapper = mountComponent({ files });
            expect(wrapper.vm.changedFiles).toHaveLength(2);
        });

        it('shows file count summary', () => {
            const wrapper = mountComponent({ files });
            expect(wrapper.text()).toContain('2 files changed');
        });

        it('shows singular "file" for one change', () => {
            const wrapper = mountComponent({
                files: [{ file: 'sys/config.g', status: 'modified', hunks: [] }]
            });
            expect(wrapper.text()).toContain('1 file changed');
        });
    });

    describe('computed methods', () => {
        it('fileStatusColor returns correct colors', () => {
            const wrapper = mountComponent();
            expect(wrapper.vm.fileStatusColor('modified')).toBe('warning');
            expect(wrapper.vm.fileStatusColor('missing')).toBe('info');
            expect(wrapper.vm.fileStatusColor('extra')).toBe('grey');
            expect(wrapper.vm.fileStatusColor('unknown')).toBe('warning');
        });

        it('fileStatusIcon returns correct icons', () => {
            const wrapper = mountComponent();
            expect(wrapper.vm.fileStatusIcon('modified')).toBe('mdi-file-document-edit');
            expect(wrapper.vm.fileStatusIcon('missing')).toBe('mdi-file-plus');
            expect(wrapper.vm.fileStatusIcon('extra')).toBe('mdi-file-question');
        });

        it('lineClass returns correct CSS classes', () => {
            const wrapper = mountComponent();
            expect(wrapper.vm.lineClass('+added line')).toBe('diff-add');
            expect(wrapper.vm.lineClass('-removed line')).toBe('diff-remove');
            expect(wrapper.vm.lineClass(' context line')).toBe('diff-context');
            expect(wrapper.vm.lineClass('other')).toBe('diff-context');
        });
    });

    describe('hunk selection', () => {
        it('selectAllHunks sets all to selected', () => {
            const wrapper = mountComponent();
            const file = {
                hunks: [
                    { index: 0, selected: false },
                    { index: 1, selected: false }
                ]
            };
            wrapper.vm.selectAllHunks(file);
            expect(file.hunks[0].selected).toBe(true);
            expect(file.hunks[1].selected).toBe(true);
        });

        it('deselectAllHunks sets all to not selected', () => {
            const wrapper = mountComponent();
            const file = {
                hunks: [
                    { index: 0, selected: true },
                    { index: 1, selected: true }
                ]
            };
            wrapper.vm.deselectAllHunks(file);
            expect(file.hunks[0].selected).toBe(false);
            expect(file.hunks[1].selected).toBe(false);
        });

        it('selectedHunkCount counts selected hunks', () => {
            const wrapper = mountComponent();
            const file = {
                hunks: [
                    { index: 0, selected: true },
                    { index: 1, selected: false },
                    { index: 2, selected: true }
                ]
            };
            expect(wrapper.vm.selectedHunkCount(file)).toBe(2);
        });

        it('selectedHunkCount returns 0 when no hunks', () => {
            const wrapper = mountComponent();
            expect(wrapper.vm.selectedHunkCount({})).toBe(0);
        });

        it('emitApplyHunks emits correct indices', () => {
            const wrapper = mountComponent();
            const file = {
                file: 'sys/config.g',
                hunks: [
                    { index: 0, selected: true },
                    { index: 1, selected: false },
                    { index: 2, selected: true }
                ]
            };
            wrapper.vm.emitApplyHunks(file);
            expect(wrapper.emitted('apply-hunks')).toHaveLength(1);
            expect(wrapper.emitted('apply-hunks')[0]).toEqual([
                { file: 'sys/config.g', hunks: [0, 2] }
            ]);
        });
    });

    describe('apply-all event', () => {
        it('emits apply-all when button clicked', () => {
            const files = [{ file: 'sys/config.g', status: 'modified', hunks: [] }];
            const wrapper = mountComponent({ files });
            // Find the Apply All button
            const btns = wrapper.findAll('v-btn-stub');
            const applyAllBtn = btns.wrappers.find(w => w.text().includes('Apply All'));
            if (applyAllBtn) {
                applyAllBtn.vm.$emit('click');
                expect(wrapper.emitted('apply-all')).toBeTruthy();
            }
        });
    });
});
