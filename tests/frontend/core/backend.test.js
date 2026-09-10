import {
    PLUGIN_ID,
    isBackendRunning,
    startBackend,
    ensureBackendRunning
} from '../../../src/core/backend'
import { createHost } from '../../../src/ui36/host'

function modelWithMap(plugin) {
    const plugins = new Map()
    if (plugin) {
        plugins.set(PLUGIN_ID, plugin)
    }
    return { plugins }
}

/** A Host built straight from a model, without going through Vuex. */
function hostFor(model, startSbcPlugin) {
    return {
        model: () => model,
        startSbcPlugin: startSbcPlugin || jest.fn().mockResolvedValue(undefined)
    }
}

describe('core/backend', () => {
    describe('startBackend', () => {
        it('asks the host to start this plugin', async () => {
            const startSbcPlugin = jest.fn().mockResolvedValue(undefined)
            await startBackend(hostFor(null, startSbcPlugin))
            expect(startSbcPlugin).toHaveBeenCalledWith(PLUGIN_ID)
        })

        it('resolves even when the host returns a non-promise', async () => {
            const startSbcPlugin = jest.fn().mockReturnValue(undefined)
            await expect(startBackend(hostFor(null, startSbcPlugin))).resolves.toBeUndefined()
        })
    })

    describe('ensureBackendRunning', () => {
        it('starts the backend when the model reports it as stopped', async () => {
            const startSbcPlugin = jest.fn().mockResolvedValue(undefined)
            const host = hostFor(modelWithMap({ pid: -1 }), startSbcPlugin)
            await expect(ensureBackendRunning(host)).resolves.toBe(true)
            expect(startSbcPlugin).toHaveBeenCalledWith(PLUGIN_ID)
        })

        it('does nothing when the backend is already running', async () => {
            const startSbcPlugin = jest.fn()
            const host = hostFor(modelWithMap({ pid: 4711 }), startSbcPlugin)
            await expect(ensureBackendRunning(host)).resolves.toBe(false)
            expect(startSbcPlugin).not.toHaveBeenCalled()
        })

        it('bails out immediately without an object model', async () => {
            const startSbcPlugin = jest.fn()
            await expect(ensureBackendRunning(hostFor(null, startSbcPlugin))).resolves.toBe(false)
            expect(startSbcPlugin).not.toHaveBeenCalled()
        })

        it('bails out immediately without a host', async () => {
            await expect(ensureBackendRunning(undefined)).resolves.toBe(false)
        })

        it('bails out when the host throws while reading the model', async () => {
            const host = {
                model: () => { throw new Error('no connection') },
                startSbcPlugin: jest.fn()
            }
            await expect(ensureBackendRunning(host)).resolves.toBe(false)
            expect(host.startSbcPlugin).not.toHaveBeenCalled()
        })

        it('waits for the object model to report a PID', async () => {
            const model = modelWithMap(null)
            const startSbcPlugin = jest.fn().mockResolvedValue(undefined)
            const host = hostFor(model, startSbcPlugin)

            const promise = ensureBackendRunning(host, { interval: 1, maxAttempts: 20 })
            // Plugin entry shows up a little later, as it does on a fresh connection
            setTimeout(() => model.plugins.set(PLUGIN_ID, { pid: -1 }), 5)

            await expect(promise).resolves.toBe(true)
            expect(startSbcPlugin).toHaveBeenCalledWith(PLUGIN_ID)
        })

        it('gives up after maxAttempts when the PID never appears', async () => {
            const startSbcPlugin = jest.fn()
            const host = hostFor(modelWithMap(null), startSbcPlugin)
            await expect(
                ensureBackendRunning(host, { interval: 1, maxAttempts: 3 })
            ).resolves.toBe(false)
            expect(startSbcPlugin).not.toHaveBeenCalled()
        })

        it('resolves false when starting the backend fails', async () => {
            const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
            const startSbcPlugin = jest.fn().mockRejectedValue(new Error('denied'))
            const host = hostFor(modelWithMap({ pid: -1 }), startSbcPlugin)
            await expect(ensureBackendRunning(host)).resolves.toBe(false)
            expect(warn).toHaveBeenCalled()
            warn.mockRestore()
        })
    })
})

describe('ui36 Vuex host adapter', () => {
    it('reads the model out of the machine module', () => {
        const model = modelWithMap({ pid: 1 })
        const host = createHost({ state: { machine: { model } } })
        expect(host.model()).toBe(model)
    })

    it('returns null when there is no machine module', () => {
        expect(createHost({ state: {} }).model()).toBeNull()
        expect(createHost(undefined).model()).toBeNull()
    })

    it('dispatches machine/startSbcPlugin', async () => {
        const dispatch = jest.fn().mockResolvedValue(undefined)
        await createHost({ state: {}, dispatch }).startSbcPlugin(PLUGIN_ID)
        expect(dispatch).toHaveBeenCalledWith('machine/startSbcPlugin', PLUGIN_ID)
    })

    it('drives ensureBackendRunning end to end', async () => {
        const dispatch = jest.fn().mockResolvedValue(undefined)
        const store = { state: { machine: { model: modelWithMap({ pid: -1 }) } }, dispatch }
        await expect(ensureBackendRunning(createHost(store))).resolves.toBe(true)
        expect(dispatch).toHaveBeenCalledWith('machine/startSbcPlugin', PLUGIN_ID)
    })
})
