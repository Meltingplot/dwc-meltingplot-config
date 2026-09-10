# Plan: one repo, two plugin packages — DWC 3.6 and DWC 3.7

**Status:** phases 1-5 implemented except the live hardware checks and the release itself.
Deviations from the plan as written are noted inline under **Implementation notes**.
**Reference implementation:** [jaysuk/ClosedLoopTuningPlugin](https://github.com/jaysuk/ClosedLoopTuningPlugin)
(commits `4a55622` → `62efa70` → `39cbf7a` → `bfa001d` → `33e2791` on 2026‑08‑20 are the whole
dual-build introduction, in that order; `docs/PLAN-dwc36-backport.md` there is the write-up).
This document describes how their pattern maps onto this plugin, what is different for us, and the
order to do it in.

---

## 0. Why this is not a port but a second UI

DWC 3.6 and DWC 3.7 are different framework stacks. A 3.6 plugin ZIP does not load on 3.7 at all
(webpack chunk vs. IIFE bundle against `window.DWC`), and the component APIs differ everywhere:

| | DWC 3.6 (`v3.6-dev`, 3.6.3) | DWC 3.7 (`v3.7-dev`, 3.7.0‑rc.1) |
|---|---|---|
| Framework | Vue **2.7** | Vue **3.5** |
| UI kit | Vuetify **2.7** | Vuetify **4** |
| State | Vuex 3 — `@/store`, `mapState('machine/model')` | Pinia — `useMachineStore()` from `@/stores/machine` |
| Route registration | `registerRoute` from `@/routes` | `registerRoute` from `@/plugins` (or `"DuetWebControl"`) |
| Plugin build | `scripts/build-plugin[-pkg].js` → vue-cli/webpack, ZIP in `DuetWebControl/dist/` | `scripts/build-plugin[-pkg].js` → Vite lib/IIFE + **vue-tsc type check**, ZIP next to the plugin dir |
| Node | 18 works | Vite 8 / TS 6 → Node 22+ |
| `plugin.data` in the store | plain object (Vuex keeps a JSON clone) | `Map<string, any>` (typed `@duet3d/objectmodel`) |
| Plugin unload | none | `dwcPluginUnloaded` event, `unregisterRoute()` |
| Plugin load | webpack chunk named after the id | reads **`dwcFiles`** from the manifest; empty list = "SBC-only plugin", UI never loads |

Duet's own migration notes (`PLUGINS.md` in the 3.7 tree, section "Migrating from earlier DWC")
say it plainly: existing v3.4–v3.7 plugins need re-porting, the new platform is not a drop-in.

The good news is the same one jaysuk found: almost nothing in our frontend is DWC-specific.
The whole DWC coupling of this plugin is:

| Call site | What it touches |
|---|---|
| `src/index.js` | `registerRoute` (`@/routes`), root Vuex store passed to `ensureBackendRunning` |
| `src/backend.js` | `state.plugins.get(id).pid`, `store.dispatch('machine/startSbcPlugin', id)` |
| `MeltingplotConfig.vue` `computed` | `mapState('machine/model')` → `plugins.get(id).data.*` and `.pid` |
| `MeltingplotConfig.vue` `startBackend()` | `this.$store` |

Everything else is `fetch()` against our own daemon under `/machine/MeltingplotConfig/*`, plus
diff/hunk bookkeeping. That is the seam. The work is (a) a second set of Vuetify‑4 templates and
(b) build/CI plumbing that produces two ZIPs from one tree — the same two things jaysuk did.

---

## 1. How ClosedLoopTuningPlugin does it (what we copy)

1. **One logic core, two template shells.** `src/model/` (pure TS) and `src/core/` (a Composition-API
   composable `useClosedLoopTuning(host)`) hold all state and behaviour once. `src/ui37/*.vue` and
   `src/ui36/*.vue` are *template-only*: each destructures the composable and renders it with
   Vuetify 4 or Vuetify 2 markup. Logic cannot drift between generations because it exists once.
2. **A `HostAdapter` seam** (`src/core/host.ts`): the only way the shared code reaches DWC. Rule:
   *no Vue types cross this boundary*. `ui37/host.ts` implements it with Pinia, `ui36/host.ts` with
   Vuex — ~55 lines each.
3. **Two entry points, one selected at build time.** The repo's `src/index.ts` is
   `export * from "./ui37/index"`. `scripts/stage-dwc36.mjs` copies only the generation-neutral
   dirs plus `ui36/` into a temp tree, writes a generated `src/index.ts` → `./ui36/index`, copies
   `plugin.json`, and hands *that* directory to DWC 3.6's `build-plugin-pkg`. DWC's builder
   always compiles `src/index.*` and cannot be pointed at a subdirectory — staging is the
   workaround, not a preference.
4. **Same `plugin.json` for both.** `dwcVersion: "auto-major"` is resolved by *whichever DWC does the
   build*, so one manifest yields a `3.6`-tagged and a `3.7`-tagged package. Both ZIPs carry the same
   plugin version; the filename suffix (`-dwc36.zip`) tells them apart.
5. **Type checking per generation, staged as well.** `scripts/typecheck.mjs` / `verify-build.mjs`
   stage a tree *without* `ui36` for the 3.7 vue-tsc pass (the Vuex/`@/routes` imports would be a
   wall of non-bugs). `ui36` gets no type check at all; `scripts/check-ui36.mjs` compiles its SFCs
   with DWC 3.6's own Vue 2.7 compiler in ~1 s as a cheap net (markup errors only).
6. **Release builds both.** `release.yml` checks out `v3.7-dev` *and* `v3.6-dev`, builds each,
   renames the 3.6 one, and attaches both. The 3.6 leg is guarded on `src/ui36` existing, so the
   pipeline was merged before the 3.6 UI was.
7. **Local builds** are `build.bat` / `build36.bat` pointing at two local DWC checkouts.
8. **Dependency vendoring** (`VENDOR = ["chart.js", "dwc-plugin-runtime"]` copied into the staged
   `src/node_modules/`) because DWC 3.6's builder does not install a plugin's npm deps and the
   checkout ships an incompatible chart.js.

### What we do **not** need from their setup

| Their concern | Us |
|---|---|
| chart.js / `dwc-plugin-runtime` vendoring into the 3.6 stage | no runtime npm dependencies at all — skip |
| `registerPluginMessages` vs `i18n.mergeLocaleMessage` | captions are literals with `translated: true`, no i18n keys — skip (works identically in both) |
| `assetPattern` regexes for the self-updater | no self-update — skip, but keep the naming rule below in case one is added |
| `AboutDialog` / `HelpTip` reimplemented for Vue 2 | not used |
| `dwc-plugin-test-kit` reusable CI workflow | we already have our own CI with a Python matrix — extend it instead |

### What we have that they don't

- A **Python backend** in `dsf/`. Both DWC generations' `build-plugin-pkg` copy `dsf/` into the ZIP
  and populate `dsfFiles`. The stage script must copy `dsf/` alongside `src/` — the builder reads
  extras from the directory it is given, not from the repo.
- A **large Jest suite on Vue 2**. Their root `package.json` is Vue 3 only and 3.6 is compile-checked;
  we keep the Vue 2 suite and add a Vue 3 one (see §5).
- A **release branch flow** (`main` → `release` → tag by workflow) rather than tag-push. Kept as is.

---

## 2. Findings that shape the plan (verified against the sources)

1. **`release.yml` is already a time bomb.** It builds against the *highest* `vX.Y.Z` tag of
   DuetWebControl. Today that is `v3.6.3`; the day Duet3D tags `v3.7.0` every release build
   compiles Vue 2 sources with the Vite toolchain and fails. Pin per generation (latest `v3.6.*`,
   latest `v3.7.*`) — do this first, independent of everything else (Phase 1).
2. **Use `build-plugin-pkg`, not `build-plugin`, for 3.7.** 3.7's `loadExternalPlugin` takes the
   JS/CSS list from `manifest.dwcFiles`; `build-plugin.js` leaves it empty, so DWC would register
   the plugin as SBC-only and never load the page. `build-plugin-pkg.js` fills `dwcFiles` and
   `dsfFiles`. Use `-pkg` for 3.6 as well for symmetry (it also fills `dsfFiles`).
3. **No `package.json` in the staged tree.** 3.7's builder runs `npm install` inside the plugin dir
   when any `dependencies` *or `devDependencies`* are not resolvable from there. Our root
   `package.json` lists Vue 2, Vuetify 2, Jest… Staging `src/`, `dsf/`, `plugin.json` only means
   the builder has nothing to install and bundles with DWC's own externals.
4. **`plugin.data` is a `Map` on 3.7**, a plain object on 3.6 (`@duet3d/objectmodel` 3.6.3 also
   declares a Map, but DWC 3.6's Vuex module stores a JSON clone). The host adapter normalises this;
   nothing above it may index `data` directly.
5. **3.7 only type-checks TypeScript.** `PLUGINS.md`: "pure-JavaScript plugins are not
   type-checked". The vue-tsc pass checks templates against Vuetify 4's real prop types — exactly
   the class of bug ("`dense` survived the translation") that jaysuk had to find on a live machine
   for their untyped generation. So the ui37 SFCs are written as `<script setup lang="ts">`
   (they are thin) even though the shared core stays JS with JSDoc.
6. **Two `vue` majors cannot share one `node_modules`.** A second package directory with its own
   `package.json` is needed for the Vue 3 tests; and its Vitest config must alias `vue`/`vuetify`
   explicitly, because `src/core/*.js` importing `vue` would otherwise resolve upward to the root's
   Vue 2 (§5).
7. **`sbcDsfVersion: "auto-major"`** makes the 3.7 package require **DSF 3.7**. That is right
   (DWC 3.7 ships with DSF 3.7) but it makes the Python backend's compatibility with dsf-python
   3.7 a release gate for the 3.7 ZIP (§7).
8. **Both generations reject the other's ZIP at install** (`dwcVersion` `3.6` ≠ `3.7`), so a user
   grabbing the wrong file gets an error, not a broken install. Still name the files unambiguously.

---

## 3. Target layout

```
src/
  core/                      # shared, framework-neutral (Vue 2.7 AND Vue 3 via `import … from 'vue'`)
    host.js                  #   HostAdapter contract (JSDoc typedef) + pluginEntry()/pluginData() helpers
    api.js                   #   API_BASE, apiGet/apiPost/extractErrorMessage, download helpers
    diff.js                  #   FILE_STATUS, parseHunkHeader, sideBySideLines, selection state
    backend.js               #   MOVED from src/backend.js — takes a host, not a Vuex store
    useConfigPage.js         #   state + actions of the main page (sync, diff, apply, settings, snackbar…)
    useConfigDiff.js         #   file/hunk selection, expand-on-demand detail fetch
    useBackupHistory.js      #   backup list, expand, file diff/content, manual backup
  ui36/                      # Vue 2.7 / Vuetify 2 — TODAY'S components, logic moved out
    index.js                 #   registerRoute from '@/routes', store from '@/store'
    host.js                  #   Vuex adapter
    MeltingplotConfig.vue  components/ConfigStatus.vue  ConfigDiff.vue  BackupHistory.vue
  ui37/                      # Vue 3 / Vuetify 4 — NEW, template-only, <script setup lang="ts">
    index.ts                 #   registerRoute from '@/plugins', unregisterRoute on dwcPluginUnloaded
    host.ts                  #   Pinia adapter
    MeltingplotConfig.vue  components/ConfigStatus.vue  ConfigDiff.vue  BackupHistory.vue
  routes.js  store.js  __mocks__/   # Jest-only stubs, unchanged, excluded from staging
dsf/                          # unchanged, copied into BOTH packages
scripts/
  stage.js                   # node scripts/stage.js 36|37 <outDir>  → src/ + dsf/ + plugin.json (+ generated src/index.js)
  build.js                   # node scripts/build.js 36|37  (uses DWC36_DIR / DWC37_DIR, stages, runs build-plugin-pkg, renames ZIP)
  build-zip.js               # keep for plugin-structure tests; take a generation argument, reuse stage.js
  version.js                 # unchanged
tests/
  frontend/                  # root Jest (Vue 2): core/*, ui36/*, integration/*, api-contract
  ui37/                      # nested npm package: Vitest + Vue 3 + Vuetify 4 (+ core/* run a 2nd time)
```

There is deliberately **no `src/index.js` in the repo**. Both generations are built through
`scripts/stage.js`, which writes the one-line entry (`import './ui36/index'` or `'./ui37/index'`)
into the staged tree. Neither generation is "the default" and the raw repo is never handed to a DWC
builder by accident. (jaysuk keeps a real `src/index.ts` for 3.7 and stages only 3.6; the symmetric
version is simpler for CI and costs nothing here.)

---

## 4. The host seam for this plugin

```js
/** @typedef {object} Host
 *  @property {() => object} model            live object model (must read reactive state on every call)
 *  @property {(id: string) => Promise<void>} startSbcPlugin
 */
```

That is the entire interface. Helpers in `core/host.js` (pure, unit-tested, shared):

- `pluginEntry(model)` → the `Plugin` object for `MeltingplotConfig` from `model.plugins`
  (Map or plain object — tests use plain objects).
- `pluginDataValue(plugin, key, fallback)` → reads `plugin.data`, which is a `Map` on 3.7 and an
  object on 3.6.
- `isBackendRunning(model)` → `pid > 0` / `null` when unknown (moved from `backend.js`).

Adapters:

| | `ui36/host.js` | `ui37/host.ts` |
|---|---|---|
| `model()` | `store.state.machine.model` | `useMachineStore().model` |
| `startSbcPlugin(id)` | `store.dispatch('machine/startSbcPlugin', id)` | `useMachineStore().startSbcPlugin(id)` |
| built where | module scope of `index.js` (Vuex store is a singleton) | module scope of `index.ts` — DWC loads external plugins after Pinia is active, and the store is resolved per call anyway |

The composables take the host as an argument (`useConfigPage(host)`), exactly like
`useClosedLoopTuning(createHost())`. Entry points create the host and register the route; page
components call `createHost()` from their own generation's `host` module.

**Vue 2.7 reactivity landmine for the composables:** `this.$set(backup, 'expanded', …)` is used 30+
times today because Vue 2 cannot observe added properties. In shared code, every field a file/backup
entry will ever carry (`selected`, `expanded`, `loadingFiles`, `files`, `changedFiles`, `selectedFile`,
`fileDiff`, `fileContent`, `viewMode`, `loadingDiff`, `loadingDetail`, `hunks[i].selected`) is
initialised when the entry is created (a `normalizeBackup()` / `normalizeFile()` in `core/`), and
updates go through `reactive()`/`ref()` from `vue`. No `$set`, no late property additions.
Vue 3 does not care; Vue 2.7 silently stops updating if this rule is broken.

---

## 5. Toolchain: build, test, lint

### 5.1 `scripts/stage.js 36|37 <outDir>`

- `rm -rf outDir`; copy `src/core/`, `src/ui<gen>/`, `dsf/`, `plugin.json`.
- Exclude `src/routes.js`, `src/store.js`, `src/__mocks__/`, the other `ui*/`.
- Write `outDir/src/index.js`: `import './ui36/index'` or `import './ui37/index'` with a
  "generated, do not edit" banner.
- Do **not** write a `package.json` (finding 3).
- Print the staged path on the last line (jaysuk's convention, handy in shell).

### 5.2 `scripts/build.js 36|37` (replaces the `.bat` pair with one cross-platform script)

| | 36 | 37 |
|---|---|---|
| env | `DWC36_DIR` (a `v3.6-dev` checkout with `npm install` done) | `DWC37_DIR` (a `v3.7-dev` checkout, Node 22+) |
| pre-clean | `rm -rf $DWC36_DIR/src/plugins/MeltingplotConfig` (a stale copy from an interrupted run gets compiled again) | — |
| command | `cd $DWC36_DIR && npm run build-plugin-pkg -- <stage>` | `cd $DWC37_DIR && node scripts/build-plugin-pkg.js <stage>` |
| ZIP lands in | `$DWC36_DIR/dist/MeltingplotConfig-<v>.zip` | `<stage>/MeltingplotConfig-<v>.zip` (+ `-srcmap.zip` for non-prerelease versions) |
| move to | `dist/MeltingplotConfig-<v>-dwc36.zip` | `dist/MeltingplotConfig-<v>-dwc37.zip` (drop the srcmap ZIP, or keep it as `-dwc37-srcmap.zip`) |

**Naming decision:** suffix **both** ZIPs. jaysuk leaves the 3.7 one bare because 3.7 is their
primary target. Our installed base is on 3.6 and downloads "the" ZIP today; a bare name that silently
switches meaning to 3.7 would bite them. Explicit `-dwc36` / `-dwc37` on every asset, and anything
matching `*.zip` in CI globs must exclude `-srcmap`.

### 5.3 Tests

Two runners, because two Vue majors cannot coexist in one `node_modules`:

| Runner | Location | Deps | Covers |
|---|---|---|---|
| **Jest 29** (exists) | root, `tests/frontend/` | Vue 2.7, Vuetify 2, `@vue/test-utils` 1, `@vue/vue2-jest` | `core/*` (composables run under Vue 2.7's reactivity), `ui36/*` components (today's tests, paths updated), `integration/*`, `api-contract` |
| **Vitest** (new) | `tests/ui37/` with its own `package.json` | Vue 3.5, Vuetify 4, `@vue/test-utils` 2, `@vitejs/plugin-vue`, `happy-dom` | `ui37/*` mount + interaction tests with mocked `fetch`; **and the same `tests/frontend/core/*.test.js` files a second time** under Vue 3 — proves the shared code runs on both reactivity systems |

Vitest config essentials (this is where it goes wrong if done naively):

```js
resolve: {
  alias: {
    '@/plugins':        './mocks/plugins.js',        // registerRoute/unregisterRoute spies
    '@/stores/machine': './mocks/machineStore.js',   // reactive { model: { plugins: Map }, startSbcPlugin }
    '@/utils/events':   './mocks/events.js',
    vue:      path.resolve('tests/ui37/node_modules/vue'),      // core/*.js would otherwise resolve
    vuetify:  path.resolve('tests/ui37/node_modules/vuetify'),  // upward to the root's Vue 2
  },
  dedupe: ['vue', 'vuetify'],
}
```

Our mocked DWC surface is three functions, so hand-rolled mocks (~60 lines) are preferred over
adding `dwc-plugin-test-kit` as a dependency; the kit remains an option if the surface grows.

CI: root `npm test` on Node 20; `npm --prefix tests/ui37 ci && npm --prefix tests/ui37 test` on Node 22.

Optional, cheap, like jaysuk's `check-ui36`: `scripts/check-sfc.js 36|37` compiling the SFCs with the
respective DWC checkout's `vue/compiler-sfc` in ~1 s for local iteration. CI does not need it —
CI runs the real builds.

### 5.4 Lint

`eslint-plugin-vue` 9 has both rule sets; use overrides instead of two configs:

- `src/ui36/**` → `plugin:vue/recommended` (Vue 2 rules, as today)
- `src/ui37/**` → `plugin:vue/vue3-recommended`, `parserOptions.parser: '@typescript-eslint/parser'`
  (new devDep, needed for `lang="ts"` blocks)
- `src/core/**` → plain `eslint:recommended`

### 5.5 CI (`.github/workflows/ci.yml`)

Keep `python-tests` and `frontend-tests` (add the Vitest step). Replace the single `build` job with a
matrix:

| `gen` | `dwc-ref` (input override kept) | Node | steps |
|---|---|---|---|
| 36 | `v3.6-dev` | 18 (known good; 20 should work, verify) | checkout DWC → `npm install` → `version.js --write` → `stage.js 36` → `build-plugin-pkg` → rename → upload `MeltingplotConfig-plugin-dwc36` |
| 37 | `v3.7-dev` | 22 | same with `stage.js 37`; the vue-tsc type check runs inside `build-plugin-pkg` and fails the job on template type errors |

Each leg uploads its own artifact. `Verify build output` asserts the ZIP contains `plugin.json`
with the expected `dwcVersion` (`3.6` / `3.7`), `dsf/*.py`, and `dwc/js/MeltingplotConfig*.js`.

### 5.6 Release (`.github/workflows/release.yml`)

- Replace "latest stable tag" with two resolutions: highest `v3.6.[0-9]+` tag, and highest
  `v3.7.*` tag — allow `-rc`/`-beta` for 3.7 **until a stable `v3.7.0` exists**, then prefer stable
  (`sort -V | grep -E '^v3\.7\.[0-9]+$' | tail -1 || fallback to prerelease`).
- Build both legs (matrix or two sequential step groups), collect both ZIPs, and attach both to the
  GitHub Release. `--notes` lists both DWC refs.
- The `main → release → tag` rule in `CLAUDE.md` is unchanged; `plugin.json` still carries the one
  version both packages share.

---

## 6. Vuetify 2 → 4 translation table for *our* templates

Measured over the four SFCs (34 `v-icon`, 22 `v-btn`, 10 `v-chip`, 77× `text`, 28× `small`, 16×
`x-small`, 15× `outlined`, 11× `dense`, …). Every row is a silent-breakage risk — valid markup,
wrong behaviour — which is why the ui37 SFCs are TypeScript (finding 5).

| Vuetify 2 (ui36) | Vuetify 4 (ui37) |
|---|---|
| `<v-tabs v-model>` + `<v-tab>` + `<v-tabs-items v-model>` / `<v-tab-item>` | `<v-tabs v-model>` + `<v-tab :value>` + `<v-tabs-window v-model>` / `<v-tabs-window-item :value>` |
| `<v-list-item-icon>`, `<v-list-item-content>`, `<v-list-item-action>` | gone — `prepend-icon` / `#prepend` / `#append` slots; `v-list-item-title/-subtitle` remain |
| `<v-expansion-panel-header>` / `-content` | `<v-expansion-panel-title>` / `-text` |
| `v-btn text` / `outlined` / `flat` | `variant="text"` / `"outlined"` / `"flat"` |
| `small`, `x-small` (btn, chip, icon) | `size="small"`, `size="x-small"` |
| `v-btn icon` + inner `<v-icon>` | `icon="mdi-…"` prop, or `icon` + default slot |
| `<v-icon left>` / `right` | `start` / `end` |
| `dense` (list, text-field, toolbar, alert) | `density="compact"` |
| `<v-text-field outlined dense>` | `variant="outlined" density="compact"` |
| `<v-select item-text>` | `item-title` |
| `<v-alert text type dense>` | `variant="tonal" type density="compact"` |
| `<v-treeview activatable :active.sync item-key item-text :open.sync>` | `v-model:activated`, `item-value`, `item-title`, `v-model:opened` (VTreeview is in DWC 3.7 — ObjectModelBrowser uses it) |
| `#activator="{ on, attrs }"` + `v-bind="attrs" v-on="on"` | `#activator="{ props }"` + `v-bind="props"` |
| `this.$set(obj, k, v)` | not needed — and not allowed in `core/` either (§4) |
| `v-snackbar`, `v-dialog`, `v-btn-toggle mandatory`, `v-expand-transition`, `v-progress-circular` | same names, check `v-model` value types |

Vuetify 4 components are globally registered by DWC 3.7 before any external plugin loads
(`ensurePluginExtras()`), so no explicit imports in templates — same as 3.6.

Registration differences, all inside `ui37/index.ts`:

```ts
import { registerRoute, unregisterRoute } from "@/plugins";   // 3.6: from "@/routes"
import Events from "@/utils/events";
import { createHost } from "./host";
import { ensureBackendRunning } from "../core/backend";
import MeltingplotConfig from "./MeltingplotConfig.vue";

registerRoute(MeltingplotConfig, { Plugins: { MeltingplotConfig: {
  icon: "mdi-update", caption: "Meltingplot Config", translated: true, path: "/MeltingplotConfig",
}}});
void ensureBackendRunning(createHost());
Events.on("dwcPluginUnloaded", function off(id) {            // 3.6 has no unload — nothing to do there
  if (id === "MeltingplotConfig") { unregisterRoute("/MeltingplotConfig"); Events.off("dwcPluginUnloaded", off); }
});
```

Keep the route path identical in both generations (bookmarks, docs).

---

## 7. Backend on DSF 3.7 — parallel track, release gate for the 3.7 ZIP

Not part of the frontend work, but the 3.7 package requires DSF 3.7 (finding 7) and our daemon has
never run there:

- `sbcPythonDependencies: ["dsf-python"]` installs whatever PyPI serves into the plugin venv. dsf-python
  has a `v3.7-dev` branch and a `3.7.0-beta.1` tag. Check whether the three monkey-patches in
  `meltingplot-config-daemon.py` (`PluginManifest._data`, `BoardState.timedOut`,
  `NetworkInterfaceType.ethernet`) are still needed, still apply cleanly, or now break on the new
  classes. They are written defensively (replace-the-enum, `try/except ImportError`) so the likely
  outcome is "harmless", but `get_object_model()` on a real DSF 3.7 SBC is the test.
- `resolve_path`, `add_http_endpoint`, `set_plugin_data` signatures: diff `v3.6-dev` vs `v3.7-dev`
  of `base_command_connection.py`.
- If DSF 3.7 changes anything, it must be handled with runtime detection in the one shared `dsf/`
  tree — there is one backend for both packages by design.

---

## 8. Phases

Each phase ends with green CI and a commit that could ship. Order matters: 1 is a bug fix, 2 is the
only phase that can regress the working 3.6 plugin, 3 proves the pipeline before the expensive UI work.

### Phase 1 — pin the release build (small, do now) — **done**
- `release.yml`: resolve the latest **`v3.6.*`** tag instead of the latest tag overall.
- No other change. Ships as its own PR.

### Phase 2 — extract the seam and the composables (3.6 only, no behaviour change) — **done**
- Create `src/core/{host,api,diff,backend,useConfigPage,useConfigDiff,useBackupHistory}.js`.
- Rewire the existing four SFCs to consume them via `setup()` (Options API stays for the rest of the
  component; no `<script setup>` on ui36 yet — least churn, `@vue/vue2-jest` is happier).
- Remove every `$set`; normalise entries up front (§4).
- Move tests for extracted logic (`parseHunkHeader`, `sideBySideLines`, selection state,
  `isBackendRunning`, `ensureBackendRunning`) to `tests/frontend/core/`. Existing component tests
  keep passing.
- Build the 3.6 ZIP with today's CI and **smoke-test on a printer**: sync, diff, partial apply,
  backup, restore, backend auto-start after upgrade. This is the regression checkpoint.

### Phase 3 — restructure and build machinery, with a stub ui37 — **done, except the live checks**
- Move SFCs to `src/ui36/`, entry to `src/ui36/index.js`, adapter `src/ui36/host.js`.
- Add `scripts/stage.js`, `scripts/build.js`; rework `scripts/build-zip.js` on top of `stage.js`;
  update `plugin-structure` and `plugin-registration` tests.
- Add `src/ui37/index.ts`, `host.ts`, and a placeholder `MeltingplotConfig.vue` (a `v-card` with the
  status text) so the 3.7 leg has something to build and type-check.
- CI matrix `36`/`37`; `release.yml` two legs, both assets.
- **Verify on DWC 3.7 + DSF 3.7:** the `-dwc37.zip` installs, the page appears, the SBC backend is
  started by `ensureBackendRunning` through the Pinia adapter, `/machine/MeltingplotConfig/status`
  answers. And the `-dwc36.zip` still installs on 3.6. And each is rejected by the other.

### Phase 4 — the DWC 3.7 UI — **done, except the live check**
- Port the four SFCs to Vuetify 4 as template-only `<script setup lang="ts">` components over the
  shared composables (translation table §6). Suggested order: `ConfigStatus` (props only) →
  `MeltingplotConfig` shell with tabs → `ConfigDiff` → `BackupHistory` (treeview last). Build after
  each; do not write all four and then build.
- `tests/ui37/` Vitest project; run `core/*` tests there too; ESLint overrides.
- Live check on DWC 3.7 for every flow in the Phase 2 smoke list.

### Phase 5 — docs and release — **docs done; version bump and release open**
- README: two ZIPs, which one to install, local build instructions (`DWC36_DIR`, `DWC37_DIR`).
- CLAUDE.md: layout, "never index `plugin.data` directly", the two test runners, the Vue 2.7
  reactivity rule for `core/`, the stage-script rule ("the raw repo is never handed to a DWC builder").
- Version bump, PR to `main`, PR `main → release`; the workflow attaches both packages.

Rough size: Phase 2 ≈ the largest refactor (≈1,100 lines of component logic move into composables);
Phase 4 ≈ 1,000–1,200 lines of new template; Phases 1, 3, 5 are plumbing. jaysuk's page of similar
size came out at 672 (3.6) vs 662 (3.7) lines of template after the logic was extracted — expect a
similar near-1:1 ratio here.

---

## 9. Landmines (theirs, plus ours)

1. **A green 3.7 build does not mean the page loads.** Check `dwcFiles` is populated in the ZIP's
   `plugin.json` (finding 2) — CI's verify step asserts it.
2. **`plugin.data` indexing.** `data.referenceRepoUrl` works on 3.6 and returns `undefined` on 3.7
   without an error. Only `pluginDataValue()` may touch it.
3. **`vue` resolution in the nested Vitest package** (§5.3). Symptom: "Vue packages version
   mismatch" or components rendering nothing.
4. **Vue 2.7 and late-added properties** in shared composables (§4). Symptom: 3.6 UI stops updating
   after an action that works fine on 3.7.
5. **Staged tree with a `package.json`** makes 3.7's builder `npm install` Vue 2 into it (finding 3).
6. **`-srcmap.zip` sorts before the real ZIP** (`-` < `.`). Any `ls | head -1` in CI must filter it —
   jaysuk shipped a sourcemap archive as a release once because of this.
7. **DWC 3.6 `build-plugin-pkg` copies the plugin into `src/plugins/<id>` inside the checkout** and
   removes it afterwards; an interrupted run leaves a stale copy that is compiled on the next run.
   `build.js 36` removes it up front.
8. **`translated: true`** keeps the literal caption in both generations; do not "fix" it into an i18n
   key on one side only.
9. **Node versions differ per leg.** 3.6 on Node 18 is proven; 3.7 needs 22+. One `setup-node` per
   matrix leg, not one for the job.
10. **`sbcDsfVersion`** is resolved per build too: the 3.7 ZIP will refuse a DSF 3.6 SBC. That is
    intended; document it in the README next to the download links.


---

## 10. Implementation notes

What the implementation does differently from the plan above, and what it confirmed.

### Confirmed against the real toolchains

- Both legs build. The 3.6 package comes out with `dwcVersion: "3.6"` and a populated
  `dwcFiles`/`dsfFiles`; the 3.7 package with `dwcVersion: "3.7"`, `sbcDsfVersion: "3.7"`
  and a 13 kB IIFE bundle. `build-plugin-pkg` is right for both (finding 2).
- DWC 3.6's `build-plugin-pkg` copies the staged tree to `src/plugins/<id>/` and picks up
  the `index.js` that staging already wrote there; it also pre-cleans that directory
  itself, so `build.js`'s own `rm -rf` is belt-and-braces rather than the only guard
  (landmine 7 is milder than stated).
- `findEntryFile` in 3.7 accepts `index.ts`, `index.js`, `dwc-src/index.*`, `src/index.*`,
  so `src/index.ts` for the 3.7 stage and `src/index.js` for 3.6 both work.
- `typeCheckPlugin` includes only `**/*.ts`, `**/*.tsx`, `**/*.vue` from the plugin dir —
  `src/core/*.js` is pulled in through imports and inferred, not error-checked. DWC's
  tsconfig has `allowJs: true` and `strict: true`.
- `-srcmap.zip` is real: the 3.7 build emitted one next to the package (landmine 6).
  `build.js` filters it out by suffix rather than by sort order.

### Deviations

- **An extra core module.** `src/core/status.js` holds the sync-status chip map. The plan's
  file list did not have one, but the map is needed by both generations and belongs
  neither in `diff.js` nor in `host.js`.
- **No `scripts/check-sfc.js`.** It was listed as optional; the real builds cover it.
- **`build-zip.js` takes a generation argument** and writes `-dwc<gen>` names, driven by
  `stage.js`. It also honours `ZIP_OUT_DIR` so the plugin-structure tests do not wipe a
  developer's `dist/`.
- **`scripts/ci-local.sh` gained `build36` / `build37` stages** instead of the plan's
  `build.bat` / `build36.bat` pair. When the host Node is older than 22, the 3.7 leg runs
  in a `node:22` container.
- **Test stores now mirror DWC's real shape.** They used a flat module literally named
  `machine/model`, which only worked because `mapState('machine/model')` resolves by
  namespace. The Vuex host adapter reads `store.state.machine.model`, so the test stores
  became a namespaced `machine` module with a `model` child — which is what DWC has.
- **Normalisation splices rather than patches.** The plan says entries carry every field
  from creation. That holds for entries created by `loadDiff` / `loadBackups`, but a
  component can also be handed a raw list directly (tests do). Patching those in place
  would add properties to an already-reactive object, which Vue 2.7 cannot observe, so the
  watcher replaces the entries with normalised ones via `splice`.
- **Two JSDoc changes were forced by vue-tsc**, and both are worth keeping:
  - `@returns {object}` on the composables flattened their return type to `{}` and hid
    every binding from the 3.7 templates. The annotations are gone; the return type is
    inferred.
  - `readPluginData()` built its result in a loop over a defaults map, which also inferred
    as `{}`. It now writes the six keys out, and `pluginDataValue()` is `@template`-typed,
    so the templates get real `string` properties.
- **`ui37/host.ts` imports the `Host` type from `core/host.js`** rather than declaring its
  own interface — a locally declared one drifted immediately (`model(): unknown` vs
  `object`) and vue-tsc rejected it.

### Still to verify on hardware

- The phase-2 smoke list on a DWC 3.6 printer: sync, diff, partial apply, backup, restore,
  backend auto-start after an upgrade.
- The phase-3 live checks: the `-dwc37.zip` installs on DWC 3.7 + DSF 3.7, the page
  appears, `ensureBackendRunning` starts the daemon through the Pinia adapter,
  `/machine/MeltingplotConfig/status` answers — and each package is rejected by the other
  generation.
- Section 7 (the Python backend against DSF 3.7 / dsf-python 3.7) is untouched and remains
  a release gate for the 3.7 package.


### Phase 4 notes

- **The 3.7 UI is a 1:1 port**, as expected: the same four components over the same
  composables, with the Vuetify 2 -> 4 translation table applied. No logic moved into a
  template.
- **vue-tsc earned its keep before a single line of markup was reviewed.** It rejected two
  JSDoc annotations that had quietly erased type information (see the deviations above),
  a locally re-declared `Host` interface that had already drifted, and a `file.hunks.length`
  the compiler could not prove non-null.
- **`tests/ui37/` runs 123 tests**: 34 for the four components and the entry point, and the
  89 shared-core tests a second time under Vue 3. Three settings in `vitest.config.mjs`
  turned out to be load-bearing, and none of them fails with a message that points at the
  cause:
  - `resolve.alias` for `vue` / `vuetify` — without it they resolve from the project root
    to Vue 2 / Vuetify 2 and components render nothing.
  - Those aliases must be **anchored regexes**. As plain strings they also rewrite
    subpaths, and `vuetify/components` becomes a directory path that no longer resolves
    through the exports map.
  - `server.fs.allow` must name the repository root, or every import from `src/` and
    `tests/frontend/` fails with "Does the file exist?" for a file that plainly does.
- **Props are not deep-reactive under Vue 3 either**, so a spec that mutates an entry after
  mounting holds the list in `reactive()` — mirroring the parent's ref.
- The plan's optional `scripts/check-sfc.js` was skipped: the real builds and the Vitest
  project cover it.


### Section 7 — the Python backend on DSF 3.7 (audited at source level)

Checked `dsf-python` `v3.6-dev` against `v3.7-dev` (3.7.0-beta.1). Every module path the
daemon patches still exists in 3.7, `PluginManifest.__init__` keeps its signature, and
`Board.state` / `NetworkInterface.type` are still real property objects, so `.setter()`
still works. All three patches apply.

What 3.7 changed, and what it means per patch:

- **The property system was rewritten.** Hand-written `@property` setters became
  `model_prop(...)` descriptors built at class-definition time, which capture their enum
  then and there. Replacing a module-level enum afterwards therefore no longer reaches the
  setter on 3.7 — but replacing the setter does. Each of the two enum patches already does
  both, so both generations stay covered; which half is load-bearing just swaps over.
- **`PluginManifest._data` is fixed upstream** (`model_prop('data', ModelDictionary, ...)`).
  Our patch assigns the same thing the descriptor's default would, so it is redundant but
  harmless.
- **`BoardState.timedOut` is still missing.** Load-bearing on both.
- **`NetworkInterfaceType` gained `ethernet` — and lost `lan`.** The same class of crash
  moved to the other value; our replacement enum carries both.
- **`resolve_path`, `add_http_endpoint`, `set_plugin_data` keep their signatures.**
  `resolve_path` still returns the raw `Response`, so that unwrap is still needed.
  `set_plugin_data`'s `value` widened from `str` to `object`.

Changes made off the back of this: the three patches are now named functions applied
through `_apply_dsf_workaround()`, which reports a patch that no longer fits on stderr
instead of raising — a library that has moved on must not take the daemon down at import
time. `tests/test_daemon_workarounds.py` covers each patch against fakes shaped like
dsf-python's own classes (24 tests).

This is a source-level audit. `get_object_model()` on a real DSF 3.7 SBC is still the test,
and remains the release gate for the 3.7 package.
