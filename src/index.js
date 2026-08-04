'use strict'

import { registerRoute } from '@/routes'
import store from '@/store'
import MeltingplotConfig from './MeltingplotConfig.vue'
import { ensureBackendRunning } from './backend'

registerRoute(MeltingplotConfig, {
    Plugins: {
        MeltingplotConfig: {
            icon: 'mdi-update',
            caption: 'Meltingplot Config',
            translated: true,
            path: '/MeltingplotConfig'
        }
    }
})

// Upgrading a plugin makes DSF stop the old SBC process without starting the
// new one, which leaves the plugin "partially started" and all of its HTTP
// endpoints unreachable. Recover from that as soon as DWC loads our resources.
ensureBackendRunning(store)
