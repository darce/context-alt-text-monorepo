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
            'react-hooks/exhaustive-deps': 'warn',
            
            // Architecture enforcement: file size limits
            'max-lines': [
                'warn',
                {
                    max: 300,
                    skipBlankLines: true,
                    skipComments: true
                }
            ],
            
            // Architecture enforcement: prevent native HTML elements (use Radix UI)
            'no-restricted-syntax': [
                'error',
                {
                    selector: 'JSXElement[openingElement.name.name="select"]',
                    message: 'Use @radix-ui/react-select instead of native <select>. See docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md'
                },
                {
                    selector: 'JSXElement[openingElement.name.name="dialog"]',
                    message: 'Use @radix-ui/react-dialog instead of native <dialog>. See docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md'
                },
                {
                    selector: 'JSXElement[openingElement.name.name="input"][openingElement.attributes[0].name.name="type"][openingElement.attributes[0].value.value="checkbox"]',
                    message: 'Use @radix-ui/react-checkbox instead of native checkbox input. See docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md'
                },
                {
                    selector: 'JSXElement[openingElement.name.name="input"][openingElement.attributes[0].name.name="type"][openingElement.attributes[0].value.value="radio"]',
                    message: 'Use @radix-ui/react-radio-group instead of native radio input. See docs/architecture/rules/RADIX_UI_COMPONENT_GUIDE.md'
                }
            ]
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
