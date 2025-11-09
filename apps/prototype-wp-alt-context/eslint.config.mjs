import { defineFlatConfig } from 'eslint/config';
import js from '@eslint/js';
import reactPlugin from 'eslint-plugin-react';
import reactHooksPlugin from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

const sharedFiles = ['js/**/*.{ts,tsx}', '.storybook/**/*.{ts,tsx}'];
const typeCheckedConfigs = [...tseslint.configs.recommendedTypeChecked, ...tseslint.configs.stylisticTypeChecked];

export default defineFlatConfig([
  {
    ignores: ['node_modules/**', 'public/**', 'vendor/**', 'storybook-static/**'],
  },
  js.configs.recommended,
  ...typeCheckedConfigs.map((config) => ({
    ...config,
    files: sharedFiles,
    languageOptions: {
      ...config.languageOptions,
      parserOptions: {
        ...config.languageOptions?.parserOptions,
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  })),
  {
    files: sharedFiles,
    plugins: {
      react: reactPlugin,
      'react-hooks': reactHooksPlugin,
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
      'max-lines': [
        'warn',
        {
          max: 350,
          skipBlankLines: true,
          skipComments: true,
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'JSXElement[openingElement.name.name="select"]',
          message:
            'Use @radix-ui/react-select instead of native <select>. See docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md',
        },
        {
          selector: 'JSXElement[openingElement.name.name="dialog"]',
          message:
            'Use @radix-ui/react-dialog instead of native <dialog>. See docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md',
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
            'Use TypeScript (.ts/.tsx) for new modules in js/. Request an exception in docs/architecture/rules if required.',
        },
      ],
    },
  },
]);
