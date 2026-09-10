import { afterEach, beforeEach, describe, expect, it } from "vitest";

import MeltingplotConfig from "../../../src/ui37/MeltingplotConfig.vue";
import { PLUGIN_ID, resetMachineStore, setPlugin, useMachineStore } from "../mocks/machineStore.js";
import { flush, mockFetch, mountWithVuetify } from "./helpers.js";

let wrapper;

beforeEach(() => {
  resetMachineStore();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  delete globalThis.fetch;
});

describe("ui37 MeltingplotConfig", () => {
  it("reads plugin.data out of the Map DWC 3.7 hands it", async () => {
    setPlugin({
      pid: 4711,
      data: {
        detectedFirmwareVersion: "3.7.0",
        activeBranch: "3.7",
        referenceRepoUrl: "https://example.com/repo.git",
        status: "up_to_date",
      },
    });
    mockFetch({ "/status": { branches: ["3.7"] }, "/diff": { files: [] } });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    const text = wrapper.text();
    expect(text).toContain("3.7.0");
    expect(text).toContain("https://example.com/repo.git");
    expect(text).toContain("Up to Date");
  });

  it("loads the status endpoint on mount", async () => {
    setPlugin({ pid: 4711 });
    const fetchStub = mockFetch({ "/status": { branches: [] } });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    expect(fetchStub).toHaveBeenCalledWith("/machine/MeltingplotConfig/status");
  });

  it("shows the backend banner only while the daemon is stopped", async () => {
    setPlugin({ pid: -1 });
    mockFetch({ "/status": { branches: [] } });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    expect(wrapper.text()).toContain("Backend is not running");
  });

  it("hides the banner while the daemon runs", async () => {
    setPlugin({ pid: 4711 });
    mockFetch({ "/status": { branches: [] } });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    expect(wrapper.text()).not.toContain("Backend is not running");
  });

  it("starts the backend through the Pinia adapter", async () => {
    setPlugin({ pid: -1 });
    mockFetch({ "/status": { branches: [] } });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    const button = wrapper.findAll("button").find((b) => b.text().includes("Start Backend"));
    await button.trigger("click");
    await flush(wrapper);

    expect(useMachineStore().startSbcPlugin).toHaveBeenCalledWith(PLUGIN_ID);
  });

  it("syncs and reloads the diff from the Status tab", async () => {
    setPlugin({ pid: 4711, data: { referenceRepoUrl: "https://example.com/repo.git" } });
    const fetchStub = mockFetch({
      "/status": { branches: ["3.7"], referenceRepoUrl: "https://example.com/repo.git" },
      "/sync": { ok: true },
      "/diff": { files: [{ file: "sys/config.g", status: "modified" }] },
      "/branches": { branches: ["3.7"] },
    });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    const button = wrapper.findAll("button").find((b) => b.text().includes("Check for Updates"));
    await button.trigger("click");
    await flush(wrapper);

    const posted = fetchStub.mock.calls.filter(([url]) => url.includes("/sync"));
    expect(posted).toHaveLength(1);
    expect(posted[0][1]).toEqual({ method: "POST" });
    // The diff is reloaded and the branch list refreshed in the same pass
    expect(fetchStub.mock.calls.some(([url]) => url.includes("/branches"))).toBe(true);
    // The snackbar is teleported into the overlay container, not the wrapper
    expect(document.body.textContent).toContain("Sync complete");
  });

  it("seeds the settings form from plugin.data", async () => {
    setPlugin({
      pid: 4711,
      data: {
        referenceRepoUrl: "https://example.com/repo.git",
        firmwareBranchOverride: "custom",
      },
    });
    mockFetch({ "/status": { branches: [] } });

    wrapper = mountWithVuetify(MeltingplotConfig);
    await flush(wrapper);

    // v-tabs-window renders only the active tab, so open Settings first
    const settingsTab = wrapper.findAll(".v-tab").find((tab) => tab.text().includes("Settings"));
    await settingsTab.trigger("click");
    await flush(wrapper);

    const values = wrapper.findAll("input").map((input) => input.element.value);
    expect(values).toContain("https://example.com/repo.git");
    expect(values).toContain("custom");
  });
});
