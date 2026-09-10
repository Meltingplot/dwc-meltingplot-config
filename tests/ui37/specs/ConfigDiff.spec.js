import { reactive } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import { normalizeFile } from "../../../src/core/diff.js";
import ConfigDiff from "../../../src/ui37/components/ConfigDiff.vue";
import { flush, mockFetch, mountWithVuetify } from "./helpers.js";

let wrapper;

afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  delete globalThis.fetch;
});

const detailHunks = (count, selected = true) =>
  Array.from({ length: count }, (_, i) => ({
    index: i,
    header: `@@ -${i + 1},1 +${i + 1},1 @@`,
    lines: [`-old${i}`, `+new${i}`],
    selected,
  }));

/**
 * Vue 3 does not deep-observe props, so a plain array handed in would not be
 * tracked. The parent holds the diff in a ref, so the specs use reactive state
 * for the same reason.
 *
 * @param {Array<object>} files Raw file entries
 * @returns {Array<object>} The reactive, normalised list the component is given
 */
function reactiveFiles(files) {
  return reactive(files.map(normalizeFile));
}

function mountDiff(files) {
  wrapper = mountWithVuetify(ConfigDiff, { props: { files: reactiveFiles(files) } });
  return wrapper;
}

describe("ui37 ConfigDiff", () => {
  it("shows the empty state when nothing changed", () => {
    mountDiff([{ file: "sys/config.g", status: "unchanged" }]);
    expect(wrapper.text()).toContain("No changes detected");
  });

  it("shows a spinner while loading", () => {
    wrapper = mountWithVuetify(ConfigDiff, { props: { files: [], loading: true } });
    expect(wrapper.text()).toContain("Loading changes...");
  });

  it("lists changed files and labels the button Apply All", () => {
    mountDiff([
      { file: "sys/config.g", status: "modified" },
      { file: "sys/homeall.g", status: "missing" },
    ]);
    expect(wrapper.text()).toContain("2 files changed");
    expect(wrapper.text()).toContain("Apply All");
  });

  it("emits apply-all when nothing is deselected", async () => {
    mountDiff([{ file: "sys/config.g", status: "modified" }]);
    const button = wrapper.findAll("button").find((b) => b.text().includes("Apply All"));
    await button.trigger("click");
    expect(wrapper.emitted("apply-all")).toHaveLength(1);
    expect(wrapper.emitted("apply-selection")).toBeFalsy();
  });

  it("switches to Partially Apply once a file is unchecked", async () => {
    const files = reactiveFiles([
      { file: "sys/config.g", status: "modified" },
      { file: "sys/homeall.g", status: "modified" },
    ]);
    wrapper = mountWithVuetify(ConfigDiff, { props: { files } });

    const checkbox = wrapper.find('input[type="checkbox"]');
    await checkbox.setValue(false);
    await flush(wrapper);

    expect(wrapper.text()).toContain("Partially Apply");
    expect(wrapper.text()).toContain("1 excluded");

    const button = wrapper.findAll("button").find((b) => b.text().includes("Partially Apply"));
    await button.trigger("click");

    expect(wrapper.emitted("apply-all")).toBeFalsy();
    expect(wrapper.emitted("apply-selection")[0][0]).toEqual({
      files: [{ file: "sys/homeall.g" }],
      excludedFiles: 1,
      partialFiles: 0,
    });
  });

  it("sends only the selected hunk indices of a partly selected file", async () => {
    const files = reactiveFiles([
      { file: "sys/config.g", status: "modified", hunks: detailHunks(3) },
    ]);
    wrapper = mountWithVuetify(ConfigDiff, { props: { files } });

    files[0].hunks[1].selected = false;
    await flush(wrapper);

    expect(wrapper.text()).toContain("Partially Apply");
    expect(wrapper.text()).toContain("1 partial");

    const button = wrapper.findAll("button").find((b) => b.text().includes("Partially Apply"));
    await button.trigger("click");

    expect(wrapper.emitted("apply-selection")[0][0]).toEqual({
      files: [{ file: "sys/config.g", hunks: [0, 2] }],
      excludedFiles: 0,
      partialFiles: 1,
    });
  });

  it("fetches hunk detail when a panel is expanded", async () => {
    const fetchStub = mockFetch({
      "/diff?file=": { hunks: [{ index: 0, header: "@@ -1,1 +1,1 @@", lines: ["-a", "+b"] }] },
    });
    const files = reactiveFiles([{ file: "sys/config.g", status: "modified" }]);
    wrapper = mountWithVuetify(ConfigDiff, { props: { files } });

    await wrapper.find(".v-expansion-panel-title").trigger("click");
    await flush(wrapper);

    expect(fetchStub).toHaveBeenCalledWith(
      "/machine/MeltingplotConfig/diff?file=sys%2Fconfig.g"
    );
    expect(files[0].hunks).toHaveLength(1);
    expect(files[0].hunks[0].lines).toEqual(["-a", "+b"]);
  });

  it("renders the side-by-side rows of a loaded hunk", async () => {
    const files = reactiveFiles([
      { file: "sys/config.g", status: "modified", hunks: detailHunks(1) },
    ]);
    wrapper = mountWithVuetify(ConfigDiff, { props: { files } });

    await wrapper.find(".v-expansion-panel-title").trigger("click");
    await flush(wrapper);

    expect(wrapper.find(".diff-remove").exists()).toBe(true);
    expect(wrapper.find(".diff-add").exists()).toBe(true);
    expect(wrapper.text()).toContain("old0");
    expect(wrapper.text()).toContain("new0");
  });

  it("offers Create File for a missing file", async () => {
    const files = reactiveFiles([{ file: "sys/new.g", status: "missing" }]);
    wrapper = mountWithVuetify(ConfigDiff, { props: { files } });

    await wrapper.find(".v-expansion-panel-title").trigger("click");
    await flush(wrapper);

    const button = wrapper.findAll("button").find((b) => b.text().includes("Create File"));
    await button.trigger("click");
    expect(wrapper.emitted("apply-file")[0]).toEqual(["sys/new.g"]);
  });

  it("gives an extra file no checkbox and never applies it", () => {
    mountDiff([{ file: "sys/leftover.g", status: "extra" }]);
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0);
    const button = wrapper.findAll("button").find((b) => b.text().includes("Apply All"));
    expect(button.attributes("disabled")).toBeDefined();
  });
});
