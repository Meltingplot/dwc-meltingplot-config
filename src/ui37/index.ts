/**
 * DWC 3.7 entry point.
 *
 * `scripts/stage.js 37` generates a `src/index.ts` that imports this module;
 * the repository itself has no entry point, so neither generation is "the
 * default" and the raw tree is never handed to a DWC builder by accident.
 */

import { registerRoute, unregisterRoute } from "@/plugins";
import Events from "@/utils/events";

import { ensureBackendRunning } from "../core/backend";
import MeltingplotConfig from "./MeltingplotConfig.vue";
import { PLUGIN_ID, createHost } from "./host";

/** Kept identical to the DWC 3.6 route so bookmarks and docs stay valid. */
const ROUTE_PATH = "/MeltingplotConfig";

registerRoute(MeltingplotConfig, {
	Plugins: {
		MeltingplotConfig: {
			icon: "mdi-update",
			caption: "Meltingplot Config",
			translated: true,
			path: ROUTE_PATH,
		},
	},
});

// Upgrading a plugin makes DSF stop the old SBC process without starting the
// new one, which leaves the plugin "partially started" and all of its HTTP
// endpoints unreachable. Recover from that as soon as DWC loads our resources.
void ensureBackendRunning(createHost());

// DWC 3.7 can unload a plugin at runtime; drop the route with it so a reload
// does not stack a second drawer entry.
Events.on("dwcPluginUnloaded", function onUnloaded(id: string) {
	if (id === PLUGIN_ID) {
		unregisterRoute(ROUTE_PATH);
		Events.off("dwcPluginUnloaded", onUnloaded);
	}
});
