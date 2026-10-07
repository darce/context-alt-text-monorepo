// @vitest-environment node
// Importing Vite loads esbuild, which requires TextEncoder and Uint8Array from the same realm.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resolvePortalProxyTarget } from '../devProxy';

beforeEach(() => {
  vi.stubEnv('PORTAL_API_PROXY_TARGET', undefined);
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('Vite development server', () => {
  it('uses port 5173 to match the authorized browser origin', async () => {
    const { default: viteConfig } = await import('../../vite.config');
    expect(viteConfig.server?.port).toBe(5173);
  });

  it('fails when the authorized port is occupied', async () => {
    const { default: viteConfig } = await import('../../vite.config');
    expect(viteConfig.server?.strictPort).toBe(true);
  });
});

describe('resolvePortalProxyTarget', () => {
  it('uses the local API default when the value is unset or blank', () => {
    expect(resolvePortalProxyTarget(undefined)).toBe('http://127.0.0.1:8000');
    expect(resolvePortalProxyTarget('  ')).toBe('http://127.0.0.1:8000');
  });

  it('allows HTTP loopback targets with and without ports', () => {
    expect(resolvePortalProxyTarget('http://127.0.0.1')).toBe('http://127.0.0.1');
    expect(resolvePortalProxyTarget('http://127.0.0.1:9000')).toBe('http://127.0.0.1:9000');
    expect(resolvePortalProxyTarget('http://localhost')).toBe('http://localhost');
    expect(resolvePortalProxyTarget('http://localhost:9000')).toBe('http://localhost:9000');
    expect(resolvePortalProxyTarget('http://[::1]')).toBe('http://[::1]');
    expect(resolvePortalProxyTarget('http://[::1]:9000')).toBe('http://[::1]:9000');
  });

  it('allows an HTTPS development host and removes a trailing slash', () => {
    expect(resolvePortalProxyTarget('https://dev.api.altcontext.com')).toBe(
      'https://dev.api.altcontext.com',
    );
    expect(resolvePortalProxyTarget('https://dev.api.altcontext.com:8443/')).toBe(
      'https://dev.api.altcontext.com:8443',
    );
  });

  it.each([
    'http://dev.api.altcontext.com',
    'https://user:password@dev.api.altcontext.com',
    'https://dev.api.altcontext.com/portal',
    'https://dev.api.altcontext.com?env=dev',
    'https://dev.api.altcontext.com?',
    'https://dev.api.altcontext.com#portal',
    'https://dev.api.altcontext.com#',
    'ftp://dev.api.altcontext.com',
    'javascript:alert(1)',
  ])('rejects unsafe target %s and names the setting', (target) => {
    expect(() => resolvePortalProxyTarget(target)).toThrow(/PORTAL_API_PROXY_TARGET/);
  });

  it('configures the Vite /portal proxy with the default target when unset', async () => {
    const { default: viteConfig } = await import('../../vite.config');
    const proxy = viteConfig.server?.proxy as
      | Record<string, { target?: string; changeOrigin?: boolean; secure?: boolean }>
      | undefined;
    expect(proxy?.['/portal']?.target).toBe('http://127.0.0.1:8000');
    expect(proxy?.['/portal']?.changeOrigin).toBe(true);
    expect(proxy?.['/portal']?.secure).toBe(true);
  });

  it('configures the Vite /portal proxy with an HTTPS target override', async () => {
    vi.stubEnv('PORTAL_API_PROXY_TARGET', 'https://dev.api.altcontext.com');
    const { default: viteConfig } = await import('../../vite.config');
    const proxy = viteConfig.server?.proxy as
      | Record<string, { target?: string; changeOrigin?: boolean; secure?: boolean }>
      | undefined;
    expect(proxy?.['/portal']?.target).toBe('https://dev.api.altcontext.com');
    expect(proxy?.['/portal']?.changeOrigin).toBe(true);
    expect(proxy?.['/portal']?.secure).toBe(true);
  });
});
