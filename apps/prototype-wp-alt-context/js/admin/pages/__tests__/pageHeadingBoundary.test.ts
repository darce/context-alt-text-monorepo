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
const appFilePath = path.resolve(here, '../../App.tsx');
const appSource = readFileSync(appFilePath, 'utf8');

/**
 * BR-42: derive the routed page list from js/admin/App.tsx instead of hand-
 * maintaining it. A hand-copied list silently stops covering a 7th route;
 * parsing App.tsx's own <Route element={...}> blocks and `import` statements
 * means adding a route without wiring this guard fails red (missing map
 * entry) instead of quietly not being checked.
 */
const ROUTE_ELEMENT_BLOCK = /<Route\b[^>]*\belement=\{([\s\S]*?)\}\s*\/>/g;
const SELF_CLOSING_COMPONENT = /<([A-Z][A-Za-z0-9]*)\s*\/>/;
const NON_PAGE_COMPONENTS = new Set(['Navigate']);

const routedComponentNames: string[] = [];
for (const match of appSource.matchAll(ROUTE_ELEMENT_BLOCK)) {
  const componentMatch = match[1].match(SELF_CLOSING_COMPONENT);
  if (!componentMatch || NON_PAGE_COMPONENTS.has(componentMatch[1])) {
    continue;
  }
  routedComponentNames.push(componentMatch[1]);
}

const resolveImportPath = (componentName: string): string => {
  const importPattern = new RegExp(`import\\s*\\{[^}]*\\b${componentName}\\b[^}]*\\}\\s*from\\s*'([^']+)'`);
  const importMatch = appSource.match(importPattern);
  if (!importMatch) {
    throw new Error(`No import found for routed component "${componentName}" in App.tsx`);
  }
  return importMatch[1];
};

const ROUTED_PAGE_FILES = routedComponentNames.map(
  (componentName) => `${path.resolve(path.dirname(appFilePath), resolveImportPath(componentName))}.tsx`,
);

// Mandatory before it.each (BR-42): if the Route/import parsing above
// regresses, ROUTED_PAGE_FILES silently empties and it.each never iterates —
// assert both so a parse break turns this guard red instead of vacuously
// green.
expect(ROUTED_PAGE_FILES.length).toBeGreaterThan(0);
expect(ROUTED_PAGE_FILES).toHaveLength(6);

const FORBIDDEN_REFERENCE = /acx-page-title/;

describe('routed page headings stay self-contained (no PHP-shell cross-reference)', () => {
  it.each(ROUTED_PAGE_FILES)('%s never points aria-labelledby at the PHP shell heading id', (filePath) => {
    const source = readFileSync(filePath, 'utf8');

    expect(source).not.toMatch(FORBIDDEN_REFERENCE);
  });
});
