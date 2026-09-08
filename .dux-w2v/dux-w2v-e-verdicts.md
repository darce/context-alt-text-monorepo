# dux-w2v-e verdicts

## DUX-W2D6C-RV-07

- Import: `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelectionTableBody.tsx:13` `import { mediaLibraryUrl } from '../../utils/adminUrls';`
- Call site: `MediaSelectionTableBody.tsx:153` `action={{ label: __('Open the media library', 'alt-context'), href: mediaLibraryUrl() }}`
- No literal `'/wp-admin/'` remains in MediaSelectionTableBody.tsx (grep: no matches).
- Helper: `js/admin/utils/adminUrls.ts:37-43` `mediaLibraryUrl()` reads `getConfig().adminUrls.mediaLibrary` via `resolveConfiguredAdminUrl`.
- Fallback when config missing / key empty / `getConfig()` throws: `FALLBACK_MEDIA_LIBRARY_PATH = '/wp-admin/upload.php'` (`adminUrls.ts:5`). Same pattern as `FALLBACK_MEDIA_EDIT_PATH` (`:3`) and `FALLBACK_ROSTER_PATH` (`:4`). Defect moved to a single centralised fallback; matches the other helpers in that file. On a live WP admin load the fallback is not used.
- PHP key: `src/admin/class-admin.php:407-410` localises `'adminUrls' => array( 'mediaEditBase' => ..., 'roster' => ..., 'mediaLibrary' => admin_url( 'upload.php' ) )`. Key name `mediaLibrary` matches JS character-for-character.
- Config contract: `js/admin/api/config.ts:4` `mediaLibrary?: string`; `normalizeConfig` at `:90` copies `raw.adminUrls?.mediaLibrary`.
- Mechanism that makes the original subdirectory 404 impossible: call site uses `mediaLibraryUrl()`; PHP `admin_url('upload.php')` is localised as `adminUrls.mediaLibrary`; JS prefers that configured value. Original hardcoded `href: '/wp-admin/upload.php'` is gone.
- [TEST-15]: `js/admin/pages/workbench/__tests__/MediaSelectionTableBody.test.tsx:97-115` registers `adminUrls.mediaLibrary: '/site/wp-admin/upload.php'` and asserts `href` contains that path and is not `'/wp-admin/upload.php'`. Not merely "anchor exists". `adminUrls.test.ts` does not yet cover `mediaLibraryUrl()` itself.

VERDICT: sustained

## DUX-W2V-E-NEW-1

Sweep of non-test `js/admin/**/*.{ts,tsx,js,jsx}` for literal `'/wp-admin/'`.
Production hits: only the three centralised fallbacks in `adminUrls.ts:3-5`
(`FALLBACK_MEDIA_EDIT_PATH`, `FALLBACK_ROSTER_PATH`, `FALLBACK_MEDIA_LIBRARY_PATH`).
No other call-site hardcoded admin URLs. Original claim that MediaSelectionTableBody
was the only stray href is confirmed after the fix.

no other hardcoded admin URLs found

VERDICT: sustained

Tests: MediaSelectionTableBody + adminUrls 19 passed; `npx vitest run js/admin/pages/workbench/__tests__` 46 files / 568 tests passed.

FINDINGS_BEGIN
FINDING: DUX-W2D6C-RV-07
VERDICT: sustained
EVIDENCE: MediaSelectionTableBody.tsx:13 import mediaLibraryUrl; :153 href: mediaLibraryUrl(); adminUrls.ts:37-43 reads getConfig().adminUrls.mediaLibrary with FALLBACK_MEDIA_LIBRARY_PATH='/wp-admin/upload.php' at :5 (same pattern as mediaEdit/roster); class-admin.php:410 'mediaLibrary' => admin_url('upload.php') exact key match; config.ts:4,90; test MediaSelectionTableBody.test.tsx:97-115 asserts configured /site/wp-admin/upload.php href. No '/wp-admin/' literal remains in MediaSelectionTableBody.tsx.
FINDING: DUX-W2V-E-NEW-1
VERDICT: sustained
EVIDENCE: no other hardcoded admin URLs found; only centralised fallbacks in adminUrls.ts:3-5
FINDINGS_END
