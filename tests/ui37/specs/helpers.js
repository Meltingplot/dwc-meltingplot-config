/**
 * Shared helpers for the DWC 3.7 component specs.
 */
import { mount } from "@vue/test-utils";
import { createVuetify } from "vuetify";
import * as components from "vuetify/components";
import * as directives from "vuetify/directives";
import { vi } from "vitest";

/**
 * Mount a component with a real Vuetify instance.
 *
 * DWC registers every Vuetify component globally before an external plugin
 * loads, so the templates resolve `<v-foo>` by name — the same here.
 *
 * @param {object} component Component to mount
 * @param {object} [options] Extra mount options
 * @returns {object} The wrapper
 */
export function mountWithVuetify(component, options = {}) {
  const vuetify = createVuetify({ components, directives });
  return mount(component, {
    ...options,
    global: {
      plugins: [vuetify],
      ...(options.global ?? {}),
      stubs: { transition: false, ...(options.global?.stubs ?? {}) },
    },
    attachTo: document.body,
  });
}

/**
 * A `fetch` stub that answers by URL substring.
 *
 * @param {object} routes Map of URL fragment to response body (or a function)
 * @returns {Function} The stub, also installed as `global.fetch`
 */
export function mockFetch(routes = {}) {
  const stub = vi.fn((url, opts) => {
    for (const [fragment, handler] of Object.entries(routes)) {
      if (String(url).includes(fragment)) {
        const body = typeof handler === "function" ? handler(url, opts) : handler;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(body),
          text: () => Promise.resolve(JSON.stringify(body)),
        });
      }
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      statusText: "Not Found",
      text: () => Promise.resolve('{"error":"Not Found"}'),
    });
  });
  globalThis.fetch = stub;
  return stub;
}

/** Let pending promises and the reactivity queue settle. */
export async function flush(wrapper) {
  await new Promise((resolve) => setTimeout(resolve, 0));
  if (wrapper) {
    await wrapper.vm.$nextTick();
  }
}
