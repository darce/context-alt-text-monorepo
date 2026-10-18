/**
 * Single-owner guard for the auth-expiry copy on the post.php surface (FEBT2-LC-NEW-01,
 * prior UXP-NET-2 #4846 / #4849).
 *
 * The literal used to exist three times: `sessionExpiredCopy.ts`, `UserFacingErrorNotice.tsx`
 * and here. Two of those were collapsed already; this file closes the third and — more
 * importantly — makes re-opening it red. Asserting only `A === B` would be tautological
 * (TEST-06) because a re-pasted literal satisfies it, so the discriminating checks are the
 * mocked-owner test (proves the value is *read*, not copied) and the source-text test
 * (proves no literal crept back in).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { SPA_SESSION_EXPIRED_COPY } from '../../admin/utils/sessionExpiredCopy';
import { ATTACHMENT_EDIT_COPY } from '../copy';

const SHIPPED_SESSION_EXPIRED = 'Your session expired — reload the page and sign in again.';
const SHIPPED_RELOAD_PAGE = 'Reload page';

const COPY_SOURCE_PATH = 'js/attachment-edit/copy.ts';

const readCopySource = (): string => readFileSync(join(process.cwd(), COPY_SOURCE_PATH), 'utf8');

/**
 * Source with comments stripped. Scoping these checks to the `ATTACHMENT_EDIT_COPY`
 * declaration was not enough: an intermediate `const` above it re-declares the literal
 * or re-wraps it in `__()` and slips past (mutants LC1-M5 / LC1-M6). The docstring has to
 * be excluded because it names both anti-patterns.
 */
const readCopyCode = (): string =>
  readCopySource()
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');

afterEach(() => {
  vi.doUnmock('../../admin/utils/sessionExpiredCopy');
  vi.resetModules();
});

describe('ATTACHMENT_EDIT_COPY auth-expiry copy has one owner [FEBT2-LC-NEW-01]', () => {
  it('serves exactly the shipped literals', () => {
    expect(ATTACHMENT_EDIT_COPY.sessionExpired).toBe(SHIPPED_SESSION_EXPIRED);
    expect(ATTACHMENT_EDIT_COPY.reloadPage).toBe(SHIPPED_RELOAD_PAGE);
  });

  it('serves the same values the SPA serves', () => {
    expect(ATTACHMENT_EDIT_COPY.sessionExpired).toBe(SPA_SESSION_EXPIRED_COPY.sessionExpired);
    expect(ATTACHMENT_EDIT_COPY.reloadPage).toBe(SPA_SESSION_EXPIRED_COPY.reloadPage);
  });

  it('follows the owner module rather than holding its own copy of the words', async () => {
    vi.doMock('../../admin/utils/sessionExpiredCopy', () => ({
      SPA_SESSION_EXPIRED_COPY: {
        sessionExpired: 'OWNER-SESSION-EXPIRED',
        reloadPage: 'OWNER-RELOAD',
      },
    }));
    vi.resetModules();

    const { ATTACHMENT_EDIT_COPY: reloaded } = await import('../copy');

    expect(reloaded.sessionExpired).toBe('OWNER-SESSION-EXPIRED');
    expect(reloaded.reloadPage).toBe('OWNER-RELOAD');
  });

  it('does not re-declare either literal anywhere in its own code', () => {
    const code = readCopyCode();

    expect(code).not.toContain(SHIPPED_SESSION_EXPIRED);
    expect(code).not.toContain(`'${SHIPPED_RELOAD_PAGE}'`);
    expect(code).toContain("from '../admin/utils/sessionExpiredCopy'");
  });

  it('never calls __() at all — extraction belongs to the owner module, not here', () => {
    // `__(SPA_SESSION_EXPIRED_COPY.x)` is not statically extractable by wp i18n make-pot,
    // and any __() here would mean this file had started owning copy again.
    expect(readCopyCode()).not.toContain('__(');
  });

  it('keeps the surface-specific face strings local — merging them would be coincidental DRY [REF-10]', () => {
    expect(ATTACHMENT_EDIT_COPY.faceDataUnavailable).toBe('Face data unavailable right now');
    expect(ATTACHMENT_EDIT_COPY.noFacesDetected).toBe('No faces detected');
    expect(ATTACHMENT_EDIT_COPY.stillClustering).toBe('still clustering — reload to refresh');
    expect(ATTACHMENT_EDIT_COPY.loadingFaces).toBe('Loading face data');
    expect(ATTACHMENT_EDIT_COPY.nameThisPerson).toBe('Name this person');
  });
});
