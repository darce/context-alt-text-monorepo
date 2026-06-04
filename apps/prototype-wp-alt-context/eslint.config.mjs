import js from '@eslint/js';
import reactPlugin from 'eslint-plugin-react';
import reactHooksPlugin from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';
import queryPlugin from '@tanstack/eslint-plugin-query';

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
