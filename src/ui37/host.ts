/**
 * DWC 3.7 host adapter — the Pinia side of the seam described in
 * `src/core/host.js`. No Vue or Pinia types leak past this module.
 */

import { useMachineStore } from "@/stores/machine";

import { PLUGIN_ID, type Host } from "../core/host";

/**
 * Build a Host backed by DWC 3.7's Pinia machine store.
 *
 * The store is resolved per call rather than captured, so the adapter can be
 * created at module scope before Pinia is fully wired up — and so the object
 * model is read live, which is what the shared computeds track.
 */
export function createHost(): Host {
	return {
		model() {
			return useMachineStore().model;
		},
		async startSbcPlugin(id: string) {
			await useMachineStore().startSbcPlugin(id);
		},
	};
}

export { PLUGIN_ID, type Host };
