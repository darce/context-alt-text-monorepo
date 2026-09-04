import { execSync } from 'node:child_process';
import { existsSync, globSync, readFileSync, statSync } from 'node:fs';
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
    expect(source).toContain('appearance: none');
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it('includes focus-visible ring for keyboard users', () => {
    const source = readFileSync(radioGroupScssPath, 'utf8');

    expect(source).toMatch(/:focus-visible/);
  });

  it('ships radio-group rules in the production admin CSS bundle', () => {
    // FEBT1-GATE-04: this assertion is only meaningful against a bundle built from the
    // tree under test. Pin the build boundary so a missing or stale artifact fails as a
    // build problem instead of masquerading as a source regression (or a green pass).
    const buildStartedAt = Date.now();
    execSync('npm run build', { cwd: appRoot, stdio: 'pipe' });
    const cssFiles = globSync(join(appRoot, 'public/assets/dist/assets/*.css'));
    expect(cssFiles.length).toBeGreaterThan(0);

    const freshCssFiles = cssFiles.filter((filePath) => statSync(filePath).mtimeMs >= buildStartedAt - 1000);
    expect(freshCssFiles).not.toHaveLength(0);

    const combined = freshCssFiles.map((filePath) => readFileSync(filePath, 'utf8')).join('\n');

    expect(combined).toContain('.acx-radio-group__item');
    expect(combined).toContain('.acx-radio-group__indicator');
    expect(combined).toMatch(/data-state=.?checked/);
  }, 120_000);
});
