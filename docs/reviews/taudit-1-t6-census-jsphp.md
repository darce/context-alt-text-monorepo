# TAUDIT-06 source-parsing test census: JS and PHP

Scope: `apps/prototype-wp-alt-context/js` tests and `apps/prototype-wp-alt-context/tests`. This census lists tests that read implementation or test source and assert textual or syntactic shape, plus representative `keep` rows where the input is itself the canonical/generated contract. Ordinary fixture and API-payload reads are excluded. Line numbers identify the source read and the associated parse/assertion.

## JavaScript and TypeScript

### `apps/prototype-wp-alt-context/js/attachment-edit`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/attachment-edit/__tests__/copy.test.ts` | 12–67 | `copy.ts` after comment stripping for duplicate auth-expiry literals, `__()` calls, and the owner import | convert-to-lint | The runtime mock already proves ownership behavior; enforce gettext extraction and single-owner literals with a lint rule. |
| `apps/prototype-wp-alt-context/js/attachment-edit/__tests__/AttachmentFacesApp.test.tsx` | 305–319 | `attachment-edit.scss` and `_face-overlay.scss` for imports and a curated-chip declaration | rewrite-behavioral | Compile the styles and assert the emitted selector/declarations or rendered style instead of relying on SCSS spelling. |

### `apps/prototype-wp-alt-context/js/public`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/public/__tests__/demo-describe.test.ts` | 539–543 | `demo-describe.css` for the degraded-state selector, warning token, and absence of hex colors | rewrite-behavioral | Assert compiled CSS or computed styling for the degraded state. |

### `apps/prototype-wp-alt-context/js/guide`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/guide/__tests__/main.test.tsx` | 14–39 | `vite.config.ts` entry strings and the public guide PHP template's `<script>` tags | rewrite-behavioral | Verify the built entry and rendered page output instead of matching config/template source. |
| `apps/prototype-wp-alt-context/js/guide/__tests__/public-boundary.test.tsx` | 47–150 | TS/TSX import statements and the transitive public-guide import graph | convert-to-lint | This is an architectural import-boundary rule suited to ESLint or a dedicated dependency check. |
| `apps/prototype-wp-alt-context/js/guide/__tests__/publicCssBundle.test.ts` | 20–26 | `index.css` source for a forbidden admin stylesheet import; the remaining checks compile Sass | convert-to-lint | Keep the compiled CSS assertions, and move the raw import prohibition to an import-boundary lint. |

### `apps/prototype-wp-alt-context/js/admin`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx` | 1099–1103, 1261–1283 | `ReviewQueue.tsx` copy and production TS/TSX files for retired vocabulary and mutation names | convert-to-lint | Rendered-surface checks already exist; lexical prohibitions belong in a vocabulary lint. |
| `apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts` | 65–100 | Dashboard TSX files for gettext literals and the `<h1>` label, then compares parsed values with UX-map content | rewrite-behavioral | Mount the dashboard states and compare accessible rendered names/copy with the spec contract. |
| `apps/prototype-wp-alt-context/js/admin/__tests__/roster-keyboard-walk.spec.guard.test.ts` | 12–36 | The Playwright spec itself for locator, URL, skip, and environment-variable substrings | delete | A test that inspects another test's source adds no product contract; run an enabled e2e test for the keyboard flow. |
| `apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.test.ts` | 1832–1884 | `render_ux_maps.py` source for named renderer constants/functions and generated UX-map Markdown sections | rewrite-behavioral | Execute the renderer against a fixture and verify generated output; retain Markdown contract checks. |
| `apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-parity.test.ts` | 39–40, 55–157 | UX-map JSON and its generated Markdown rendering | keep | The map and rendering are the canonical UX contract whose drift this parity test is meant to catch. |
| `apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-one-primary.test.ts` | 57–104 | Structured UX-map JSON screen/action declarations | keep | `primary_action_id` and its action list are the contract data being validated. |

### `apps/prototype-wp-alt-context/js/admin/navigation`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/navigation/__tests__/appLinks.guard.test.ts` | 18–158 | TS/TSX source for raw hash routes and repeated URL parameter literals | convert-to-lint | URL ownership and restricted literals are static architecture rules suitable for lint enforcement. |

