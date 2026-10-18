import js from '@eslint/js';
import reactPlugin from 'eslint-plugin-react';
import reactHooksPlugin from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';
import queryPlugin from '@tanstack/eslint-plugin-query';
import importXPlugin, { createNodeResolver } from 'eslint-plugin-import-x';

const sharedFiles = [
  'js/**/*.{ts,tsx}',
  'tests/e2e/**/*.ts',
  'playwright.config.ts',
  '.storybook/**/*.{ts,tsx}',
];

export default tseslint.config(
  {
    ignores: ['node_modules/**', 'public/**', 'vendor/**', 'storybook-static/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked.map((config) => ({
    ...config,
    files: sharedFiles,
  })),
  ...tseslint.configs.stylisticTypeChecked.map((config) => ({
    ...config,
    files: sharedFiles,
  })),
  {
    files: sharedFiles,
    languageOptions: {
      parserOptions: {
        project: './tsconfig.type-check.json',
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      react: reactPlugin,
      'react-hooks': reactHooksPlugin,
      '@tanstack/query': queryPlugin,
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
    rules: {
      quotes: ['error', 'single', { avoidEscape: true }],
      'func-style': ['error', 'expression', { allowArrowFunctions: true }],
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@tanstack/query/exhaustive-deps': 'error',
      '@tanstack/query/no-unstable-deps': 'error',
      '@tanstack/query/stable-query-client': 'error',
    },
  },
  /**
   * FEBT2 X-LANE-01: static enforcement for the import cycle that
   * `js/admin/utils/errorTaxonomy.ts` was extracted to break.
   *
   * The historical cycle was `api/config -> utils/logger -> utils/appError ->
   * utils/http -> api/config`. Its closing edge left `utils/`, so a
   * `js/admin/utils/**`-only scope would not have caught it: the rule must also
   * see `js/admin/api/**` for the back-edge to be inside the linted graph
   * (GRPH-02 — a cycle is one indivisible unit; you cannot lint half of it).
   *
   * `maxDepth: Infinity` is pinned explicitly because the real cycle was 4 hops
   * and any bounded default would report clean on the exact regression this
   * rule exists to catch (RLSE-05 / TEST-15 — a check that cannot go red
   * certifies nothing). `allowUnsafeDynamicCyclicDependency: false` keeps a
   * `await import()` from being an escape hatch that re-closes the cycle at
   * runtime, which is the only place an ESM TDZ failure is observable at all.
   */
  {
    files: ['js/admin/utils/**/*.{ts,tsx}', 'js/admin/api/**/*.{ts,tsx}'],
    plugins: {
      'import-x': importXPlugin,
    },
    settings: {
      // `import-x/resolver-next` (the v4 resolver API), not the legacy
      // `import-x/resolver` map: the legacy map needs a separately installed
      // `eslint-import-resolver-node`, and when it is missing import-x resolves
      // nothing and `no-cycle` reports clean on a real cycle. A lint rule that
      // silently no-ops is worse than no rule (RLSE-05) — this exact
      // misconfiguration was caught by the mutation check below, not by review.
      'import-x/resolver-next': [
        createNodeResolver({
          extensions: ['.ts', '.tsx', '.js', '.jsx', '.mjs'],
        }),
      ],
      // Without this map import-x cannot PARSE a resolved `.ts` dependency, so
      // its export map comes back null and the traversal stops at hop 1 —
      // `no-cycle` then reports clean on a genuine cycle. Resolution and parsing
      // are two separate failure modes and both fail silently.
      'import-x/parsers': {
        '@typescript-eslint/parser': ['.ts', '.tsx'],
      },
      'import-x/extensions': ['.ts', '.tsx', '.js', '.jsx', '.mjs'],
    },
    rules: {
      'import-x/no-cycle': [
        'error',
        {
          maxDepth: Infinity,
          allowUnsafeDynamicCyclicDependency: false,
        },
      ],
    },
  },
  {
    files: ['js/**/*.{js,jsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Program',
          message:
            'Use TypeScript (.ts/.tsx) for new modules in js/. Request an exception in docs/agentic/rules if required.'
        },
      ],
    },
  },
);
