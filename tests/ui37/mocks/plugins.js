/**
 * Stand-in for DWC 3.7's `@/plugins` module.
 *
 * The real one is provided by DWC at runtime and externalised at build time
 * (it resolves to `window.DWC`), so the tests supply their own spies.
 */
import { vi } from "vitest";

export const registerRoute = vi.fn();
export const unregisterRoute = vi.fn();
