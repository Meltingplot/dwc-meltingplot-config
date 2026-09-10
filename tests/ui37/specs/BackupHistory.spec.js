import { reactive } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import { normalizeBackup } from "../../../src/core/useBackupHistory.js";
import BackupHistory from "../../../src/ui37/components/BackupHistory.vue";
import { flush, mockFetch, mountWithVuetify } from "./helpers.js";

let wrapper;

afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  delete globalThis.fetch;
});

/** Reactive, normalised entries — the shape the parent's ref holds. */
function reactiveBackups(backups) {
  return reactive(backups.map(normalizeBackup));
}

function mountHistory(backups, extra = {}) {
  wrapper = mountWithVuetify(BackupHistory, {
    props: { backups: reactiveBackups(backups), ...extra },
  });
  return wrapper;
}

describe("ui37 BackupHistory", () => {
  it("shows the empty state", () => {
    mountHistory([]);
    expect(wrapper.text()).toContain("No backups yet");
  });

  it("shows a spinner while loading", () => {
    wrapper = mountWithVuetify(BackupHistory, { props: { backups: [], loading: true } });
    expect(wrapper.text()).toContain("Loading backups...");
  });

  it("renders a backup row with its short hash", () => {
    mountHistory([
      { hash: "abcdef1234567890", message: "Apply config", timestamp: "2026-09-10", filesChanged: 3 },
    ]);
    const text = wrapper.text();
    expect(text).toContain("Apply config");
    expect(text).toContain("2026-09-10");
    expect(text).toContain("3 files");
    expect(text).toContain("abcdef12");
  });

  it("emits restore, download and delete with the hash", async () => {
    mountHistory([{ hash: "abcdef1234567890", message: "Apply config" }]);

    const byTitle = (title) =>
      wrapper.findAll("button").find((b) => b.attributes("title") === title);

    await byTitle("Download backup").trigger("click");
    await byTitle("Restore this backup").trigger("click");
    await byTitle("Delete backup").trigger("click");

    expect(wrapper.emitted("download")[0]).toEqual(["abcdef1234567890"]);
    expect(wrapper.emitted("restore")[0]).toEqual(["abcdef1234567890"]);
    expect(wrapper.emitted("delete")[0]).toEqual(["abcdef1234567890"]);
  });

  it("fetches the file list when a row is expanded", async () => {
    const fetchStub = mockFetch({
      "/backup?hash=": { changedFiles: ["sys/config.g"], files: ["sys/config.g", "sys/homeall.g"] },
    });
    const backups = reactiveBackups([{ hash: "abcdef1234567890", message: "Apply config" }]);
    wrapper = mountWithVuetify(BackupHistory, { props: { backups } });

    await wrapper.find(".v-list-item").trigger("click");
    await flush(wrapper);

    expect(fetchStub).toHaveBeenCalledWith(
      "/machine/MeltingplotConfig/backup?hash=abcdef1234567890"
    );
    expect(backups[0].expanded).toBe(true);
    expect(backups[0].changedFiles).toEqual(["sys/config.g"]);
    expect(wrapper.text()).toContain("Changed Files");
  });

  it("collapses again on a second click without refetching", async () => {
    const fetchStub = mockFetch({ "/backup?hash=": { changedFiles: [], files: [] } });
    const backups = reactiveBackups([{ hash: "abcdef1234567890", message: "Apply config" }]);
    wrapper = mountWithVuetify(BackupHistory, { props: { backups } });

    await wrapper.find(".v-list-item").trigger("click");
    await flush(wrapper);
    await wrapper.find(".v-list-item").trigger("click");
    await flush(wrapper);

    expect(backups[0].expanded).toBe(false);
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });

  it("creates a manual backup and asks the parent to refresh", async () => {
    const fetchStub = mockFetch({ "/manualBackup": { backup: { hash: "abc" } } });
    mountHistory([]);

    const button = wrapper.findAll("button").find((b) => b.text().includes("Create Backup"));
    await button.trigger("click");
    await flush(wrapper);

    expect(fetchStub).toHaveBeenCalledWith(
      "/machine/MeltingplotConfig/manualBackup",
      { method: "POST" }
    );
    expect(wrapper.emitted("refresh")).toBeTruthy();
    expect(wrapper.emitted("notify")[0][0].color).toBe("success");
  });

  it("reports a failed manual backup", async () => {
    mockFetch({});
    mountHistory([]);

    const button = wrapper.findAll("button").find((b) => b.text().includes("Create Backup"));
    await button.trigger("click");
    await flush(wrapper);

    expect(wrapper.emitted("notify")[0][0].color).toBe("error");
    expect(wrapper.emitted("refresh")).toBeFalsy();
  });
});