### `apps/prototype-wp-alt-context/js/admin/utils`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/utils/__tests__/adminUrls.test.ts` | 17–43, 98–150 | Production TS/TSX source for retired `tab=clusters`, modules, and imports | convert-to-lint | A retired-symbol/source sweep is a lint or dependency rule; keep the URL behavior tests. |
| `apps/prototype-wp-alt-context/js/admin/utils/__tests__/httpModuleGraph.test.ts` | 141–176, 309–465 | TS/TSX import/export text to build value and type dependency graphs | convert-to-lint | Replace the custom graph parser with a maintained import-cycle/dependency lint where its scope supports these graph types. |
| `apps/prototype-wp-alt-context/js/admin/utils/__tests__/jobStreamErrorCodeParity.test.ts` | 11–51 | The PHP producer class is passed to PHP and reflected at runtime; mutation probes execute altered declarations | keep | It observes the producer's runtime constant values rather than asserting source substrings or regex shape. |
| `apps/prototype-wp-alt-context/js/admin/utils/__tests__/logger.test.ts` | 628–638 | `logger.ts` for forbidden `instanceof` branches | convert-to-lint | Preserve the logger output behavior tests and enforce this implementation restriction with lint. |
| `apps/prototype-wp-alt-context/js/admin/utils/__tests__/recognitionCooldown.test.ts` | 159–162 | `recognitionCooldown.ts` for an `instanceof HTTPError` substring pattern | convert-to-lint | Exercise classifier behavior for the boundary case or encode the forbidden dependency as lint. |

### `apps/prototype-wp-alt-context/js/admin/pages`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/pageHeadingBoundary.test.ts` | 14–109 | `App.tsx` route/import text and routed component source for `aria-labelledby` references | rewrite-behavioral | The guard derives pages and headings from JSX source instead of rendering each routed page and checking its accessible name. |
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/menuHeadingParity.test.ts` | 12–138 | PHP `add_submenu_page()` calls, React `<h1>` blocks, Settings component mounts, and e2e route text | rewrite-behavioral | Compare real WordPress menu labels and rendered page headings through the public interfaces. |
| `apps/prototype-wp-alt-context/js/admin/pages/guided/__tests__/GuidedUxMap.contract.test.ts` | 109–112, 143–275 | UX-map, copy, and test-hook JSON artifacts | keep | These structured files are the canonical guided-demo design and test-hook contracts. |

### `apps/prototype-wp-alt-context/js/admin/pages/workbench`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/syncVocabulary.test.ts` | 20–64, 127–163 | The glossary's canonical Say/Don't-say Markdown table and runtime sync vocabulary values | keep | The glossary is the vocabulary contract; the test compares the shipped module to that source of truth. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ownedGettextLiterals.test.ts` | 31–78 | TSX AST call expressions in `ScanTabContent.tsx` and `ReviewQueue.tsx` to require literal gettext arguments | convert-to-lint | This is a translation-extraction rule and belongs in the gettext/TypeScript lint pipeline. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/syncPresentation.test.ts` | 368–462 | TypeScript interface and implementation text for deleted `failed` fields and escalation branches | convert-to-lint | Preserve presentation behavior cases and express the interface/forbidden-field constraint through type or lint checks. |

### `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts` | 11–147 | Identity-cluster TS/TSX source with a hand-written scanner for gettext first arguments | convert-to-lint | This is another literal-extraction rule; use the TypeScript AST already available in the translation tooling. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx` | 2869–2877, 6325–6332 | `personCommitCopy.ts` and `ReviewQueue.tsx` for literal and `HOLD_*_STATUS_COPY` spellings | rewrite-behavioral | Verify the disclosure and hold-state text in the rendered accessible UI; adjacent behavioral tests already cover those surfaces. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/representativeVocabulary.source.test.tsx` | 112–125 | Two TS source files for exactly one quoted unavailable-image literal | rewrite-behavioral | Assert the unavailable-image copy at the user-visible image boundary; the same suite already tests rendered sentinel behavior. |

