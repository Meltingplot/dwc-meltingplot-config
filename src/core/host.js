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

/**
 * This plugin's custom data, as declared in the `data` section of plugin.json.
 *
 * @typedef {object} PluginData
 * @property {string} referenceRepoUrl Git URL of the reference config repo
 * @property {string} firmwareBranchOverride Branch to use instead of auto-detection
 * @property {string} detectedFirmwareVersion Firmware version read from the object model
 * @property {string} activeBranch Branch the reference repo is checked out at
 * @property {string} lastSyncTimestamp When the reference repo was last fetched
 * @property {string} status Sync status, see `core/status.js`
 */

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
 * @template T
 * @param {object|null} plugin Plugin object from the object model
 * @param {string} key Data key
 * @param {T} fallback Value to return when the key is absent or empty
 * @returns {T} The stored value, or `fallback`
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
 * Written out key by key rather than looped over a defaults map so the DWC 3.7
 * templates get a real type for it out of vue-tsc.
 *
 * @param {object} model Machine object model
 * @returns {PluginData} Every key, with the plugin.json default where unset
 */
export function readPluginData(model) {
  const plugin = pluginEntry(model)
  return {
    referenceRepoUrl: pluginDataValue(plugin, 'referenceRepoUrl', ''),
    firmwareBranchOverride: pluginDataValue(plugin, 'firmwareBranchOverride', ''),
    detectedFirmwareVersion: pluginDataValue(plugin, 'detectedFirmwareVersion', ''),
    activeBranch: pluginDataValue(plugin, 'activeBranch', ''),
    lastSyncTimestamp: pluginDataValue(plugin, 'lastSyncTimestamp', ''),
    status: pluginDataValue(plugin, 'status', 'not_configured')
  }
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
