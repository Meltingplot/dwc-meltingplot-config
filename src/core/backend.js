'use strict'

/**
 * Helpers for keeping the SBC backend (the Python daemon) running.
 *
 * Background: when a plugin is upgraded, DSF runs UninstallPlugin with the
 * ForUpgrade flag, which stops the running SBC process and drops the plugin
 * from the auto-start list. InstallPlugin then re-registers the plugin with
 * Pid = -1 but never starts it again — DWC only issues StartPlugin when the
 * ZIP was uploaded via "Upload & Start", which is not the case for the
 * "Install Plugin" button on Settings -> Plugins.
 *
 * The result is a plugin whose DWC resources are loaded while its backend is
 * dead — exactly what DWC labels "partially started", and why every HTTP
 * endpoint of this plugin returns 404 until the backend is started manually.
 */

import { PLUGIN_ID, isBackendRunning } from './host'

export { PLUGIN_ID, isBackendRunning }

/** Default delay between attempts while waiting for the object model. */
const DEFAULT_INTERVAL = 1500

/** Default number of attempts before giving up on the object model. */
const DEFAULT_MAX_ATTEMPTS = 20

/**
 * Ask DSF to start the SBC part of this plugin.
 *
 * DSF persists the new execution state, so the backend also comes back up
 * automatically after the next SBC reboot.
 *
 * @param {import('./host').Host} host DWC host adapter
 * @returns {Promise<void>} Resolves once DSF accepted the command
 */
export function startBackend(host) {
  return Promise.resolve(host.startSbcPlugin(PLUGIN_ID))
}

/**
 * Start the SBC backend if the object model reports it as stopped.
 *
 * The object model may not be populated at the time DWC loads plugin
 * resources, so this polls until the plugin entry shows up. It gives up
 * immediately when there is no object model at all (e.g. in unit tests).
 *
 * @param {import('./host').Host} host DWC host adapter
 * @param {object} [options] Polling options
 * @param {number} [options.interval] Delay between attempts in ms
 * @param {number} [options.maxAttempts] Attempts before giving up
 * @returns {Promise<boolean>} Whether a start was issued
 */
export function ensureBackendRunning(host, options = {}) {
  const interval = options.interval || DEFAULT_INTERVAL
  const maxAttempts = options.maxAttempts || DEFAULT_MAX_ATTEMPTS

  let initialModel = null
  try {
    initialModel = host && host.model()
  } catch {
    initialModel = null
  }
  if (!initialModel) {
    // No object model — nothing to inspect and nothing to start
    return Promise.resolve(false)
  }

  return new Promise(resolve => {
    let attempts = 0

    const check = () => {
      attempts++

      let running = null
      try {
        running = isBackendRunning(host.model())
      } catch {
        running = null
      }

      if (running === true) {
        resolve(false)
        return
      }

      if (running === false) {
        startBackend(host).then(
          () => resolve(true),
          err => {
            // eslint-disable-next-line no-console
            console.warn(`[${PLUGIN_ID}] failed to start the SBC backend:`, err)
            resolve(false)
          }
        )
        return
      }

      if (attempts >= maxAttempts) {
        resolve(false)
        return
      }
      setTimeout(check, interval)
    }

    check()
  })
}
