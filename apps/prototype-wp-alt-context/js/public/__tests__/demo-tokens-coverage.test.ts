// @vitest-environment node

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as sass from 'sass';

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const tokenStylesheetPath = path.join(pluginRoot, 'js/public/demo-tokens.scss');
const demoStylesheetPath = path.join(pluginRoot, 'js/public/demo-describe.css');
const shortcodePath = path.join(pluginRoot, 'src/public/class-public-demo-shortcode.php');
const viteConfigPath = path.join(pluginRoot, 'vite.config.ts');

function findCustomProperties(css: string, pattern: RegExp): Set<string> {
  return new Set(Array.from(css.matchAll(pattern), (match) => match[1]));
}

describe('public demo design tokens', () => {
  it('declares every token referenced by the public demo stylesheet', () => {
    const compiledTokens = sass.compile(tokenStylesheetPath).css;
    const demoStylesheet = readFileSync(demoStylesheetPath, 'utf8');
    const declaredTokens = findCustomProperties(compiledTokens, /(--acx-[\w-]+)\s*:/g);
    const referencedTokens = findCustomProperties(demoStylesheet, /var\(\s*(--acx-[\w-]+)/g);
    const missingTokens = Array.from(referencedTokens).filter((token) => !declaredTokens.has(token)).sort();

    expect(referencedTokens.size).toBeGreaterThan(0);
    expect(
      missingTokens,
      `demo-describe.css references tokens not declared by demo-tokens.scss: ${missingTokens.join(', ')}`
    ).toEqual([]);
  });

  it('lists the PHP token entry point as a Vite rollup input', () => {
    const shortcode = readFileSync(shortcodePath, 'utf8');
    const entryPoint = shortcode.match(/private const TOKEN_ENTRY_POINT\s*=\s*'([^']+)'/u)?.[1];
    const viteConfig = readFileSync(viteConfigPath, 'utf8');
    const rollupInput = viteConfig.match(/rollupOptions:\s*\{\s*input:\s*\{([\s\S]*?)\n\s*\},/u)?.[1];

    expect(entryPoint, 'PublicDemoShortcode must define TOKEN_ENTRY_POINT').toBeTruthy();
    expect(rollupInput, 'vite.config.ts must define rollupOptions.input').toBeTruthy();
    expect(rollupInput).toContain(`path.resolve(__dirname, '${entryPoint}')`);
  });
});
