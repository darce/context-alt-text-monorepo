import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const stylesPath = join(dirname(fileURLToPath(import.meta.url)), '..', 'styles.css');

function getDeclarations(stylesheet: string, selector: RegExp): string {
  const rule = stylesheet.match(new RegExp(`${selector.source}\\s*\\{([^}]*)\\}`));
  if (!rule) throw new Error(`Missing CSS rule for ${selector}`);
  return rule[1];
}

function getDeclaration(rule: string, property: string): string {
  const declaration = rule.match(new RegExp(`(?:^|\\n)\\s*${property}\\s*:\\s*([^;]+);`));
  if (!declaration) throw new Error(`Missing ${property} declaration`);
  return declaration[1].trim();
}

function getHexColor(value: string, variables: Map<string, string>): string {
  const variable = /^var\((--[\w-]+)\)$/.exec(value);
  if (variable) {
    const resolved = variables.get(variable[1]);
    if (!resolved) throw new Error(`Missing CSS variable ${variable[1]}`);
    return getHexColor(resolved, variables);
  }
  if (/^#[\da-f]{6}$/i.test(value)) return value;
  throw new Error(`Unsupported color value: ${value}`);
}

function luminance(hex: string): number {
  const channels = hex.slice(1).match(/../g);
  if (!channels) throw new Error(`Invalid hex color: ${hex}`);
  const [red, green, blue] = channels.map((channel) => {
    const srgb = Number.parseInt(channel, 16) / 255;
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(first: string, second: string): number {
  const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

describe('ADVFIX-1 form-control border contrast', () => {
  it('gives enabled controls a 3:1 boundary against their fill and page surface', () => {
    const stylesheet = readFileSync(stylesPath, 'utf8');
    const root = getDeclarations(stylesheet, /:root/);
    const variables = new Map<string, string>();
    for (const [, name, value] of root.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      variables.set(name, value.trim());
    }
    const controls = getDeclarations(stylesheet, /input,\s*select,\s*textarea/);
    const borderColorValue = getDeclaration(controls, 'border').split(/\s+/).pop();
    if (!borderColorValue) throw new Error('Missing form-control border color');
    const borderColor = getHexColor(borderColorValue, variables);
    const controlFill = getHexColor(getDeclaration(controls, 'background'), variables);
    const pageSurface = getHexColor('var(--acx-color-surface)', variables);

    expect(contrastRatio(borderColor, controlFill)).toBeGreaterThanOrEqual(3);
    expect(contrastRatio(borderColor, pageSurface)).toBeGreaterThanOrEqual(3);
  });
});
