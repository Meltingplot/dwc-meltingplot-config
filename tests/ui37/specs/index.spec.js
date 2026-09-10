import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const PLUGIN_ID = "MeltingplotConfig";
const ROUTE_PATH = "/MeltingplotConfig";

/**
 * Load the entry point with a fresh module registry.
 *
 * `vi.resetModules()` also resets the mock modules, so the spies have to be
 * re-imported afterwards — a spy grabbed at the top of the file would be a
 * different instance from the one the entry point ends up calling.
 *
 * @param {object} [plugin] Plugin entry to seed the object model with
 * @returns {Promise<object>} The fresh mock modules
 */
async function loadEntry(plugin = { pid: 4711 }) {
  vi.resetModules();
  const plugins = await import("../mocks/plugins.js");
  const events = await import("../mocks/events.js");
  const machineStore = await import("../mocks/machineStore.js");

  machineStore.resetMachineStore();
  machineStore.setPlugin(plugin);

  await import("../../../src/ui37/index.ts");

  return { ...plugins, Events: events.default, ...machineStore };
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  delete globalThis.fetch;
});

describe("ui37 entry point", () => {
  it("registers the route under Plugins with the shared path", async () => {
    const { registerRoute } = await loadEntry();

    expect(registerRoute).toHaveBeenCalledTimes(1);
    const [component, route] = registerRoute.mock.calls[0];
    expect(component).toBeDefined();

    const entry = route.Plugins.MeltingplotConfig;
    // Identical to the DWC 3.6 route so bookmarks and docs stay valid
    expect(entry.path).toBe(ROUTE_PATH);
    expect(entry.icon).toMatch(/^mdi-/);
    expect(entry.caption).toBe("Meltingplot Config");
    // Captions are literals, not i18n keys — the same in both generations
    expect(entry.translated).toBe(true);
  });

  it("starts the SBC backend when the object model reports it stopped", async () => {
    const { useMachineStore } = await loadEntry({ pid: -1 });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(useMachineStore().startSbcPlugin).toHaveBeenCalledWith(PLUGIN_ID);
  });

  it("leaves a running backend alone", async () => {
    const { useMachineStore } = await loadEntry({ pid: 4711 });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(useMachineStore().startSbcPlugin).not.toHaveBeenCalled();
  });

  it("unregisters the route when DWC unloads this plugin", async () => {
    const { Events, unregisterRoute } = await loadEntry();

    Events.emit("dwcPluginUnloaded", PLUGIN_ID);

    expect(unregisterRoute).toHaveBeenCalledWith(ROUTE_PATH);
    // The listener removes itself, so a reload cannot stack handlers
    expect(Events.handlerCount("dwcPluginUnloaded")).toBe(0);
  });

  it("ignores the unload of another plugin", async () => {
    const { Events, unregisterRoute } = await loadEntry();

    Events.emit("dwcPluginUnloaded", "SomeOtherPlugin");

    expect(unregisterRoute).not.toHaveBeenCalled();
    expect(Events.handlerCount("dwcPluginUnloaded")).toBe(1);
  });
});