### `apps/prototype-wp-alt-context/js/admin/guidedPrototype`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/guidedPrototype/copyCatalogParity.test.ts` | 7–25 | Canonical `copy.en.json` and the runtime guided-copy catalog | keep | The JSON is the canonical copy artifact and exact runtime parity is its contract. |
| `apps/prototype-wp-alt-context/js/admin/guidedPrototype/credits.contract.test.ts` | 16–72 | `CREDITS.md` rows and runtime bundled-photo credits | keep | The Markdown ledger is the canonical attribution/license contract for shipped images. |
| `apps/prototype-wp-alt-context/js/admin/guidedPrototype/publicGuideCopy.test.ts` | 105–118, 170–179 | Generated copy catalog text and `GuidedDesignNotes.tsx` import strings | convert-to-lint | Keep runtime copy parity; move the source-import restriction to a dependency lint and avoid inspecting generated TS text. |
| `apps/prototype-wp-alt-context/js/admin/guidedPrototype/state.test.ts` | 1283–1292 | `state.ts` for fetch, browser-global, storage, and timer tokens | convert-to-lint | A no-network/no-browser-dependency boundary is a static module rule; retain the runtime zero-fetch scenario. |

### `apps/prototype-wp-alt-context/js/admin/hooks`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useBulkDescribe.test.tsx` | 166–180 | `useBulkDescribe.ts` after import stripping for duplicate phase names, status tables, and retired routes | convert-to-lint | Test the hook's observed state transitions and enforce the single-owner dependency rule with lint. |
| `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx` | 47–49, 363–381 | `_media-selection.scss` source plus canonical GPU UX-map Markdown/JSON | rewrite-behavioral | Replace the SCSS substring assertion with compiled/rendered style behavior; the UX-map artifacts remain the contract. |

### `apps/prototype-wp-alt-context/js/admin/components/ui`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/components/ui/__tests__/UserFacingErrorNotice.test.tsx` | 51–73 | Component and copy-leaf TS source for duplicated text, `__()` calls, and gettext literal placement | convert-to-lint | Keep the visible error/reload assertions and enforce extraction ownership in lint. |

### `apps/prototype-wp-alt-context/js/admin/styles`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/styles/__tests__/query-conditions.test.ts` | 26–50, 79–100 | SCSS `@media`/`@container` conditions and source rule bodies with a brace scanner | convert-to-lint | Responsive-query and token-expression constraints are stylelint rules, not runtime behavior tests. |
| `apps/prototype-wp-alt-context/js/admin/styles/__tests__/guided-prototype-styles.test.ts` | 14–58 | `_guided-prototype.scss` rule blocks, token spellings, and declaration order | rewrite-behavioral | Compile the stylesheet and test the resulting style properties for the visible states. |

### `apps/prototype-wp-alt-context/js/admin/styles/tokens`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/styles/tokens/__tests__/design-tokens.test.ts` | 86–237 | SCSS custom-property definitions and references across the token/style tree | convert-to-lint | Dangling and duplicate token checks are static design-system rules suited to stylelint. |
| `apps/prototype-wp-alt-context/js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts` | 8–132 | Workbench/component SCSS for raw values, tokenized declarations, and `@use` statements | convert-to-lint | Token use and SCSS module wiring are style lint/import rules. |

### `apps/prototype-wp-alt-context/js/admin/styles/components`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/orientation-card-styles.test.ts` | 7–15 | `_orientation-card.scss` source for selector, spacing token, and focus-visible text | rewrite-behavioral | Assert the compiled focus and spacing styles on the dismiss control. |
| `apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/review-queue-styles.test.ts` | 7–55 | `_review-queue.scss` by slicing top-level rules and checking declaration substrings | rewrite-behavioral | Compile the stylesheet and verify the rendered error/empty distinction and non-color warning cue. |
| `apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/target-card-styles.test.ts` | 22–46 | `index.scss` and `_target-card.scss` source for import and token/selector strings; it also checks a built bundle | rewrite-behavioral | Use the emitted production CSS assertions for registration and token behavior instead of raw SCSS reads. |
| `apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/radio-group-styles.test.ts` | 29–61 | `index.scss` and `_radio-group.scss` source for registration, declarations, and focus rules | rewrite-behavioral | The production bundle is already built in this suite; assert the compiled selectors and focus behavior there. |
| `apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/name-face-surface.test.ts` | 65–69 | Two SCSS files for `@include` source spellings | rewrite-behavioral | Assert the three emitted overlay selector blocks rather than source mixin invocations. |

## PHP

### `apps/prototype-wp-alt-context/tests/Unit`

