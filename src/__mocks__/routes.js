/* eslint-env jest */
/**
 * Manual mock for DWC's @/routes module.
 *
 * In a real DWC environment, this module provides registerRoute().
 * For testing, we export a jest.fn() so we can verify the plugin's
 * registration call.
 */
export const registerRoute = jest.fn();
