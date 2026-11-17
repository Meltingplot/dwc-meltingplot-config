import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");

/** Vue and Vuetify must come from this package, never from the repo root. */
const local = (name) => resolve(here, "node_modules", name);

export default defineConfig({
  // The repo root, so the shared core and the ui37 sources are inside the
  // project and the core tests can be included from tests/frontend/.
  root: repoRoot,
  plugins: [vue()],
  server: {
    fs: {
      // The specs live in tests/ui37 but import from src/ and tests/frontend;
      // without this Vite refuses to read anything outside the config's own
      // directory and every import fails with "Does the file exist?".
      strict: false,
      allow: [repoRoot],
    },
  },
  resolve: {
    alias: [
      // DWC provides these at runtime; the plugin build externalises them.
      { find: "@/plugins", replacement: resolve(here, "mocks", "plugins.js") },
      { find: "@/stores/machine", replacement: resolve(here, "mocks", "machineStore.js") },
      { find: "@/utils/events", replacement: resolve(here, "mocks", "events.js") },
      // src/core/*.js and src/ui37/*.vue import `vue` and `vuetify`. Resolution
      // walks up from those files, which would find the root package's Vue 2 —
      // components would then render nothing.
      //
      // Anchored regexes, not plain strings: a string alias also rewrites
      // subpaths, so `vuetify/components` would become a bare directory path
      // and stop resolving through the package's exports map. Subpath imports
      // come from tests/ui37 itself and find this package's copy on their own.
      { find: /^vue$/, replacement: local("vue") },
      { find: /^vuetify$/, replacement: local("vuetify") },
      // Subpaths need their own entries: Vite resolves bare imports from the
      // project root, where `vuetify` is the root package's version 2 — which
      // has no `./components` export and fails outright.
      { find: /^vuetify\/components$/, replacement: local("vuetify/lib/components/index.js") },
      { find: /^vuetify\/directives$/, replacement: local("vuetify/lib/directives/index.js") },
    ],
    dedupe: ["vue", "vuetify"],
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: [resolve(here, "setup.js")],
    include: [
      // The shared core, run a second time under Vue 3's reactivity
      "tests/frontend/core/**/*.test.js",
      // The DWC 3.7 components
      "tests/ui37/specs/**/*.spec.js",
    ],
    server: {
      deps: {
        inline: ["vuetify"],
      },
    },
  },
});