| Path | Lines | What it parses | Verdict | Reason |
|---|---:|---|---|---|
| `apps/prototype-wp-alt-context/tests/Unit/ClusterLabelServiceTest.php` | 635–668 | Controller PHP source for an explicit `require_once` substring | rewrite-behavioral | Load the controller chain without the Composer classmap and assert the service is available. |
| `apps/prototype-wp-alt-context/tests/Unit/BulkApplyBucketKeysDualSourceTest.php` | 11–24, 54–415, 434–644 | Controller PHP tokens and method bodies to scrape keys written by the bulk-apply loop | convert-to-lint | This custom token parser enforces source structure; use a PHP static rule or remove the second source of bucket keys. |
| `apps/prototype-wp-alt-context/tests/Unit/CliCommandAutoloadTest.php` | 66–116 | `alt-context.php` text/regex for the `WP_CLI` require block and CLI entry paths | rewrite-behavioral | Boot the CLI entrypoint without Composer autoload and assert command classes/registrations at runtime. |
| `apps/prototype-wp-alt-context/tests/Unit/DeclarationTimeRequireOnceGuardTest.php` | 198–230, 1208–1293, 1441–1818 | PHP files tokenized to compare declaration-time dependencies with explicit includes | convert-to-lint | Declaration/include dependency constraints belong in a PHPStan or Composer dependency rule. |
| `apps/prototype-wp-alt-context/tests/Unit/RecognitionTransportEgressGuardTest.php` | 138–220 | PHP tokens across runtime files for `wp_remote_*` calls/imports outside an allowlist | convert-to-lint | A prohibited-egress-call rule is static analysis and should run as a dedicated PHP lint gate. |
| `apps/prototype-wp-alt-context/tests/Unit/RecognitionTransportRequireOnceGuardTest.php` | 177–255, 644–670 | PHP source tokens and bootstrap file text for transport references without required includes | convert-to-lint | This is a static dependency rule; express it as PHP analysis rather than a test-owned lexer. |
| `apps/prototype-wp-alt-context/tests/Unit/ViteManifestTest.php` | 123–143 | `class-admin.php` text/regex for the Vite-manifest `require_once` target | rewrite-behavioral | Bootstrap the admin class without autoload and assert the manifest dependency is loadable. |
| `apps/prototype-wp-alt-context/tests/Unit/ClustersSchemaParityTest.php` | 26–359, 425–513, 1498–1579 | PHP SQL/write arrays and lifecycle DDL source to scrape cluster columns | convert-to-lint | Keep the DDL as schema contract and move source-column scraping to static schema analysis or database-backed writes. |
| `apps/prototype-wp-alt-context/tests/Unit/SuggestionsControllerTest.php` | 1698–1735 | Python cap assignment and PHP controller query block via regex | rewrite-behavioral | Import the Python limit and capture the actual outbound PHP request/query in parity tests. |
| `apps/prototype-wp-alt-context/tests/Unit/ClustersReadFixtureRegenGuardTest.php` | 12–24 | Its own test method source for fixture-update environment and write calls | delete | Self-inspecting the golden-test implementation is not an independent product contract. |
| `apps/prototype-wp-alt-context/tests/Unit/RunsTransactionalAutoloadTest.php` | 35–50 | Controller PHP source for a `require_once` substring | rewrite-behavioral | Exercise controller loading in a fresh process with a missing/stale Composer classmap. |
| `apps/prototype-wp-alt-context/tests/Unit/PublicGuideRouteTest.php` | 200–238, 669–676 | Rendered template PHP source for `get_header`/`get_footer` strings and plugin bootstrap source for route setup | rewrite-behavioral | The route already renders a response; assert its public output and hook registration without inspecting PHP text. |
| `apps/prototype-wp-alt-context/tests/Unit/ProjectionQueryColumnParityTest.php` | 117–195, 285–290, 412–517, 803–820 | PHP repository/query source for SQL column references and `$wpdb` writes | convert-to-lint | Query/schema parity is structural; replace the bespoke source scraper with static SQL analysis or real schema-backed queries. |
| `apps/prototype-wp-alt-context/tests/Unit/AdminPageAutoloadTest.php` | 100–120 | `alt-context.php` source for the required admin bootstrap paths | rewrite-behavioral | Use the existing no-classmap bootstrap probe to assert classes load through the actual entrypoint. |
| `apps/prototype-wp-alt-context/tests/Unit/TelemetryAutoloadTest.php` | 45–62 | Plugin entrypoint source for the Telemetry `require_once` string | rewrite-behavioral | Assert Telemetry is available after a real bootstrap without Composer autoload. |
| `apps/prototype-wp-alt-context/tests/Unit/IdentityMembersSchemaParityTest.php` | 104–161, 272–332 | PHP repository write source and DDL text for identity-member, cluster, and person columns | convert-to-lint | Preserve DDL as the contract and move implementation scraping into static schema analysis or database-backed tests. |
| `apps/prototype-wp-alt-context/tests/Unit/RecognitionDataSourceTest.php` | 43–147 | TypeScript `DATA_SOURCE` text and PHP runtime source lines for duplicate literal declarations | convert-to-lint | Centralize the enum contract or run declaration-duplication checks in the PHP/TypeScript lint pipeline. |
| `apps/prototype-wp-alt-context/tests/Unit/DescriptionCommandStatusTest.php` | 87–94 | `alt-context.php` source for CLI import and registration strings | rewrite-behavioral | Assert the registered WP-CLI command after plugin bootstrap instead of matching registration text. |

