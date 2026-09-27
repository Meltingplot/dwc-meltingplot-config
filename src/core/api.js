'use strict'

/**
 * Thin fetch wrappers around this plugin's DSF HTTP endpoints.
 *
 * Framework-neutral on purpose: the same module is bundled into the DWC 3.6
 * and the DWC 3.7 package.
 */

import { PLUGIN_ID } from './host'

/** Base path all endpoints of this plugin are registered under. */
export const API_BASE = `/machine/${PLUGIN_ID}`

/** Host whose session authenticates every request; see `setApiHost()`. */
let apiHost = null

/**
 * Authenticate every request with the session of the given host.
 *
 * DSF forwards requests to plugin endpoints whether or not they carry a
 * session, so the daemon rejects those without an `X-Session-Key` of its own.
 * The entry point calls this once when DWC loads the plugin.
 *
 * @param {import('./host').Host|null} host DWC host adapter
 */
export function setApiHost(host) {
  apiHost = host
}

/**
 * Fetch options with the current session key added.
 *
 * @param {RequestInit} [options] Options for `fetch`
 * @returns {RequestInit} The same options, plus `X-Session-Key` when there is a session
 */
function withSession(options = {}) {
  const key = apiHost ? apiHost.sessionKey() : null
  if (!key) {
    return options
  }
  return { ...options, headers: { ...options.headers, 'X-Session-Key': key } }
}

/**
 * Best-effort error text for a failed response.
 *
 * The daemon answers errors as `{"error": "..."}`; fall back to the raw body
 * and finally to the HTTP status text.
 *
 * @param {Response} response Failed fetch response
 * @returns {Promise<string>} Message to put into an Error
 */
export async function extractErrorMessage(response) {
  try {
    const text = await response.text()
    const data = JSON.parse(text)
    return data.error || text || response.statusText
  } catch {
    return response.statusText
  }
}

/**
 * GET a plugin endpoint and parse the JSON body.
 *
 * @param {string} path Path below `API_BASE`, e.g. `/status`
 * @returns {Promise<object>} Parsed response body
 */
export async function apiGet(path) {
  const response = await fetch(API_BASE + path, withSession())
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response))
  }
  return response.json()
}

/**
 * POST to a plugin endpoint and parse the JSON body.
 *
 * @param {string} path Path below `API_BASE`, e.g. `/apply`
 * @param {object|null} [body] JSON request body, or null for an empty POST
 * @returns {Promise<object>} Parsed response body
 */
export async function apiPost(path, body = null) {
  const options = { method: 'POST' }
  if (body !== null) {
    options.headers = { 'Content-Type': 'application/json' }
    options.body = JSON.stringify(body)
  }
  const response = await fetch(API_BASE + path, withSession(options))
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response))
  }
  return response.json()
}

/**
 * GET a plugin endpoint and return the raw body as a Blob.
 *
 * @param {string} path Path below `API_BASE`
 * @returns {Promise<Blob>} Response body
 */
export async function apiBlob(path) {
  const response = await fetch(API_BASE + path, withSession())
  if (!response.ok) {
    throw new Error(response.statusText)
  }
  return response.blob()
}

/**
 * Hand a Blob to the browser as a file download.
 *
 * @param {Blob} blob Payload
 * @param {string} filename Name to save it under
 */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/** Query-string helper so callers do not forget to encode. */
export function query(params) {
  return Object.entries(params)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join('&')
}
