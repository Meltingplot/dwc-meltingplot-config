import { vi } from "vitest";

// The shared-core tests are written for Jest and run unchanged here, so `jest`
// has to answer to `fn` and `spyOn`. Vitest's `vi` provides both.
globalThis.jest = vi;

// Vuetify components observe their container; happy-dom has no ResizeObserver.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Vuetify's display composable reads matchMedia on mount.
if (!globalThis.matchMedia) {
  globalThis.matchMedia = () => ({
    matches: false,
    media: "",
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  });
}

// happy-dom has no visualViewport, which Vuetify's overlays read.
if (!globalThis.visualViewport) {
  globalThis.visualViewport = {
    width: 1280,
    height: 800,
    addEventListener() {},
    removeEventListener() {},
  };
}
