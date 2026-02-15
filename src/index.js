'use strict'

import { registerRoute } from '@/routes'
import MeltingplotConfig from './MeltingplotConfig.vue'

registerRoute(MeltingplotConfig, {
    Plugins: {
        MeltingplotConfig: {
            icon: 'mdi-update',
            caption: 'Meltingplot Config',
            translated: true,
            path: '/MeltingplotConfig'
        }
    }
});
