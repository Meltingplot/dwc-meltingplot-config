import {
    PLUGIN_ID,
    pluginEntry,
    pluginDataValue,
    readPluginData,
    isBackendRunning
} from '../../../src/core/host'

function modelWithMap(plugin) {
    const plugins = new Map()
    if (plugin) {
        plugins.set(PLUGIN_ID, plugin)
    }
    return { plugins }
}

describe('core/host', () => {
    describe('pluginEntry', () => {
        it('reads the plugin from a Map', () => {
            const plugin = { id: PLUGIN_ID, pid: 1234 }
            expect(pluginEntry(modelWithMap(plugin))).toBe(plugin)
        })

        it('reads the plugin from a plain object (test stores)', () => {
            const plugin = { id: PLUGIN_ID, pid: 1234 }
            expect(pluginEntry({ plugins: { [PLUGIN_ID]: plugin } })).toBe(plugin)
        })

        it('returns null when the plugin is absent', () => {
            expect(pluginEntry(modelWithMap(null))).toBeNull()
        })

        it('returns null when there is no model at all', () => {
            expect(pluginEntry(undefined)).toBeNull()
            expect(pluginEntry({})).toBeNull()
        })
    })

    describe('pluginDataValue', () => {
        it('reads plugin.data as a plain object (DWC 3.6)', () => {
            const plugin = { data: { activeBranch: '3.6' } }
            expect(pluginDataValue(plugin, 'activeBranch', '')).toBe('3.6')
        })

        it('reads plugin.data as a Map (DWC 3.7)', () => {
            const plugin = { data: new Map([['activeBranch', '3.7']]) }
            expect(pluginDataValue(plugin, 'activeBranch', '')).toBe('3.7')
        })

        it('falls back for missing, null and empty values', () => {
            expect(pluginDataValue({ data: {} }, 'activeBranch', 'fb')).toBe('fb')
            expect(pluginDataValue({ data: { activeBranch: null } }, 'activeBranch', 'fb')).toBe('fb')
            expect(pluginDataValue({ data: { activeBranch: '' } }, 'activeBranch', 'fb')).toBe('fb')
        })

        it('falls back when there is no plugin or no data', () => {
            expect(pluginDataValue(null, 'activeBranch', 'fb')).toBe('fb')
            expect(pluginDataValue({}, 'activeBranch', 'fb')).toBe('fb')
        })
    })

    describe('readPluginData', () => {
        it('fills every key with the manifest defaults', () => {
            expect(readPluginData({ plugins: new Map() })).toEqual({
                referenceRepoUrl: '',
                firmwareBranchOverride: '',
                detectedFirmwareVersion: '',
                activeBranch: '',
                lastSyncTimestamp: '',
                status: 'not_configured'
            })
        })

        it('reads through a Map-backed plugin.data', () => {
            const plugin = { data: new Map([['status', 'up_to_date'], ['activeBranch', '3.7']]) }
            const data = readPluginData(modelWithMap(plugin))
            expect(data.status).toBe('up_to_date')
            expect(data.activeBranch).toBe('3.7')
            expect(data.referenceRepoUrl).toBe('')
        })
    })

    describe('isBackendRunning', () => {
        it('is true for a positive PID', () => {
            expect(isBackendRunning(modelWithMap({ pid: 4711 }))).toBe(true)
        })

        it('is false for pid -1 (stopped, e.g. right after an upgrade)', () => {
            expect(isBackendRunning(modelWithMap({ pid: -1 }))).toBe(false)
        })

        it('is false for pid 0 (shutting down)', () => {
            expect(isBackendRunning(modelWithMap({ pid: 0 }))).toBe(false)
        })

        it('is null when the plugin entry is missing', () => {
            expect(isBackendRunning(modelWithMap(null))).toBeNull()
        })

        it('is null when the PID is not a number yet', () => {
            expect(isBackendRunning(modelWithMap({}))).toBeNull()
        })
    })
})
