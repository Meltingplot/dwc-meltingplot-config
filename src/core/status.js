'use strict'

/**
 * Presentation of the daemon's sync status.
 *
 * Shared by both DWC generations so the status chip cannot drift between them.
 */

/** Chip colour, icon and label per status reported by `GET /status`. */
export const SYNC_STATUS = {
  not_configured: { color: 'grey', icon: 'mdi-help-circle', label: 'Not Configured' },
  up_to_date: { color: 'success', icon: 'mdi-check-circle', label: 'Up to Date' },
  updates_available: { color: 'warning', icon: 'mdi-alert-circle', label: 'Updates Available' },
  sync_error: { color: 'error', icon: 'mdi-wifi-off', label: 'Sync Failed' },
  error: { color: 'error', icon: 'mdi-alert', label: 'Error' }
}

/**
 * Look up how a status should be rendered, falling back to "not configured".
 *
 * @param {string} status Status string from the daemon
 * @returns {{color: string, icon: string, label: string}} Chip presentation
 */
export function syncStatusInfo(status) {
  return SYNC_STATUS[status] || SYNC_STATUS.not_configured
}
