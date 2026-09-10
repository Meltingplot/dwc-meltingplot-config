'use strict'

/**
 * The seam between the shared plugin logic and DuetWebControl.
 *
 * Everything in `src/core/` reaches DWC exclusively through a Host object.
 * DWC 3.6 (Vuex 3) and DWC 3.7 (Pinia) each provide their own adapter in
 * `src/ui36/host.js` / `src/ui37/host.ts`; no Vue or store types cross this
 * boundary.
 *
 * @typedef {object} Host
 * @property {() => object} model Live machine object model. Must read the
 *   reactive state on every call so computed properties track it.
 * @property {(id: string) => Promise<void>} startSbcPlugin Ask DSF to start
 *   the SBC part of a plugin.
 */

/** Identifier of this plugin as registered with DSF and DWC. */
export const PLUGIN_ID = 'MeltingplotConfig'

/** Shape of this plugin's custom data, with the defaults from plugin.json. */
const PLUGIN_DATA_DEFAULTS = {
  referenceRepoUrl: '',
  firmwareBranchOverride: '',
  detectedFirmwareVersion: '',
  activeBranch: '',
  lastSyncTimestamp: '',
  status: 'not_configured'
}

/**
 * Read this plugin's entry from the machine object model.
 *
 * `model.plugins` is a Map in both DWC generations; tests may hand in a plain
 * object instead.
 *
 * @param {object} model Machine object model
 * @returns {object|null} The Plugin object, or null if not present
 */
export function pluginEntry(model) {
  const plugins = model && model.plugins
  if (!plugins) {
    return null
  }
  const plugin = plugins instanceof Map ? plugins.get(PLUGIN_ID) : plugins[PLUGIN_ID]
  return plugin || null
}

/**
 * Read one key out of a Plugin's custom data.
 *
 * `plugin.data` is a Map on DWC 3.7 (`@duet3d/objectmodel`) and a plain object
 * on DWC 3.6, whose Vuex module keeps a JSON clone. This is the only place
 * that is allowed to index it — see the landmine list in the dual-build plan.
 *
 * @param {object|null} plugin Plugin object from the object model
 * @param {string} key Data key
 * @param {*} [fallback] Value to return when the key is absent or empty
 * @returns {*} The stored value, or `fallback`
 */
export function pluginDataValue(plugin, key, fallback) {
  const data = plugin && plugin.data
  if (!data) {
    return fallback
  }
  const value = data instanceof Map ? data.get(key) : data[key]
  return value === undefined || value === null || value === '' ? fallback : value
}

/**
 * This plugin's custom data, normalised to a plain object with all keys set.
 *
 * @param {object} model Machine object model
 * @returns {object} One property per key of `PLUGIN_DATA_DEFAULTS`
 */
export function readPluginData(model) {
  const plugin = pluginEntry(model)
  const result = {}
  for (const [key, fallback] of Object.entries(PLUGIN_DATA_DEFAULTS)) {
    result[key] = pluginDataValue(plugin, key, fallback)
  }
  return result
}

/**
 * Whether the SBC backend process is running.
 *
 * DSF reports the process ID in `Plugin.pid`: -1 while the plugin is stopped,
 * 0 while it is shutting down, and the real PID while it runs.
 *
 * @param {object} model Machine object model
 * @returns {boolean|null} true/false, or null when the state is not yet known
 */
export function isBackendRunning(model) {
  const plugin = pluginEntry(model)
  if (!plugin || typeof plugin.pid !== 'number') {
    return null
  }
  return plugin.pid > 0
}
