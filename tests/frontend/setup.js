/**
 * Jest test setup — creates a minimal Vuetify instance for component tests.
 */
import Vue from 'vue';
import Vuetify from 'vuetify';

Vue.use(Vuetify);
Vue.config.productionTip = false;

// Provide a fresh Vuetify instance for each test file
global.createVuetify = () => new Vuetify();
