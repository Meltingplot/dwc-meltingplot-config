'use strict'

/**
 * DWC 3.6 host adapter — the Vuex 3 side of the seam described in
 * `src/core/host.js`. No Vue or Vuex types leak past this module.
 */

/**
 * Wrap a DWC root store in a Host.
 *
 * @param {object} store Root Vuex store
 * @returns {import('../core/host').Host} Adapter for the shared core
 */
export function createHost(store) {
  return {
    model() {
      const machine = store && store.state && store.state.machine
      return (machine && machine.model) || null
    },
    startSbcPlugin(id) {
      return Promise.resolve(store.dispatch('machine/startSbcPlugin', id))
    },
    sessionKey() {
      // RestConnector keeps the key from /machine/connect in a field its
      // typings mark private; there is no public accessor for it.
      const connector = store && store.getters && store.getters['machine/connector']
      return (connector && connector.sessionKey) || null
    }
  }
}
