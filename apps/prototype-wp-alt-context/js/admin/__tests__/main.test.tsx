/**
 * Bootstrap shim/observability contract for `main.tsx` (FEBT1G-L-14).
 *
 * The missing-globals warning is the only signal that the plugin loaded without
 * `wp` / `wp.hooks`. `ensureWordPressGlobalShims` creates both, so the check has
 * to observe the page state BEFORE the shim runs — otherwise the predicate is a
 * lying predicate and both warning branches are unreachable dead code.
 *
 * Assertions read the console sink rather than `setLogSink`: `vi.resetModules()`
 * gives the re-imported `main` its own copy of the logger module, so a sink
 * installed from this file would never see the bootstrap's records.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-dom/client', () => ({
  createRoot: () => ({ render: () => undefined, unmount: () => undefined }),
}));

vi.mock('../App', () => ({ App: () => null }));

type WindowWithWp = typeof window & { wp?: { hooks?: unknown; svgPainter?: unknown } };

const warnCalls: unknown[][] = [];
let originalWarn: typeof console.warn;

const bootstrap = async (): Promise<void> => {
  vi.resetModules();
  await import('../main');
};

const missingGlobalsWarnings = (): { message: string; fields: Record<string, unknown> }[] =>
  warnCalls
    .filter((call) => typeof call[0] === 'string' && call[0].includes('Missing WordPress globals'))
    .map((call) => ({ message: call[0] as string, fields: (call[1] ?? {}) as Record<string, unknown> }));

beforeEach(() => {
  warnCalls.length = 0;
  originalWarn = console.warn;
  console.warn = (...args: unknown[]): void => {
    warnCalls.push(args);
  };
  document.body.innerHTML = '<div id="alt-context-admin-app" hidden></div>';
  delete (window as WindowWithWp).wp;
});

afterEach(() => {
  console.warn = originalWarn;
  delete (window as WindowWithWp).wp;
});

describe('admin bootstrap WordPress global shims', () => {
  it('warns that `wp` was missing even though the shim then supplies it [FEBT1G-L-14]', async () => {
    await bootstrap();

    const warnings = missingGlobalsWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0].fields.missingGlobals).toEqual(['wp']);
    // The shim still ran: the warning reports what the page loaded, not what we supplied.
    expect((window as WindowWithWp).wp?.hooks).toBeTruthy();
  });

  it('warns that `wp.hooks` was missing when only `wp` was present [FEBT1G-L-14]', async () => {
    (window as WindowWithWp).wp = {};

    await bootstrap();

    const warnings = missingGlobalsWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0].fields.missingGlobals).toEqual(['wp.hooks']);
  });

  it('stays silent when WordPress supplied both globals', async () => {
    (window as WindowWithWp).wp = { hooks: { doAction: () => undefined } };

    await bootstrap();

    expect(missingGlobalsWarnings()).toHaveLength(0);
  });

  it('correlates the bootstrap warning with a requestId [OBS-03]', async () => {
    await bootstrap();

    const [warning] = missingGlobalsWarnings();
    expect(typeof warning.fields.requestId).toBe('string');
    expect(warning.fields.requestId).not.toBe('');
  });
});
