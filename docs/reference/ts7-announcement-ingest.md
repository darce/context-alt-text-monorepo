# TypeScript 7.0 Announcement — Durable Ingest

## Source metadata

| Field | Value |
| --- | --- |
| Source URL | https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/ |
| Fetch date | 2026-07-12 |
| Announcement date | Not stated as a calendar date in the post body; media paths under the post use `.../sites/11/2026/07/...` (July 2026) |
| Authors / byline | Daniel Rosenwasser (Principal Product Manager); closing signed “– The TypeScript Team” |
| Related prior posts (linked) | [TypeScript native port announcement](https://devblogs.microsoft.com/typescript/typescript-native-port/); [Announcing TypeScript 6.0](https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/); [VS Code: iterating faster with TS 7](https://code.visualstudio.com/blogs/2026/06/26/iterating-faster-with-ts-7) |

This document is a structured ingest of the public announcement only. Claims and numbers below are as published on the source URL; they are not independently re-benchmarked here.

---

## Release highlights

### What TypeScript 7.0 is

- **Native port of TypeScript**, announced as generally available: a **Go-based native** rewrite of the toolset intended to keep structure and logic aligned with the original TypeScript codebase for compatibility, while delivering native-code speed and shared-memory multithreading.
- Framed as “TypeScript 7” / “TypeScript 7.0” — “a 10x faster native port of TypeScript.”
- Install surface: standard npm package `typescript` (`npm install -D typescript`), providing a new `tsc` executable (`npx tsc`).
- Editor path: new **Language Server Protocol (LSP)** foundation, with multithreading; VS Code has a dedicated extension (`TypeScriptTeam.native-preview`); Visual Studio can enable TS 7 from the workspace automatically.
- Historical lineage in the post: last year’s native-port mission; preview installs via `@typescript/native-preview` (nightly-style previews with “over 8.5 million weekly downloads”). Nightlies are expected to move to `typescript@next`.

### Naming: “tsgo” / “Corsa”

The announcement **does not** use the product names **“tsgo”** or **“Corsa”** in the fetched body. It describes a **native port built in Go**, links the earlier “TypeScript’s next step” native-port post, and points quality notes at the `microsoft/typescript-go` repo (`CHANGES.md`). Treat “tsgo”/“Corsa” as external nicknames unless confirmed elsewhere.

> Direct quote — what 7.0 is:  
> “Today we are proud to announce the availability of TypeScript 7, a 10x faster native port of TypeScript!”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> Direct quote — Go port and compatibility intent:  
> “The mission was a native port of TypeScript built in Go that could make the most of modern hardware. This port was done as faithfully as possible, writing new code while maintaining the structure and logic of the original codebase to keep results consistent and compatible between the two compilers.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> Direct quote — headline performance characterization:  
> “TypeScript 7 brings native code speed, shared memory multithreading, and a number of new optimizations that typically yield speedups between 8x and 12x on full builds.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

---

## Performance claims (as published)

### Full build: TypeScript 6 vs 7 (default checkers)

| Codebase | TypeScript 6 | TypeScript 7 | Speedup |
| --- | ---: | ---: | ---: |
| vscode | 125.7s | 10.6s | 11.9x |
| sentry | 139.8s | 15.7s | 8.9x |
| bluesky | 24.3s | 2.8s | 8.7x |
| playwright | 12.8s | 1.47s | 8.7x |
| tldraw | 11.2s | 1.46s | 7.7x |

### Memory (aggregate over a build)

| Codebase | TypeScript 6 | TypeScript 7 | Memory delta |
| --- | ---: | ---: | ---: |
| vscode | 5.2GB | 4.2GB | −18% |
| sentry | 4.9GB | 4.6GB | −6% |
| bluesky | 1.8GB | 1.3GB | −26% |
| playwright | 1.0GB | 0.9GB | −11% |
| tldraw | 0.6GB | 0.5GB | −15% |

### Editor / first-error latency (VS Code codebase example)

- Opening a file with an error: ~**17.5s** (prior) → under **1.3s** with TypeScript 7 — “over **13x** faster.”

### With `--checkers 8` (same machine; default was `--checkers 4`)

| Codebase | TypeScript 6 | TypeScript 7 (`--checkers 8`) | Speedup |
| --- | ---: | ---: | ---: |
| vscode | 125.7s | 7.51s | 16.7x |
| sentry | 139.8s | 12.08s | 11.6x |
| bluesky | 24.3s | 2.01s | 12.1x |
| playwright | 12.8s | 1.16s | 11x |
| tldraw | 11.2s | 1.06s | 10.6x |

### Language server stability (aggregate metrics)

- Failing language server commands: reduced by **over 80%** vs TypeScript 6.0.
- Server crashes: reduced by **over 60%** vs TypeScript 6.0.

### Third-party / partner anecdotes (as published)

| Claim | Detail in post |
| --- | --- |
| Slack | Eliminated **40%** of merge queue time; CI type-check ~**7.5 min → 1.25 min**; local editor previously near “unusable.” |
| Vanta | Up to **~9x** faster on one large project. |
| Microsoft News Services | **~400 hours/month** saved waiting on CI. |
| PowerBI / Loop | Qualitative: editor experience “life-saving” / monorepo “amazing” vs prior unusable scale. |
| Canva | First error in editor ~**58s → ~4.8s**. |

> Direct quote — default build speed band:  
> “…typically yield speedups between 8x and 12x on full builds.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> Direct quote — first-error latency:  
> “On the same computer, opening a file with an error in the VS Code codebase would previously take about 17.5 seconds from the time you opened the editor to the time you saw the first error. With TypeScript 7, it’s under 1.3 seconds – over 13x faster.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> Direct quote — LS reliability:  
> “…TypeScript 7.0’s new language server has actually reduced failing language server commands by over 80%, and reduced server crashes by over 60% compared to that of TypeScript 6.0.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

---

## Breaking changes and deprecations

### API / packaging (major ecosystem implication)

- **TypeScript 7.0 does not ship with a (programmatic) API.** Post expects **7.1** to ship a **new and different** API.
- Tools needing programmatic access (e.g. **typescript-eslint**) are expected to keep using **TypeScript 6.0** side-by-side for now.
- Compatibility package: **`@typescript/typescript6`** provides executable **`tsc6`** and re-exports the TypeScript **6.0 API**.
- npm alias patterns recommended so `typescript` peer deps resolve to 6.x while 7.x can be aliased (e.g. `@typescript/native` → `npm:typescript@^7.0.2`).
- Preview package **`@typescript/native-preview`** was the prior install path; nightlies moving to **`typescript@next`**.

> Direct quote — no API in 7.0:  
> “While TypeScript 7.0 is here, it does not ship with an API. We expect TypeScript 7.1 to ship with a new (and different) API, but until then we have made it a priority to ensure TypeScript can be run side-by-side with TypeScript 6.0 for utilities that still need some programmatic access to the compiler (such as typescript-eslint).”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

### Compatibility baseline with 6.0

- Designed to be compatible with **TypeScript 6.0 type-checking and CLI behavior**.
- Code that compiles cleanly with **6.0**, with **`stableTypeOrdering` on** and **without `ignoreDeprecations`**, “should compile identically in TypeScript 7.0.”
- **Adopts 6.0 defaults**; flags/constructs **deprecated in 6.0 become hard errors** in 7.0.

### New / experimental CLI flags (parallelism)

| Flag | Role (as published) |
| --- | --- |
| `--checkers` | Number of type-checker workers (default **4**; can go to **1** or higher e.g. **8**). Higher → often faster, more memory; rare order-dependent differences if varied. |
| `--builders` | Parallel project-reference builders under `--build` (monorepos). Multiplies with `--checkers` (e.g. 4×4 → up to 16 checkers). Should not change results vs checkers (per post). |
| `--singleThreaded` | Disables parallelization (parse/emit/check) for debug, fair 6-vs-7 comparison, external orchestration, or low-resource environments. |
| `--ignoreConfig` | Required for CLI builds that pass file paths when a `tsconfig.json` exists in the current directory (listed under hard errors from 6.0 deprecations). |

### Config default changes (notable)

- `strict` → **true** by default  
- `module` → **esnext**  
- `target` → current stable ECMAScript version immediately preceding `esnext`  
- `noUncheckedSideEffectImports` → **true**  
- `libReplacement` → **false**  
- `stableTypeOrdering` → **true**, **cannot be turned off**  
- `rootDir` → defaults to **`. /`**; inner source dirs must be set explicitly  
- `types` → defaults to **`[]`**; restore old auto-include with `["*"]`

### Deprecations that are hard errors / no-op (list as published)

- `target: es5` unsupported  
- `downlevelIteration` unsupported  
- `moduleResolution: node` / `node10` unsupported → prefer `nodenext` / `bundler`  
- `module: amd | umd | systemjs | none` unsupported → prefer `esnext` / `preserve` with bundlers/browser resolution  
- `baseUrl` unsupported → make `paths` relative to project root  
- `moduleResolution: classic` unsupported  
- `esModuleInterop` / `allowSyntheticDefaultImports` cannot be **false**  
- `alwaysStrict` assumed **true**; cannot set **false**  
- `module` keyword cannot be used in namespace declarations  
- Import **`asserts`** → must use **`with`** (import attributes)  
- `/// <reference no-default-lib />` not respected under `skipDefaultLibCheck`  
- CLI: file paths + present `tsconfig.json` requires **`--ignoreConfig`**

### Type-system behavior change

- **Template literal type inference** now treats Unicode **code points** (e.g. emoji as one unit) instead of UTF-16 code units / surrogate halves. Breaking for type-level utilities that intentionally modeled UTF-16 units.

### JavaScript / JSDoc analysis changes

Reworked toward consistency with `.ts` analysis; examples listed:

- Values not usable where types expected → use `typeof`  
- `@enum` not special → `@typedef` pattern on enum-like values  
- Standalone `?` as type gone → use `any`  
- `@class` does not make a function a constructor → use `class`  
- Postfix `!` unsupported  
- Type names must be defined inside `@typedef` tags (not adjacent identifier form)  
- Closure-style `function(string): void` unsupported → TS arrow-style types  
- Special cases for aliasing `this` / reassigning full `prototype` dropped  

Detailed delta file linked: https://github.com/microsoft/typescript-go/blob/main/CHANGES.md

### Editor / tsserver / LSP

- New **LSP-based** language server with multithreading; not the prior tsserver model as the primary story.
- VS Code: extension becomes default when installed; commands to disable/enable “TypeScript 7 Language Server”; expected to ship in VS Code itself “in the coming weeks.”
- Features called out as restored/added vs early previews: auto-imports, expandable hovers, inlay hints, code lenses, go-to-source-definition, JSX linked editing/tag completions; former beta gaps (semantic highlighting, sort imports, remove unused imports, etc.) “now in.”
- **Embedded languages** (Vue, MDX, Astro, Svelte, etc.) and tools that embed TS (e.g. **Volar**), plus specialized template checking (**Angular**), **likely cannot use TS 7 yet** because there is **no stable programmatic API**.

---

## Migration guidance (as published)

### CLI / install

1. Install TypeScript 7: `npm install -D typescript` → use `npx tsc`.
2. Prefer **adopting TypeScript 6.0 first** so 6.0 defaults/deprecations are already handled before 7.0 hard errors.
3. For tools that need the **6.0 API**, install side-by-side via **`@typescript/typescript6`** / npm aliases (`tsc6` + re-exported API). Example dual-alias layout:
   - `"@typescript/native": "npm:typescript@^7.0.2"`
   - `"typescript": "npm:@typescript/typescript6@^6.0.2"`
4. Nightly channel: `npm install -D typescript@next` (replacing reliance on `@typescript/native-preview` over time).
5. Tune parallel work: `--checkers`, `--builders`, or `--singleThreaded` for CI/resource-constrained hosts; fix checker count if order-dependent edge cases appear.
6. Config mitigations called out:
   - Set `"rootDir": "./src"` (or equivalent) when config sits outside source tree.
   - Set `"types": ["node", "jest", ...]` explicitly when globals were previously auto-pulled.

### Editor / tooling

- VS Code: install TypeScript 7 extension; use Disable/Enable TypeScript 7 Language Server commands to flip back to 6.0 when needed.
- Visual Studio: latest IDE enables TS 7 from workspace automatically.
- Other editors: LSP foundation expected to work; check each editor’s docs.
- **Vue / MDX / Astro / Svelte / Volar-style embeds:** stay on **TypeScript 6.0** until a programmatic API story lands.
- **Angular-style** template workflows: post suggests **TS 7 for CLI `tsc` project-wide errors** + **TS 6.0 for editor** until embeds work.

### Build-tool integration

- Rebuild of **`--watch`** on a Go port of Parcel’s file watcher (`@parcel/watcher` lineage) for cross-platform efficiency; intended to improve resource use vs polling-heavy approaches.
- Project references: parallel **`--builders`** under **`--build`** for monorepos; bottlenecked by project dependency graph (except paths using `--isolatedDeclarations` + separate syntactic declaration emit, as noted).
- External parallel orchestration: use **`--singleThreaded`** so outer systems own concurrency.

### `@types` / ecosystem notes

- Default **`types: []`** means **no automatic inclusion** of all `@types/*` packages; list needed packages or use `["*"]` to restore prior behavior.
- Ecosystem plugins/tools that **import `typescript` as a library** remain on the **6.x API path** until 7.1+ API ships.
- Broader automated GitHub project testing mentioned as rebuilt to run against TS 7 (regression hunting).

---

## What is unchanged / compatibility guarantees

As published:

- Goal of a **faithful port**: structure/logic retained so results stay **consistent and compatible** between the two compilers.
- **Type-checking and command-line behavior** aimed at **parity with TypeScript 6.0** (with the caveats above: 6.0 defaults, hard deprecations, Unicode template-literal change, JS analysis rework, no 7.0 API).
- Explicit compatibility claim:

> “TypeScript 7.0 is made to be compatible with TypeScript 6.0’s type-checking and command-line behavior. Practically any TypeScript code that compiles cleanly with TypeScript 6.0 (with the `stableTypeOrdering` flag on, and without any `ignoreDeprecations` flag set) should compile identically in TypeScript 7.0.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

- Large existing test suite still runs on every `main` commit; additional production soak with large internal/external codebases claimed.
- Release cadence expectation after 7.0: return to feature work; **new featureful versions every ~3–4 months**, with **7.1** intended to address API/ecosystem gaps.

---

## Additional load-bearing quotes

> “Just as with any other release, TypeScript 7 is available via npm: `npm install -D typescript`”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> “Until now, most developers have installed TypeScript 7 via the `@typescript/native-preview` package. This package shipped nightly builds of the new codebase, and has served the community well with over 8.5 million weekly downloads!”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> “Workflows that use Vue, MDX, Astro, Svelte, and others will likely not yet be able to leverage TypeScript 7. … This is mainly because TypeScript 7 does not yet expose a stable programmatic API…”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

> “Welcome to the native era of the TypeScript toolset.”  
> — https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

---

## Open questions

1. **Exact public GA calendar date** of the blog post is not printed as “Published: YYYY-MM-DD” in the fetched content (only 2026/07 media paths and related June 2026 VS Code post).
2. **“tsgo” / “Corsa”** naming is **absent** from this announcement; relationship of those nicknames to the shipping `typescript@7` / `typescript-go` surfaces is not defined here.
3. **Precise shape of the 7.1 API** (“new and different”) is promised but not specified.
4. **When** VS Code will ship native TS 7 “as part of VS Code itself” (“coming weeks”) — no fixed date.
5. **Timeline** for Vue/MDX/Astro/Svelte/Volar/Angular editor embeds on TS 7 is “committed” but unbounded.
6. **Machine specs** for the published benchmark tables are not detailed (only “same machine” for checker comparisons).
7. **Order-dependent results** when varying `--checkers`: frequency, detection guidance, and recommended CI policy beyond “fix a fixed number” are thin.
8. **Full JS support delta** is deferred to `CHANGES.md` in `typescript-go` — this post is not exhaustive.
9. Whether **all** TypeScript 6.0 deprecations are listed vs summarized (“at a glance”) — treat the post list as non-authoritative vs official migration guides if they diverge.
10. Interaction of **`--builders` × `--checkers`** with CI runner sizes: no universal recommended matrix published.
11. **Package version pins** in examples (`^7.0.2`, `^6.0.2`) may lag current tags; operators should resolve live npm metadata.
12. Scope of “identical” compile results under the compatibility claim vs known intentional breaks (Unicode template literals, JS analysis, hard deprecations) needs careful reading: the identity claim is conditioned on clean 6.0 compiles under `stableTypeOrdering` and no `ignoreDeprecations`.

---

## Ingest notes (operator)

- **Lane / task:** INV-TS7 / `lane-inv-ts7-ingest`  
- **Worktree file:** `docs/reference/ts7-announcement-ingest.md`  
- **Method:** Web fetch of the source URL on 2026-07-12; content structured for durable reference without fabricating unpublished claims.  
- **Heuristic touchpoints:** docs-only durable reference (no runtime code); do not invent numbers or names absent from source; open questions capture ambiguity rather than resolving it.
