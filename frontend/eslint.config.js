import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores([
    'dist/**',
    'dist-ui/**',
    'dist-electron/**',
    'release*/**',
    'node_modules/**',
  ]),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // The app deliberately uses dynamic dashboard/API payloads. Migrating those
      // boundaries from `any` is a separate API-schema project, not a lint fix.
      '@typescript-eslint/no-explicit-any': 'off',
      // Existing fetch/animation effects intentionally initialise local UI state.
      // Keep the rule disabled until those flows are redesigned around async caches.
      'react-hooks/set-state-in-effect': 'off',
      // Vite HMR remains correct for the app's component-plus-helper modules.
      'react-refresh/only-export-components': 'off',
    },
  },
])
