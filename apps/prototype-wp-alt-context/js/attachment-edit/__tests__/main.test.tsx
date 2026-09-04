/**
 * Entry-point contract for the SECOND production bundle (`vite.config.ts:17`,
 * `src/admin/class-admin.php:55`). FEBT2-LG-NEW-01.
 *
 * `AttachmentFacesApp.test.tsx` already pins three `mountAttachmentEdit` branches
 * (container absent, attachmentId zero, success mount). This file owns the two that
 * nothing exercised — the localized-config guards — plus the module-scope auto-mount
 * on line 88, which every importer runs and no assertion ever looked at.
 *
 * The guards used to `return false` in silence. On post.php the container is already
 * on the page when they fire, so the user gets an empty box and the operator gets
 * nothing at all: not a crash, not a log line (RLSE-05). Each guard now warns, and
 * these tests are the reason a future edit cannot quietly delete that warning.
 *
 * Assertions read `console.warn` rather than `setLogSink`: `vi.resetModules()` gives
 * the re-imported entry its own copy of the logger module, so a sink installed here
 * would never see the bootstrap's records (same reason as `js/admin/__tests__/main.test.tsx`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache, type AttachmentEditLocalizedConfig } from '../../admin/api/config';
import { mountAttachmentEdit } from '../main';

const renderSpy = vi.fn();
// createRoot's ARGUMENT is the assertion that matters, not just that it was called:
// `createRoot(doc.body)` renders the panel outside the container PHP reserved for it and
// survives every "did it render" check (mutant LG1-M1).
const createRootSpy = vi.fn();
vi.mock('react-dom/client', () => ({
  createRoot: (element: Element) => {
    createRootSpy(element);
    return { render: renderSpy, unmount: () => undefined };
  },
}));

// post.php is never a page whose only div is ours. The decoy makes "first div on the page"
// a different element from the container, so a positional mount cannot pass by accident.
const CONTAINER_HTML =
  '<div id="acx-decoy-postbox"></div><div id="acx-attachment-faces" hidden></div>';
const NONCE = 'a1b2c3d4e5f6';

const validPayload = (): AttachmentEditLocalizedConfig => ({
  nonce: NONCE,
  ajaxUrl: '/wp-admin/admin-ajax.php',
  attachmentId: 7,
  imageUrl: 'https://example.test/img.jpg',
  imageWidth: 100,
  imageHeight: 80,
  workbenchUrl: 'https://example.test/workbench',
  endpoints: { recognitionMediaIdentities: 'https://example.test/wp-json/acx/v1/recognition/media-identities' },
});

const warnCalls: unknown[][] = [];
const debugCalls: unknown[][] = [];
let originalWarn: typeof console.warn;
let originalDebug: typeof console.debug;

interface LogLine {
  message: string;
  fields: Record<string, unknown>;
}

const bootstrapLines = (calls: unknown[][]): LogLine[] =>
  calls
    .filter((call) => typeof call[0] === 'string' && call[0].startsWith('[alt-context/attachment-edit.bootstrap]'))
    .map((call) => ({ message: call[0] as string, fields: (call[1] ?? {}) as Record<string, unknown> }));

const bootstrapWarnings = (): LogLine[] => bootstrapLines(warnCalls);
const bootstrapDebug = (): LogLine[] => bootstrapLines(debugCalls);

const container = (): HTMLElement | null => document.getElementById('acx-attachment-faces');

beforeEach(() => {
  warnCalls.length = 0;
  debugCalls.length = 0;
  renderSpy.mockClear();
  createRootSpy.mockClear();
  originalWarn = console.warn;
  originalDebug = console.debug;
  console.warn = (...args: unknown[]): void => {
    warnCalls.push(args);
  };
  console.debug = (...args: unknown[]): void => {
    debugCalls.push(args);
  };
  resetConfigCache();
  delete window.AltContextAttachmentEdit;
  document.body.innerHTML = CONTAINER_HTML;
});

afterEach(() => {
  console.warn = originalWarn;
  console.debug = originalDebug;
  resetConfigCache();
  delete window.AltContextAttachmentEdit;
  document.body.innerHTML = '';
});

describe('mountAttachmentEdit localized-config guards [FEBT2-LG-NEW-01]', () => {
  it.each([
    ['nonce', { nonce: '' }],
    ['ajaxUrl', { ajaxUrl: '' }],
    ['endpoints', { endpoints: undefined as unknown as Record<string, string> }],
  ])('refuses to mount and names %s as the missing key', (key, override) => {
    const payload = { ...validPayload(), ...override };

    expect(mountAttachmentEdit(document, payload)).toBe(false);

    expect(createRootSpy).not.toHaveBeenCalled();
    expect(renderSpy).not.toHaveBeenCalled();
    // Reveal contract: a container that never mounted must stay hidden.
    expect(container()?.hasAttribute('hidden')).toBe(true);

    const warnings = bootstrapWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0].message).toContain('incomplete localized config');
    expect(warnings[0].fields.missingConfigKeys).toEqual([key]);
  });

  it('reports every missing key at once when PHP localized nothing', () => {
    expect(mountAttachmentEdit(document, undefined)).toBe(false);

    const warnings = bootstrapWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0].fields.missingConfigKeys).toEqual(['nonce', 'ajaxUrl', 'endpoints']);
  });

  it('correlates the refusal with a requestId [OBS-03]', () => {
    mountAttachmentEdit(document, undefined);

    expect(bootstrapWarnings()[0].fields.requestId).toEqual(expect.any(String));
  });

  it('never puts the nonce into the log record', () => {
    mountAttachmentEdit(document, { ...validPayload(), ajaxUrl: '' });

    expect(JSON.stringify(bootstrapWarnings())).not.toContain(NONCE);
  });

  it.each([
    ['zero', 0],
    ['a non-numeric string', 'not-an-id'],
    ['negative', -3],
  ])('refuses to mount and reports the type when attachmentId is %s', (_label, attachmentId) => {
    expect(
      mountAttachmentEdit(document, { ...validPayload(), attachmentId }),
    ).toBe(false);

    expect(renderSpy).not.toHaveBeenCalled();
    expect(container()?.hasAttribute('hidden')).toBe(true);

    const warnings = bootstrapWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0].message).toContain('attachmentId is not a positive integer');
    expect(warnings[0].fields.attachmentIdType).toBe(typeof attachmentId);
  });

  it('records the container-absent no-op at debug, never at warn [RLSE-04 / OBS-04 / OBS-08]', () => {
    document.body.innerHTML = '';

    expect(mountAttachmentEdit(document, validPayload())).toBe(false);

    // Observable: a branch that returns in total silence cannot be told apart from
    // "the bundle never loaded" (OBS-08).
    const debugLines = bootstrapDebug();
    expect(debugLines).toHaveLength(1);
    expect(debugLines[0].message).toContain('no container on this screen');
    expect(debugLines[0].fields.requestId).toEqual(expect.any(String));
    // But NOT at warn: this fires on every media-modal open, and an alarm that
    // demands no action trains operators past the real ones (OBS-04).
    expect(bootstrapWarnings()).toHaveLength(0);
    expect(createRootSpy).not.toHaveBeenCalled();
    expect(renderSpy).not.toHaveBeenCalled();
  });

  it('mounts into #acx-attachment-faces — not the body — and reveals it', () => {
    expect(mountAttachmentEdit(document, validPayload())).toBe(true);

    expect(createRootSpy).toHaveBeenCalledTimes(1);
    expect(createRootSpy).toHaveBeenCalledWith(container());
    expect(createRootSpy).not.toHaveBeenCalledWith(document.body);
    expect(renderSpy).toHaveBeenCalledTimes(1);
    expect(container()?.hasAttribute('hidden')).toBe(false);
    expect(bootstrapWarnings()).toHaveLength(0);
    // The success path is not a refusal: it must not emit the no-container record either.
    expect(bootstrapDebug()).toHaveLength(0);
  });
});

describe('module-scope auto-mount [FEBT2-LG-NEW-01]', () => {
  const bootstrap = async (): Promise<void> => {
    vi.resetModules();
    await import('../main');
  };

  it('mounts the faces panel on import — nothing else on post.php calls the mount', async () => {
    window.AltContextAttachmentEdit = validPayload();

    await bootstrap();

    expect(renderSpy).toHaveBeenCalledTimes(1);
    expect(createRootSpy).toHaveBeenCalledWith(container());
    expect(container()?.hasAttribute('hidden')).toBe(false);
  });

  it('reads the live window payload, so a payload set after load is not silently used', async () => {
    delete window.AltContextAttachmentEdit;

    await bootstrap();

    expect(renderSpy).not.toHaveBeenCalled();
    expect(container()?.hasAttribute('hidden')).toBe(true);
    expect(bootstrapWarnings()).toHaveLength(1);
  });

  it('importing the entry on a page without the container neither throws nor warns', async () => {
    document.body.innerHTML = '';
    window.AltContextAttachmentEdit = validPayload();

    await expect(bootstrap()).resolves.toBeUndefined();

    expect(renderSpy).not.toHaveBeenCalled();
    expect(bootstrapWarnings()).toHaveLength(0);
    // The auto-mount still ran and still left a trace — this is what distinguishes
    // "loaded on the media modal" from "the bundle failed to load at all" (OBS-08).
    expect(bootstrapDebug()).toHaveLength(1);
  });
});
