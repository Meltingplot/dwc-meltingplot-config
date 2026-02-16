/**
 * Jest test setup — creates a minimal Vuetify instance for component tests.
 */
import Vue from 'vue';
import Vuetify from 'vuetify';

Vue.use(Vuetify);
Vue.config.productionTip = false;

// Provide a fresh Vuetify instance for each test file
global.createVuetify = () => new Vuetify();

// Add data-app attribute to the document body so Vuetify's detachable
// components (v-dialog, v-menu, v-snackbar) can find their mount target.
// Without this, full-mount integration tests emit console warnings.
document.body.setAttribute('data-app', 'true');
