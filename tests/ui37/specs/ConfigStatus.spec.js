import { afterEach, describe, expect, it } from "vitest";

import ConfigStatus from "../../../src/ui37/components/ConfigStatus.vue";
import { mountWithVuetify } from "./helpers.js";

let wrapper;

afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
});

describe("ui37 ConfigStatus", () => {
  it("renders the values it is given", () => {
    wrapper = mountWithVuetify(ConfigStatus, {
      props: {
        status: "up_to_date",
        firmwareVersion: "3.7.0",
        activeBranch: "3.7",
        repoUrl: "https://example.com/repo.git",
        lastSync: "2026-09-10 12:00",
      },
    });

    const text = wrapper.text();
    expect(text).toContain("3.7.0");
    expect(text).toContain("https://example.com/repo.git");
    expect(text).toContain("2026-09-10 12:00");
    expect(text).toContain("Up to Date");
  });

  it("falls back to placeholders when nothing is configured", () => {
    wrapper = mountWithVuetify(ConfigStatus);

    const text = wrapper.text();
    expect(text).toContain("Not detected");
    expect(text).toContain("Not configured");
    expect(text).toContain("Never");
    expect(text).toContain("Not Configured");
    expect(text).toContain("Configure a repository URL in Settings first");
  });

  it("disables the sync button without a repository URL", () => {
    wrapper = mountWithVuetify(ConfigStatus);
    const button = wrapper.findAll("button").find((b) => b.text().includes("Check for Updates"));
    expect(button.attributes("disabled")).toBeDefined();
  });

  it("emits check-updates once a repository is configured", async () => {
    wrapper = mountWithVuetify(ConfigStatus, {
      props: { repoUrl: "https://example.com/repo.git" },
    });
    const button = wrapper.findAll("button").find((b) => b.text().includes("Check for Updates"));
    await button.trigger("click");
    expect(wrapper.emitted("check-updates")).toHaveLength(1);
  });
});
