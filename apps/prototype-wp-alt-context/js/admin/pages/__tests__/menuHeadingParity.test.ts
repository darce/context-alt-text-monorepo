/**
 * BR-41: glossary.md Rule 1 requires a menu label and the `<h1>` of the page
 * it opens to be the same words. The BR-37 fix conflated `getPageTitle()`
 * (page_title — the WordPress browser `<title>`, prefixed by convention, now
 * rendered only into the permanently hidden shell heading) with menu_title
 * (the un-prefixed label the sidebar shows and Rule 1 actually binds to).
 * Three visible React `<h1>`s carried the page_title prefix as a result. This
 * guard parses class-menu.php's own `add_submenu_page()` calls — the single
 * source of truth for menu_title — and asserts every routed page's visible
 * `<h1>` matches it, so a future page can't silently regress to page_title.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const menuPhpPath = path.resolve(here, '../../../../src/admin/class-menu.php');
const menuPhpSource = readFileSync(menuPhpPath, 'utf8');

interface MenuEntry {
  pageTitle: string;
  menuTitle: string;
  slug: string;
}

/**
 * Matches each `add_submenu_page('parent', __('page_title', 'alt-context'),
 * __('menu_title', 'alt-context'), 'capability', 'slug', ...)` call in
 * class-menu.php and pulls out (page_title, menu_title, slug).
 */
const ADD_SUBMENU_PAGE_CALL =
  /add_submenu_page\(\s*'[^']*',\s*__\(\s*'([^']+)',\s*'alt-context'\s*\),\s*__\(\s*'([^']+)',\s*'alt-context'\s*\),\s*'[^']*',\s*'([^']+)',/g;

const menuEntries: MenuEntry[] = [];
for (const match of menuPhpSource.matchAll(ADD_SUBMENU_PAGE_CALL)) {
  menuEntries.push({ pageTitle: match[1], menuTitle: match[2], slug: match[3] });
}

// Mandatory before any loop (BR-41/BR-39-style fail-closed guard): if the
// add_submenu_page() regex above stops matching (PHP call reformatted,
// argument order changed), menuEntries silently empties and every assertion
// below would vacuously pass. Pin the count so a parse regression is red.
expect(menuEntries.length).toBeGreaterThan(0);
expect(menuEntries).toHaveLength(6);

/** Explicit slug -> routed React page file map. Adding a 7th submenu without extending this map fails red below, not silently. */
const SLUG_TO_PAGE_FILE: Record<string, string> = {
  'alt-context-dashboard': '../DashboardPage.tsx',
  'alt-context-workbench': '../WorkbenchPage.tsx',
  'alt-context-roster': '../RosterPage.tsx',
  'alt-context-description-history': '../DescriptionHistoryPage.tsx',
  'alt-context-retention': '../RetentionPage.tsx',
  'alt-context-settings': '../SettingsPage.tsx',
};

for (const entry of menuEntries) {
  if (!(entry.slug in SLUG_TO_PAGE_FILE)) {
    throw new Error(
      `class-menu.php registers slug "${entry.slug}" with no entry in SLUG_TO_PAGE_FILE — extend the map in menuHeadingParity.test.ts`,
    );
  }
}

const H1_BLOCK = /<h1\b[^>]*>([\s\S]*?)<\/h1>/g;
const H1_LABEL_TEXT = /__\(\s*'([^']+)'/;

describe('every routed page heading matches its admin menu label (glossary Rule 1 / BR-41)', () => {
  it.each(menuEntries)('$slug renders an <h1> matching menu label "$menuTitle"', ({ menuTitle, slug }) => {
    const pageFilePath = path.resolve(here, SLUG_TO_PAGE_FILE[slug]);
    // readFileSync throws on a renamed/missing page file — intentional
    // fail-closed behaviour, not caught.
    const pageSource = readFileSync(pageFilePath, 'utf8');

    const headingTexts = [...pageSource.matchAll(H1_BLOCK)].map((match) => {
      const labelMatch = H1_LABEL_TEXT.exec(match[1]);
      return labelMatch ? labelMatch[1] : match[1].trim();
    });

    expect(headingTexts.length).toBeGreaterThan(0);
    for (const headingText of headingTexts) {
      expect(headingText).toBe(menuTitle);
    }
  });
});