## Summary

| Verdict | Files |
|---|---:|
| convert-to-lint | 27 |
| rewrite-behavioral | 25 |
| delete | 2 |
| keep | 7 |
| **Total** | **61** |

## Proposed batching

Each batch contains at most three files. Keep rows are not scheduled for changes.

1. `pageHeadingBoundary.test.ts`, `menuHeadingParity.test.ts`, `dashboard-uxmap-code-parity.test.ts` — rewrite rendered heading/copy behavior.
2. `main.test.tsx`, `AttachmentFacesApp.test.tsx`, `demo-describe.test.ts` — rewrite config/template/style source checks as built or rendered behavior.
3. `public-boundary.test.tsx`, `httpModuleGraph.test.ts`, `appLinks.guard.test.ts` — move module/URL boundaries into lint.
4. `adminUrls.test.ts`, `banned-vocabulary.test.tsx`, `roster-keyboard-walk.spec.guard.test.ts` — lint retired-source rules; delete the test-source guard.
5. `copy.test.ts`, `gettext-literals.test.ts`, `ownedGettextLiterals.test.ts` — move copy ownership and gettext literal checks into lint.
6. `ReviewQueue.test.tsx`, `representativeVocabulary.source.test.tsx`, `UserFacingErrorNotice.test.tsx` — replace source pins with rendered behavior or gettext lint.
7. `state.test.ts`, `useBulkDescribe.test.tsx`, `syncPresentation.test.ts` — move source-boundary and interface-shape checks to lint/type validation.
8. `publicGuideCopy.test.ts`, `useDescribeRunProgress.test.tsx`, `guided-prototype-styles.test.ts` — lint source imports; assert styles through compiled/rendered output.
9. `query-conditions.test.ts`, `design-tokens.test.ts`, `workbench-tokenization.test.ts` — move SCSS parsing to stylelint/design-system rules.
10. `orientation-card-styles.test.ts`, `review-queue-styles.test.ts`, `target-card-styles.test.ts` — assert emitted or rendered component styles.
11. `radio-group-styles.test.ts`, `name-face-surface.test.ts`, `publicCssBundle.test.ts` — assert built CSS; lint the remaining raw import rule.
12. `logger.test.ts`, `recognitionCooldown.test.ts`, `uxmap-render-parity.test.ts` — lint implementation restrictions; execute the UX-map renderer for output checks.
13. `BulkApplyBucketKeysDualSourceTest.php`, `DeclarationTimeRequireOnceGuardTest.php`, `RecognitionTransportEgressGuardTest.php` — move token scans into PHP static analysis.
14. `RecognitionTransportRequireOnceGuardTest.php`, `ClustersSchemaParityTest.php`, `ProjectionQueryColumnParityTest.php` — replace custom source scanners with static dependency/schema checks.
15. `IdentityMembersSchemaParityTest.php`, `RecognitionDataSourceTest.php`, `ClusterLabelServiceTest.php` — lint shared declarations and test runtime loading/parity.
16. `CliCommandAutoloadTest.php`, `ViteManifestTest.php`, `SuggestionsControllerTest.php` — exercise actual bootstrap, class loading, and outbound query behavior.
17. `RunsTransactionalAutoloadTest.php`, `PublicGuideRouteTest.php`, `AdminPageAutoloadTest.php` — assert real bootstrap and public route behavior.
18. `TelemetryAutoloadTest.php`, `DescriptionCommandStatusTest.php`, `ClustersReadFixtureRegenGuardTest.php` — assert CLI/runtime registration and remove the self-inspecting fixture guard.
