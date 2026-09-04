import { execSync } from 'node:child_process';
import { existsSync, globSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const componentsRoot = join(__dirname, '..');
const appRoot = join(componentsRoot, '..', '..', '..', '..');
const targetCardScssPath = join(componentsRoot, '_target-card.scss');
const indexScssPath = join(componentsRoot, 'index.scss');

describe('E15-25 slice 3: target-card stylesheet', () => {
  it('registers target-card in components index.scss', () => {
    const indexScss = readFileSync(indexScssPath, 'utf8');
    expect(indexScss).toMatch(/@use\s+['"]\.\/target-card['"]/);
  });

  it('defines token-based active and health chip styles', () => {
    expect(existsSync(targetCardScssPath)).toBe(true);
    const source = readFileSync(targetCardScssPath, 'utf8');

    expect(source).toContain('&--active');
    expect(source).toContain('&--reachable');
    expect(source).toContain('var(--acx-color-accent)');
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it('ships target-card rules in the production admin CSS bundle', () => {
    // FEBT1-GATE-04: public/assets/dist is a gitignored build output, so this assertion is
    // only meaningful against a bundle emitted from the tree under test. Pin the build
    // boundary so a missing or stale artifact fails as a build problem instead of passing
    // on someone else's leftover CSS.
    const buildStartedAt = Date.now();
    execSync('npm run build', { cwd: appRoot, stdio: 'pipe' });
    const cssFiles = globSync(join(appRoot, 'public/assets/dist/assets/*.css'));
    expect(cssFiles.length).toBeGreaterThan(0);

    const freshCssFiles = cssFiles.filter((filePath) => statSync(filePath).mtimeMs >= buildStartedAt - 1000);
    expect(freshCssFiles).not.toHaveLength(0);

    const combined = freshCssFiles.map((filePath) => readFileSync(filePath, 'utf8')).join('\n');

    expect(combined).toContain('.acx-target-card--active');
    expect(combined).toContain('.acx-target-card__health');
  }, 120_000);
});