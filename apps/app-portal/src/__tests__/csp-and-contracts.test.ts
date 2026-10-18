import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const portalRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

function walkSource(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];
  for (const entry of entries) {
    if (entry === '__tests__' || entry === 'dist' || entry === 'node_modules') {
      continue;
    }
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...walkSource(full));
    } else if (/\.(ts|tsx|css|html)$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

describe('production CSP artifact and source contracts', () => {
  it('documents Clerk production CSP without unsafe script or fake nonces', () => {
    const csp = readFileSync(join(portalRoot, 'csp', 'production.csp'), 'utf8');
    const collapsed = csp.replace(/\s+/g, ' ');

    expect(collapsed).toMatch(/default-src 'self'/);
    expect(collapsed).toMatch(/base-uri 'self'/);
    expect(collapsed).toMatch(/object-src 'none'/);
    expect(collapsed).toMatch(/frame-ancestors 'none'/);
    expect(collapsed).toMatch(/script-src[^;]*'self'[^;]*https:\/\/clerk\.altcontext\.com/);
    expect(collapsed).toMatch(/script-src[^;]*https:\/\/challenges\.cloudflare\.com/);
    expect(collapsed).toMatch(/script-src[^;]*https:\/\/\*\.protect\.clerk\.com/);
    expect(collapsed).toMatch(/connect-src[^;]*'self'[^;]*https:\/\/clerk\.altcontext\.com/);
    expect(collapsed).toMatch(/connect-src[^;]*https:\/\/\*\.protect\.clerk\.com:\*/);
    expect(collapsed).toMatch(/img-src[^;]*https:\/\/img\.clerk\.com/);
    expect(collapsed).toMatch(/worker-src 'self' blob:/);
    expect(collapsed).toMatch(/style-src[^;]*'self'[^;]*'unsafe-inline'/);
    expect(collapsed).toMatch(/frame-src[^;]*https:\/\/challenges\.cloudflare\.com/);
    expect(collapsed).toMatch(/form-action[^;]*'self'/);

    const scriptSources = (collapsed.match(/script-src ([^;]+)/)?.[1] ?? '').split(/\s+/);
    expect(scriptSources).not.toContain("'unsafe-inline'");
    expect(scriptSources).not.toContain("'unsafe-eval'");
    expect(scriptSources).not.toContain('https:');
    expect(scriptSources).not.toContain('http:');
    expect(scriptSources).not.toContain('*');
    expect(collapsed).not.toMatch(/nonce-/);
    const formSources = (collapsed.match(/form-action ([^;]+)/)?.[1] ?? '').split(/\s+/);
    expect(formSources).not.toContain('*');
    expect(formSources).not.toContain('https:');
  });

  it('keeps production source on @clerk/react without secret keys or homemade passwords', () => {
    const appSource = readFileSync(join(portalRoot, 'src', 'App.tsx'), 'utf8');
    expect(appSource).toMatch(/from '@clerk\/react'/);
    expect(appSource).toMatch(/ClerkProvider/);
    expect(appSource).toMatch(/<SignIn/);
    expect(appSource).toMatch(/<SignUp/);
    expect(appSource).toMatch(/UserButton/);
    expect(appSource).toMatch(/useAuth/);

    const files = walkSource(join(portalRoot, 'src'));
    const combined = files.map((file) => readFileSync(file, 'utf8')).join('\n');
    expect(combined).not.toMatch(/OrganizationSwitcher/);
    expect(combined).not.toMatch(/CLERK_SECRET_KEY/);
    expect(combined).not.toMatch(/type=["']password["']/);
    expect(combined).not.toMatch(/localStorage/);
    expect(combined).not.toMatch(/@clerk\/nextjs/);
    expect(combined).not.toMatch(/@clerk\/clerk-react/);
  });
});
