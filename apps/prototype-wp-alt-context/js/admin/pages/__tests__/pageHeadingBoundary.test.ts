/**
 * ORCH-UX-UI BR-37/BR-38: every routed page must own its accessible name.
 *
 * A React page's `aria-labelledby` must never reference `acx-page-title` — the
 * id of the PHP-shell heading rendered once per request by
 * AbstractSpaPage::render(). That heading is now unconditionally
 * screen-reader-only, but per A11Y-58 a hidden node stays in the accessible-
 * name computation when something still references it directly. Any page that
 * points back at the shell id resurrects the exact cross-boundary staleness
 * bug this fix removed (a hash-only SPA navigation leaves the shell's <h1>
 * showing the previously-loaded page's title). Each page must instead
 * `aria-labelledby` its own, self-rendered heading id.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));

/** The six routed top-level pages mounted by js/admin/App.tsx. */
const ROUTED_PAGE_FILES = [
  '../DashboardPage.tsx',
  '../WorkbenchPage.tsx',
  '../RosterPage.tsx',
  '../RetentionPage.tsx',
  '../SettingsPage.tsx',
  '../DescriptionHistoryPage.tsx',
] as const;

const FORBIDDEN_REFERENCE = 'aria-labelledby="acx-page-title"';

describe('routed page headings stay self-contained (no PHP-shell cross-reference)', () => {
  it.each(ROUTED_PAGE_FILES)('%s never points aria-labelledby at the PHP shell heading id', (relativePath) => {
    const filePath = path.resolve(here, relativePath);
    const source = readFileSync(filePath, 'utf8');

    expect(source).not.toContain(FORBIDDEN_REFERENCE);
  });
});
