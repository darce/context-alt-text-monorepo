import js from '@eslint/js';
import reactPlugin from 'eslint-plugin-react';
import reactHooksPlugin from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

const typedExtends = [
    ...tseslint.configs.recommendedTypeChecked,
    ...tseslint.configs.stylisticTypeChecked
];

export default tseslint.config(
    {
        ignores: ['node_modules/**', 'public/**', 'vendor/**', 'storybook-static/**']
    },
    js.configs.recommended,
    {
        files: ['js/**/*.{ts,tsx}', '.storybook/**/*.{ts,tsx}'],
        extends: typedExtends,
        languageOptions: {
            parserOptions: {
                projectService: true,
                tsconfigRootDir: import.meta.dirname
            }
        },
        plugins: {
            react: reactPlugin,
            'react-hooks': reactHooksPlugin
        },
        settings: {
            react: {
                version: 'detect'
            }
        },
        rules: {
            'func-style': ['error', 'expression', { allowArrowFunctions: true }],
            'react-hooks/rules-of-hooks': 'error',
            'react-hooks/exhaustive-deps': 'warn'
        }
    },
    {
        files: ['js/**/*.{js,jsx}'],
        rules: {
            'no-restricted-syntax': [
                'error',
                {
                    selector: 'Program',
                    message: 'Use TypeScript (.ts/.tsx) for new modules in js/. Request an exception in docs/architecture/rules if required.'
                }
            ]
        }
    }
);
