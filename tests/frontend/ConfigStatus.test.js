import { shallowMount } from '@vue/test-utils';
import ConfigStatus from '../../src/components/ConfigStatus.vue';

function mountComponent(propsData = {}) {
    return shallowMount(ConfigStatus, {
        vuetify: global.createVuetify(),
        propsData
    });
}

describe('ConfigStatus', () => {
    describe('default state', () => {
        it('shows "Not detected" when no firmware version', () => {
            const wrapper = mountComponent();
            expect(wrapper.text()).toContain('Not detected');
        });

        it('shows "None" when no active branch', () => {
            const wrapper = mountComponent();
            expect(wrapper.text()).toContain('None');
        });

        it('shows "Not configured" when no repo URL', () => {
            const wrapper = mountComponent();
            expect(wrapper.text()).toContain('Not configured');
        });

        it('shows "Never" when no last sync', () => {
            const wrapper = mountComponent();
            expect(wrapper.text()).toContain('Never');
        });

        it('shows "Not Configured" status label', () => {
            const wrapper = mountComponent();
            expect(wrapper.text()).toContain('Not Configured');
        });
    });

    describe('with data', () => {
        const props = {
            firmwareVersion: '3.5.1',
            activeBranch: '3.5',
            repoUrl: 'https://example.com/config.git',
            lastSync: '2026-02-15T10:00:00',
            status: 'up_to_date'
        };

        it('shows firmware version', () => {
            const wrapper = mountComponent(props);
            expect(wrapper.text()).toContain('3.5.1');
        });

        it('shows active branch', () => {
            const wrapper = mountComponent(props);
            expect(wrapper.text()).toContain('3.5');
        });

        it('shows repo URL', () => {
            const wrapper = mountComponent(props);
            expect(wrapper.text()).toContain('https://example.com/config.git');
        });

        it('shows "Up to Date" status', () => {
            const wrapper = mountComponent(props);
            expect(wrapper.text()).toContain('Up to Date');
        });
    });

    describe('status mapping', () => {
        it('maps "updates_available" to warning color', () => {
            const wrapper = mountComponent({ status: 'updates_available' });
            expect(wrapper.vm.statusColor).toBe('warning');
            expect(wrapper.vm.statusLabel).toBe('Updates Available');
        });

        it('maps "error" to error color', () => {
            const wrapper = mountComponent({ status: 'error' });
            expect(wrapper.vm.statusColor).toBe('error');
            expect(wrapper.vm.statusLabel).toBe('Error');
        });

        it('falls back to not_configured for unknown status', () => {
            const wrapper = mountComponent({ status: 'garbage' });
            expect(wrapper.vm.statusColor).toBe('grey');
            expect(wrapper.vm.statusLabel).toBe('Not Configured');
        });
    });

    describe('check updates button', () => {
        it('is disabled when no repoUrl', () => {
            const wrapper = mountComponent({ repoUrl: '' });
            const btn = wrapper.find('v-btn-stub[color="primary"]');
            expect(btn.attributes('disabled')).toBe('true');
        });

        it('is enabled when repoUrl is set', () => {
            const wrapper = mountComponent({ repoUrl: 'https://example.com' });
            const btn = wrapper.find('v-btn-stub[color="primary"]');
            expect(btn.attributes('disabled')).toBeUndefined();
        });

        it('emits check-updates on click', async () => {
            const wrapper = mountComponent({ repoUrl: 'https://example.com' });
            const btn = wrapper.find('v-btn-stub[color="primary"]');
            await btn.vm.$emit('click');
            expect(wrapper.emitted('check-updates')).toBeTruthy();
        });
    });

    describe('settings hint', () => {
        it('shows hint when no repoUrl', () => {
            const wrapper = mountComponent({ repoUrl: '' });
            expect(wrapper.text()).toContain('Configure a repository URL');
        });

        it('hides hint when repoUrl is set', () => {
            const wrapper = mountComponent({ repoUrl: 'https://example.com' });
            expect(wrapper.text()).not.toContain('Configure a repository URL');
        });
    });
});
