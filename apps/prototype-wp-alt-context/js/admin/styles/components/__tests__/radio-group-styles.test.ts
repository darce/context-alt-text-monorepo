import { execSync } from 'node:child_process';
import { existsSync, globSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const componentsRoot = join(__dirname, '..');
const appRoot = join(componentsRoot, '..', '..', '..', '..');
const radioGroupScssPath = join(componentsRoot, '_radio-group.scss');
const indexScssPath = join(componentsRoot, 'index.scss');

describe('E15-25 slice 1: radio-group stylesheet', () => {
  it('registers radio-group in components index.scss', () => {
    const indexScss = readFileSync(indexScssPath, 'utf8');

    expect(indexScss).toMatch(/@use\s+['"]\.\/radio-group['"]/);
  });

  it('defines token-based radio item and checked indicator styles', () => {
    expect(existsSync(radioGroupScssPath)).toBe(true);
    const source = readFileSync(radioGroupScssPath, 'utf8');

    expect(source).toContain('.acx-radio-group__item');
    expect(source).toContain('.acx-radio-group__indicator');
    expect(source).toMatch(/data-state=['"]checked['"]/);
    expect(source).toContain('var(--acx-color-border)');
    expect(source).toContain('var(--acx-color-accent)');
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it('includes focus-visible ring for keyboard users', () => {
    const source = readFileSync(radioGroupScssPath, 'utf8');

    expect(source).toMatch(/:focus-visible/);
  });

  it('ships radio-group rules in the production admin CSS bundle', () => {
    execSync('npm run build', { cwd: appRoot, stdio: 'pipe' });
    const cssFiles = globSync(join(appRoot, 'public/assets/dist/assets/*.css'));
    const combined = cssFiles.map((filePath) => readFileSync(filePath, 'utf8')).join('\n');

    expect(combined.match(/acx-radio-group/g)?.length ?? 0).toBeGreaterThan(0);
  }, 120_000);
});
