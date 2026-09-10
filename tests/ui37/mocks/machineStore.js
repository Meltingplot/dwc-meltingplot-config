/**
 * Stand-in for DWC 3.7's Pinia machine store.
 *
 * `plugin.data` is a Map here, exactly as `@duet3d/objectmodel` reports it on
 * 3.7 — which is the difference `pluginDataValue()` exists to absorb.
 */
import { reactive } from "vue";
import { vi } from "vitest";

export const PLUGIN_ID = "MeltingplotConfig";

const store = reactive({
  model: { plugins: new Map() },
  startSbcPlugin: vi.fn().mockResolvedValue(undefined),
});

export function useMachineStore() {
  return store;
}

/**
 * Put this plugin into the object model.
 *
 * @param {object} [options] `pid` and `data` (a plain object, stored as a Map)
 */
export function setPlugin({ pid, data } = {}) {
  const plugin = {};
  if (pid !== undefined) {
    plugin.pid = pid;
  }
  plugin.data = new Map(Object.entries(data ?? {}));
  store.model.plugins.set(PLUGIN_ID, plugin);
}

/** Reset the store between test cases. */
export function resetMachineStore() {
  store.model = { plugins: new Map() };
  store.startSbcPlugin = vi.fn().mockResolvedValue(undefined);
}
