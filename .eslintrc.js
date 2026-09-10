module.exports = {
    root: true,
    env: {
        browser: true,
        es2020: true
    },
    // The shared core is framework-neutral: plain ESLint, no Vue rules.
    extends: ['eslint:recommended'],
    parserOptions: {
        ecmaVersion: 2020,
        sourceType: 'module'
    },
    rules: {
        'no-console': 'warn',
        'no-unused-vars': ['error', { argsIgnorePattern: '^_' }]
    },
    globals: {
        fetch: 'readonly'
    },
    overrides: [
        {
            // DWC 3.6 UI — Vue 2.7 / Vuetify 2.7
            files: ['src/ui36/**/*.{js,vue}'],
            extends: ['eslint:recommended', 'plugin:vue/recommended'],
            rules: {
                'vue/html-indent': ['error', 2],
                'vue/max-attributes-per-line': 'off',
                'vue/singleline-html-element-content-newline': 'off',
                'vue/multi-word-component-names': 'off'
            }
        },
        {
            // DWC 3.7 UI — Vue 3.5 / Vuetify 4, <script setup lang="ts">
            files: ['src/ui37/**/*.{ts,vue}'],
            extends: ['eslint:recommended', 'plugin:vue/vue3-recommended'],
            parserOptions: {
                parser: '@typescript-eslint/parser'
            },
            rules: {
                'vue/html-indent': ['error', 2],
                'vue/max-attributes-per-line': 'off',
                'vue/singleline-html-element-content-newline': 'off',
                'vue/multi-word-component-names': 'off',
                // TypeScript's own checker (vue-tsc, run by DWC 3.7's builder)
                // reports undefined names; ESLint's scope analysis does not
                // understand type-only syntax and false-positives on it.
                'no-undef': 'off',
                'no-unused-vars': 'off'
            }
        }
    ]
};
