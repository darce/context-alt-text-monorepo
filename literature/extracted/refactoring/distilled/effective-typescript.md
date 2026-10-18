# Effective TypeScript — distilled

> **Source**: Dan Vanderkam, *Effective TypeScript: 62 Specific Ways to Improve Your TypeScript*, O'Reilly 1st ed. 2019 · extracted from `../effective-typescript.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The directory's only systematic treatment of TypeScript's *type system as a soundness budget*: which constructs silently disable checking (`any`, `as`, `!`, `declare module`, stubbed @types), which recover it (`unknown`, narrowing, tagged unions, user-defined guards), and the diff-observable cues for each. Unique named concepts no other source here defines: **structural typing** surprises, **excess property checking** as a distinct-from-assignability process, **type widening** / **narrowing**, **evolving any**, **declaration merging**, **brands** for nominal typing, the **three-versions problem** of @types, and the **contagious any**. Also the canonical TS async rules (async-all-the-way, never half-synchronous) and the JS→TS migration playbook. Where `refactoring-typescript` gives shape-level refactorings, this source gives the type-level correctness rules that make those shapes checkable.

## Chapter map

- ch-1 — Getting to Know TypeScript (items 1–5): what the type system does and does not guarantee (superset, erasure, unsoundness, `any`)
- ch-2 — TypeScript's Type System (items 6–18): types-as-sets, type vs value space, declarations vs assertions, type/interface, index signatures, readonly, mapped types
- ch-3 — Type Inference (items 19–27): when to annotate; widening, narrowing, object creation, aliasing, async, context, functional constructs
- ch-4 — Type Design (items 28–37): valid-states-only types, Postel's law, null perimeter, unions of interfaces, precise strings, incomplete-over-inaccurate, naming, brands
- ch-5 — Working with any (items 38–44): scoping, precise variants, hidden assertions, evolving any, unknown, monkey patching, type coverage
- ch-6 — Type Declarations and @types (items 45–52): devDependencies, three versions, exporting types, TSDoc, `this`, conditional types, mirroring, testing types
- ch-7 — Writing and Running Your Code (items 53–58): ECMAScript-vs-TS features, object iteration, DOM hierarchy, private, source maps
- ch-8 — Migrating to TypeScript (items 58–62): modern JS first, @ts-check, allowJs, dependency-graph order, noImplicitAny as the finish line

Each item below is one falsifiable rule: **Rule** = condition → action; **Detect** = the diff/error/plan cue an agent can pattern-match.

---

## ch-1 — Getting to Know TypeScript {#ch-1}

Foundational model: TypeScript is a **superset of JavaScript** — every syntactically valid JS program is a TS program, but not vice versa. The type checker and the emitter are **independent**: code with type errors still emits JavaScript ("doesn't compile" is the wrong phrase; "doesn't type check" is right). Types are **erased** at emit. The type system is deliberately **unsound**: passing the checker does not guarantee no runtime type errors (out-of-bounds access, `any`, runtime data diverging from declared types all slip through). Soundness-first languages (Elm, Reason) buy guarantees at the cost of not being a JS superset.

### Item 1 — Understand the TS/JS relationship
- **Rule**: If you expect the checker to prove runtime safety, recalibrate — it models JS runtime behavior and flags *likely-unintended* code (`alert('a','b')`, `null + 7`), but declared and runtime types can diverge. Treat checker-pass as strong lint, not proof.
- **Detect**: reasoning like "it type-checks so it can't throw"; surprise that `2 + '3'` passes (it models JS: result `string`).
- Adding type annotations lets TS check *intent*, not just behavior — annotate to convert "did you mean `capital`?" guesses into real errors.

### Item 2 — Know which compiler options you're using
- **Rule**: Before diagnosing any TS behavior or sharing a repro, read `tsconfig.json` (prefer it over CLI flags). `noImplicitAny` (variables must have known types) and `strictNullChecks` (`null`/`undefined` not members of every type) change the language. New projects: `strict` on from day one. Only JS-migrations may temporarily relax `noImplicitAny`.
- **Detect**: `const x: number = null` compiling; a colleague's error you can't reproduce; "undefined is not an object" runtime errors (= `strictNullChecks` off, or overridden).
- Enable `noImplicitAny` before `strictNullChecks`; the longer you wait, the harder the flip.

### Item 3 — Code generation is independent of types
- **Rule**: Never branch runtime logic on a type-only construct. `instanceof Interface` checks a *value* that doesn't exist; `val as number` performs no conversion; type-level function overloads don't dispatch at runtime; types have zero runtime performance cost.
- **Detect**: `instanceof` against an `interface`/`type` name ("only refers to a type, but is being used as a value"); an `as` expected to transform data; two function bodies differing only in param types ("Duplicate function implementation").
- To recover a type at runtime: property check (`'height' in shape`), an explicit **tagged union** discriminant, or `class` (which introduces both a type and a value):

```ts
type Shape = {kind:'square'; width:number}
           | {kind:'rect';   width:number; height:number};
if (shape.kind === 'rect') { /* narrowed */ }
```

### Item 4 — Get comfortable with structural typing
- **Rule**: Expect **structural ("duck") typing**: any value with the right properties is assignable — including values with *extra* properties. Types are "open," not sealed. Classes too: an object literal with matching shape is assignable to a class type without its constructor ever running.
- **Detect**: a `Vector2D` function silently accepting `{x,y,z}` (z ignored → wrong math); `const d: C = {...}` where `C` is a class with constructor logic; iteration code assuming a parameter has *only* the declared keys.
- Exploit it: unit tests pass a narrow hand-rolled `interface DB { runQuery(sql: string): any[] }` instead of the real `PostgresDB` — no mocking library. Guard against it with brands (item 37) when impostors would corrupt logic.

### Item 5 — Limit use of `any`
- **Rule**: Every `any` is a standing liability, not a one-time cost: no type safety on the value, breaks function contracts (a string `birthDate: any` passes into a `Date` param), kills language services (autocomplete, rename), masks bugs during refactors (an `(item: any)` callback compiles happily after the param changed to `id: number` — then throws), hides your type design, and erodes team trust in the checker.
- **Detect**: `: any` annotations or `as any` in a diff; a type error "fixed" by an `any`; heavily-`any` state objects whose design nobody can read.

## ch-2 — TypeScript's Type System {#ch-2}

Core mental model: **think of types as sets of values** (the type's *domain*). `never` = ∅; literal ("unit") type = one-element set; union = set union; intersection applies to *domains*, so `A & B` has the properties of both A and B; `extends` / "assignable to" / "subtype of" all read as **"subset of"**; `unknown` = the universal set. Two consequences juniors miss: `keyof (A|B) = (keyof A) & (keyof B)` (possibly `never`), and a value with extra properties still belongs to the type.

### Item 6 — Use your editor to interrogate the type system
- **Rule**: Before guessing or annotating, hover to see what TS inferred; if an inferred return type surprises you, that's a bug lead, not noise. Go-to-definition into `lib.dom.d.ts` / library `.d.ts` files to learn how behavior is modeled.
- **Detect**: debugging types by trial-and-error annotations; never inspecting the inferred type at the error site.

### Item 7 — Think of types as sets of values
- **Rule**: When an assignability error confuses, translate to sets: "X is not assignable to Y" = "X ⊄ Y". Generic constraints (`K extends string`, `K extends keyof T`) mean "K's domain ⊆ …", not OO inheritance. Tuples aren't assignable from arrays (`number[]` ⊄ `[number, number]`), and a triple isn't a pair (length `3` ⊄ `2`).
- **Detect**: confusion over `interface A extends B`, `Exclude<A,B>`, or why `Person & Lifespan` has *all* the properties rather than none.

### Item 8 — Type space vs value space
- **Rule**: Know which space each symbol lives in. Same name can exist in both (`interface Cylinder` + `const Cylinder`). `typeof`, `this`, `[]`, `&`, `|`, `extends`, `in` mean different things per space; `class` and `enum` create both a type and a value. In destructuring, `function f({person: Person})` *renames a value* — put the whole annotation after the pattern.
- **Detect**: "Binding element implicitly has an 'any' type" + "Duplicate identifier 'string'" in destructured params; `typeof x` giving `"object"` where a TS type was expected; `InstanceType<typeof C>` needed to go from constructor type to instance type.

### Item 9 — Prefer type declarations to type assertions
- **Rule**: `const x: T = {...}` *verifies* conformance (missing/extra properties error); `{...} as T` *overrides* the checker and skips excess-property checking. In arrows, annotate the return: `(name): Person => ({name})`. Assertions are legitimate only when you genuinely know more than the checker — canonical case: DOM element identity. `!` (non-null assertion) is an assertion with the same bar; it's erased at runtime. Assertions only convert between overlapping types; arbitrary conversion requires `as unknown as T` — treat any occurrence as a red flag.
- **Detect**: `as T` on object literals; `map(name => ({name} as Person))`; `!` with no nearby reason the value must be non-null.

### Item 10 — Avoid object wrapper types
- **Rule**: Never annotate with `String`, `Number`, `Boolean`, `Symbol`, `BigInt`. `string` is assignable to `String` but not the reverse, so a wrapper type poisons every downstream call expecting the primitive. Runtime wrappers exist only so primitives can have methods.
- **Detect**: capitalized primitive in a type position; "'string' is a primitive, but 'String' is a wrapper object" errors.

### Item 11 — Limits of excess property checking
- **Rule**: **Excess property checking** ("strict object literal checking") fires only when an *object literal* is assigned to a declared type — it catches key typos (`darkmode` vs `darkMode`) that structural assignability would legally admit. It is bypassed by intermediate variables and by assertions; don't conflate it with assignability. Related: "weak types" (all-optional) must share ≥1 property with the assigned value in *all* assignments.
- **Detect**: an error that disappears when a literal is factored into a variable; option-bag typos reaching runtime; `as` used to shut the check up.

### Item 12 — Apply types to entire function expressions
- **Rule**: When several functions share a signature, or you wrap an existing function, type the whole expression instead of each param/return: `type BinaryFn = (a: number, b: number) => number`, or `const checkedFetch: typeof fetch = async (input, init) => {...}` — params are inferred and the checker verifies your return path matches the wrapped contract (e.g., catches `return new Error(...)` where a `throw` was needed).
- **Detect**: repeated identical hand-written signatures; a wrapper whose type has drifted from its wrappee.

### Item 13 — type vs interface
- **Rule**: Both express object shapes, function types, generics, extension, and `implements`. Only `type` can express unions, mapped/conditional types, and tuples cleanly. Only `interface` supports **declaration merging** (a second `interface X` block augments the first) — required for declaration files (that's how `lib.es2015.d.ts` adds `Array` methods), a hazard for internal types. Decide by (a) codebase convention, (b) whether consumers *should* be able to augment. No `I`/`T` name prefixes.
- **Detect**: new named object type — check project style; a second same-name `interface` block silently merging; a union forced through `interface` gymnastics.

### Item 14 — Use type operations and generics to avoid repeating yourself
- **Rule**: DRY applies in type space. Name repeated shapes; extend rather than copy; derive: index (`State['userId']`), mapped types (`{[k in keyof Options]?: Options[k]}`), `keyof`, `typeof value` (careful: value becomes source of truth), `ReturnType<typeof fn>`. Standard-library generics: `Pick<T,K>`, `Partial<T>`, `Record<K,V>`, `ReturnType<F>`. Generic types are the functions of type space; constrain with `extends` (`K extends keyof T`).
- **Detect**: two interfaces with hand-copied fields; a `-Update` variant with every field re-typed `?`; a tag union `'save'|'load'` maintained separately from `Action['type']`.

### Item 15 — Index signatures are for dynamic data
- **Rule**: `{[key: string]: T}` allows *any* key, requires none, forces one value type, and kills autocomplete. Reserve it for truly dynamic keys (CSV columns, unknown external maps); consider `T | undefined` values for safe access. If the key set is knowable — even partially — use an interface, `Record<'x'|'y'|'z', number>`, or a mapped type (which can vary value types per key).
- **Detect**: index signature over keys that are actually enumerable; `{}` being a valid value of a type meant to have required fields.

### Item 16 — Prefer Array/tuple/ArrayLike to `number` index signatures
- **Rule**: JS object keys are strings (numeric keys are stringified at runtime; `Object.keys([...])` returns strings). TS's `number` index is a helpful *fiction* for arrays — don't write your own. Use `Array<T>`, tuples, or `ArrayLike<T>` (length + numeric index only). Avoid `for-in` over arrays (wrong types, and far slower than `for-of` / C-style).
- **Detect**: `{[n: number]: T}` outside stdlib; `for (const i in array)`.

### Item 17 — Use readonly to avoid mutation errors
- **Rule**: If a function doesn't mutate an array param, declare it `readonly T[]`: the checker rejects in-body mutations (`pop`, `length=`, `push`) and callers may pass readonly arrays (broader inputs — item 29). `T[]` is a *subtype* of `readonly T[]` (mutable is strictly more capable). `readonly` and `Readonly<T>` are **shallow**; use a `DeepReadonly` generic from a library if needed. Declaring locals `readonly` flushes out aliasing+mutation bugs (pushing a reference then clearing it in place).
- **Detect**: a "compute" helper that consumes its input (`while(arr.pop())`); comment "does not modify nums" instead of `readonly`; shared mutable accumulator pushed into a result structure.

### Item 18 — Mapped types keep values in sync
- **Rule**: When a value must track a type's properties (e.g., "which props require a redraw"), declare it `const REQUIRES_UPDATE: {[k in keyof ScatterProps]: boolean}` — adding a property to the interface then *fails to compile* at the decision point, forcing the future editor to decide. **Fail closed at compile time** instead of relying on a "remember to update X" comment (an array of keys can't do this).
- **Detect**: comments pleading "if you add a property here, update …"; optimization code enumerating properties by hand with no exhaustiveness guard.

## ch-3 — Type Inference {#ch-3}

Posture: experienced TS has *few* annotations — signatures annotated, locals inferred. A variable's type is fixed where it's introduced (exceptions: narrowing, and evolving `any`, item 41).

### Item 19 — Avoid cluttering code with inferable types
- **Rule**: Don't annotate what inference already knows: `let x = 12`, object/array literals, destructured locals, callback params of well-typed libraries, defaulted params (`base = 10` infers `number`). DO still annotate: **object literals** (turns on excess-property checking; localizes the error to the definition, not the use) and **function return types** (stops implementation errors surfacing in callers — e.g., a cache branch returning `number` from a `Promise<number>` function; enables named return types; contract-first thinking). Lint: `no-inferrable-types`.
- **Detect**: diff full of redundant local annotations; conversely, an error reported at a call site whose real cause is an unannotated return leaking a union.

### Item 20 — Different variables for different types
- **Rule**: A variable's *value* changes; its *type* generally shouldn't. Don't reuse one variable for a string then a number — introduce a second `const` with a meaningful name. Simpler types, `const` over `let`, better inference, no union contamination.
- **Detect**: `let id = "12-34-56"; … id = 123456` errors; a `string|number` annotation that exists only to permit reassignment.

### Item 21 — Understand type widening
- **Rule**: **Widening**: from a literal initializer TS infers a broader type to permit reassignment (`let x = 'x'` → `string`; object properties widen as if `let`). When widening breaks a call (`string` not assignable to `"x"|"y"|"z"`), control it: `const` (primitives narrow to literal types), an explicit annotation (`{x: 1|3|5}`), context (item 26), or **`as const`** (no widening at all: deep-readonly, exact literals, tuple inference `readonly [1,2,3]`). `as const` moves errors to *use* sites — a malformed definition errors where it's consumed.
- **Detect**: extract-variable refactor introduces literal-union assignability errors; array meant as a tuple inferred `number[]`; `v.y = 4` rejected on an inferred `{x: number}`.

### Item 22 — Understand type narrowing
- **Rule**: **Narrowing** refines a union along control flow: null checks, early `throw`/`return`, `instanceof`, `'key' in obj`, `Array.isArray`, and tagged-union `switch (e.type)`. Traps where the checker is *right* and you're not: `typeof null === 'object'`; `!x` also excludes `''` and `0`. When flow analysis can't prove what you know, write a **user-defined type guard** — `function isDefined<T>(x: T | undefined): x is T` makes `.filter(isDefined)` produce `T[]` where an inline lambda stays `(T|undefined)[]`.
- **Detect**: an `as` where a guard/discriminant would do; a `filter` that doesn't narrow; a `typeof === 'object'` branch still including `null`.

### Item 23 — Create objects all at once
- **Rule**: A value's type is fixed at creation — building `{}` then assigning properties errors (and hides shape). Build whole literals; compose with spread `{...pt, ...id}`; conditionally add properties with `...(cond ? {middle: 'S'} : {})` (yields a union; use a typed `addOptional` helper if you want an optional field instead); use a *new* variable per intermediate shape so each gets a type.
- **Detect**: `pt.x = 3` on `{}` ("Property 'x' does not exist on type '{}'"); `Object.assign(target, a, b)` feeding typed reads.

### Item 24 — Be consistent in your use of aliases
- **Rule**: Introducing an alias (`const box = polygon.bbox`) splits narrowing: checking `polygon.bbox` refines the property, *not* the alias. Golden rule: **if you introduce an alias, use it consistently** (destructuring enforces the naming too). Runtime hazard: after a function call, a property refinement may be stale — TS pragmatically assumes calls don't invalidate refinements, but they can. Trust refinements on locals more than on properties.
- **Detect**: "Object is possibly 'undefined'" on an alias right after the original was checked; property refinement relied on across an intervening mutating call.

### Item 25 — async functions over callbacks *and* raw Promises
- **Rule**: Prefer Promises to callbacks (composability, type flow), and `async/await` to raw Promises. Types flow beautifully: `const [a, b] = await Promise.all([...])` infers each; `Promise.race([fetch(url), timeout(ms)])` collapses `Response | never` → `Response`. Two hard rules: (1) **if a function returns a Promise, declare it `async`** — `async` guarantees a Promise return, and returning a Promise inside `async` doesn't double-wrap; (2) **a function must be always-sync or always-async, never both by branch** — a cache-hit path that invokes a callback synchronously reorders observable state (the classic `requestStatus` ends `'loading'` on cache hits).
- **Detect**: `function f(): Promise<T>` implemented with `.then` chains; a memo/cache wrapper whose fast path calls back synchronously; callback pyramids in new code.

### Item 26 — Understand how context is used in inference
- **Rule**: TS infers from the value *and its location*. Factoring an inline value into a variable strips the context: string literal params (`setLanguage(language)` fails with `string`), tuples (`panTo(loc)` fails with `number[]`), object literals with literal-typed fields, callbacks (extracted → implicit-any params). Fixes: annotate the variable (`const loc: [number, number]`), `as const` (mind use-site errors and readonly-vs-mutable param types), annotate callback params, or keep it inline.
- **Detect**: an "extract variable/function" refactor that introduces assignability or implicit-any errors with no logic change.

### Item 27 — Functional constructs help types flow
- **Rule**: Built-ins (`map`, `flat`, `filter`, `reduce`, `Object.values`, `Object.entries`) and typed util libraries (Lodash chains, `_.zipObject`, property-shorthand `_.map(xs, 'name')`) carry types through with zero annotations; hand-rolled loops with mutable accumulators demand annotations and invite evolving-any errors. `const allPlayers = Object.values(rosters).flat()` needs nothing; the loop+`concat` version needs an annotation.
- **Detect**: loop building a result where the only reason for an annotation is the loop; `(row, val, i) => (row[headers[i]] = val, row), {}` reduce-into-`{}` errors.

## ch-4 — Type Design {#ch-4}

Theme (Fred Brooks): show the data and the flowcharts become obvious. Types *are* the design surface — most items here generalize beyond TypeScript.

### Item 28 — Prefer types that always represent valid states
- **Rule**: If a type admits states no code path should produce (`isLoading` and `error` both set), every consumer must arbitrate the contradiction and will do so inconsistently; some functions become *impossible to implement correctly*. Model each state explicitly as a **tagged union** (`{state:'pending'} | {state:'error'; error} | {state:'ok'; pageText}`), even at 3–4× the length — `renderPage`/`changePage` become trivially correct switches.
- **Detect**: state interface with co-occurring booleans + optional error/data fields; "which field wins?" branches; the Airbus 447 cautionary shape — two independent inputs (`leftSideStick`, `rightSideStick`) where the domain guarantees only one is meaningful: no `getStickSetting` over that input type can be right.

### Item 29 — Liberal in what you accept, strict in what you produce
- **Rule**: Postel's law for signatures: parameters may be loose (unions, optionals, `LngLatLike` variants); **return types must be canonical and fully-defined** (`Camera`, every field present). A return type with many optionals/unions forces every caller to re-narrow (`zoom: number|undefined` from `viewportForBounds`). Maintain a canonical type + a `-Like` loose form; derive the option type (`interface CameraOptions extends Omit<Partial<Camera>, 'center'> { center?: LngLatLike }`).
- **Detect**: destructuring a function's result immediately errors on half the union; a return type reusing the permissive input type.

### Item 30 — Don't repeat type information in documentation
- **Rule**: Comments restating param/return types drift and lie ("when code and comments disagree, they're both wrong"). Types are compiler-enforced; prose isn't. "Does not modify" → `readonly`. Type-encoding names (`ageNum`) → typed `age`. Exception: **units** belong in names when not expressed in types: `timeMs`, `temperatureC` (or brands, item 37).
- **Detect**: doc comment contradicting the signature; `@param {string}` JSDoc type braces inside TS; variables named after their types.

### Item 31 — Push null values to the perimeter of your types
- **Rule**: Never let A's nullness *implicitly* imply B's. Return one nullable aggregate — `extent(): [number, number] | null` — not a pair of independently-`undefined` values (which also hid the `!min` falsy-zero bug). Classes: don't hold `user: X|null; posts: Y|null` filled by racing fetches (4 null-combinations infect every method) — write a `static async init()` that awaits everything and constructs a fully non-null instance. Don't swap nullable props for Promises (forces everything async, muddies the consumer).
- **Detect**: `(number | undefined)[]` returns; several `X | null` fields assigned in separate awaits; "if a is set, b is always set" comments; `strictNullChecks` errors clustering around one structure.

### Item 32 — Prefer unions of interfaces to interfaces of unions
- **Rule**: `{layout: FillLayout|LineLayout; paint: FillPaint|LinePaint}` admits invalid cross-pairings; `FillLayer | LineLayer | PointLayer` (each pairing its own interface, ideally with a `type` tag) makes them unrepresentable and gives the checker a discriminant to narrow on. Optional fields that co-occur (`placeOfBirth?`/`dateOfBirth?`) → nest into one optional object (`birth?: {place; date}`), or, if the shape is externally fixed, a union of interfaces (`Name | PersonWithBirth`) checked via `'placeOfBirth' in p`.
- **Detect**: multiple union-typed properties whose arms move together; paired optionals with a "both present or neither" comment (a type-information comment — item 30's smell).

### Item 33 — Prefer more precise alternatives to string types
- **Rule**: "Stringly typed" code invites format drift and swapped-argument bugs (`recordRelease(date, title)` compiles). Replace: enumerable values → **union of string literals** (`type RecordingType = 'studio' | 'live'` — documented, autocompletable; not `enum`, item 53); dates → `Date`; property-name params → `keyof T`. The `pluck` progression is canonical: `key: string` → `keyof T` (return `T[keyof T][]`, still too wide) → `<T, K extends keyof T>(xs: T[], key: K): T[K][]` (exact).
- **Detect**: fields whose legal values live in a comment; `key: string` indexed into objects; adjacent same-typed string params.

### Item 34 — Prefer incomplete types to inaccurate types
- **Rule**: The **uncanny valley of type precision**: refining `any` helps, but past a point extra "precision" that's *wrong* (a `[number, number]` position that forbids GeoJSON's legal third element; fixed-arity call-expression interfaces that reject legal variadic `+`) is worse than acknowledged looseness — users trust precise types, then must assert around them. As you tighten declarations, keep a test corpus of valid and invalid values; watch the *quality of error messages and autocomplete*, not just checking power. If you can't model accurately, leave `any`/`unknown` and say so.
- **Detect**: a typings-precision PR that makes downstream users add assertions or `as any`; declarations rejecting spec-legal inputs; error messages that got dramatically worse after "improving" types.

### Item 35 — Generate types from APIs and specs, not data
- **Rule**: Types from a spec/schema cover cases you haven't seen; types from sample data cover only what you sampled. GeoJSON's `GeometryCollection` (no `coordinates`) is exactly what example-derived types miss — official `@types/geojson` caught the real bug. GraphQL schemas generate exact per-query types with nullability (Apollo codegen); DOM types are spec-generated. Data-derived types (quicktype) are a last resort.
- **Detect**: hand-written types for a format with an official spec or @types package; API response types transcribed from one sample payload.

### Item 36 — Name types using the language of the problem domain
- **Rule**: Reuse established domain vocabulary (IUCN `ConservationStatus` codes, Köppen climate classes) instead of inventing `endangered: boolean` / `habitat: string`. Make distinctions meaningful (no decorative synonyms — same thing, same name); ban `data`/`info`/`thing`/`item`/`entity`-grade names; name things for what they *are*, not how they're computed (`Directory`, not `INodeList`). Co-opting domain terms to mean something else is worse than inventing.
- **Detect**: field semantics that require finding the original author to interpret; two names for one concept in one function (item 24's `box`/`bbox`).

### Item 37 — Consider "brands" for nominal typing
- **Rule**: When structural typing admits wrong-but-shaped values, add a **brand**. Runtime brand: `interface Vector2D {_brand: '2d'; x; y}` + factory. Type-system-only brand (zero runtime cost, works on primitives): `type AbsolutePath = string & {_brand: 'abs'}` — unconstructable directly; obtainable only via a guard (`function isAbsolutePath(p: string): p is AbsolutePath`) or by being handed one. Encodes invariants the type system can then police: sortedness (`SortedList<T>` required by `binarySearch`), units (`Meters`, `Seconds` — arithmetic drops brands), path kinds. The general stance: to call the function you must *be given* proof or *establish* it with a check.
- **Detect**: functions that must reject structurally-compatible impostors (2D vs 3D vectors); binary search over possibly-unsorted input; mixed-unit numeric code.

## ch-5 — Working with any {#ch-5}

Theme: gradual typing is TypeScript's superpower and `any` is its mechanism (and migration's, ch-8) — the discipline is *scope, precision, containment, measurement*.

### Item 38 — Use the narrowest possible scope for `any`
- **Rule**: Scope `any` to a single expression: `processBar(x as any)` beats `const x: any = ...` (which untypes `x` for the rest of the function). **Never return `any`** — a returned `any` is *contagious*: `const foo = f1(); foo.fooMethod()` is silently unchecked in a different file (explicit return annotations prevent the escape — item 19). To silence one spurious error, `// @ts-ignore` on that line beats widening a type (but the next error there goes unseen too). One bad property in a big literal → assert *that property* (`key: value as any`), never the whole object.
- **Detect**: `: any` variable declarations; `as any` wrapping whole literals; unannotated-return function whose body traffics in `any`.

### Item 39 — Prefer more precise variants of `any`
- **Rule**: If "any array" is meant, write `any[]` (checks arrayness at call sites; `.length` returns `number`); "any object" → `{[key: string]: any}`; function types → `() => any` / `(...args: any[]) => any` (rest param typed `any[]`, not `any`). Each variant keeps some checking that bare `any` throws away. `object` allows key enumeration but no value access.
- **Detect**: bare `any` param that is always an array/object/function; `(...args: any)` rest params.

### Item 40 — Hide unsafe type assertions in well-typed functions
- **Rule**: Some functions have easy signatures and hard type-safe bodies (`cacheLast<T extends Function>(fn: T): T`; `shallowObjectEqual`). Put the unavoidable assertion *inside* the function (`as unknown as T`; `(b as any)[k]` right after checking `k in b`), keep the public signature sound. One contained, precondition-documented assertion beats the same assertion scattered across call sites.
- **Detect**: identical assertion pattern repeated at many call sites; a generic wrapper erroring "'(...args:any[]) => any' is not assignable to 'T'" and someone reaching for a signature-level `any`.

### Item 41 — Understand evolving any
- **Rule**: The one sanctioned exception to "types don't expand": with `noImplicitAny`, `const out = []` and `let x = null` start as *implicit* `any[]`/`any` and **evolve** with writes (`out.push(1)` → `number[]`; pushes of mixed types union; branch assignments union across branches; the try/catch `let val = null` pattern ends `number | null`). Reading one *before* any write errors ("implicitly has type 'any[]' in some locations"); writes inside callbacks don't evolve it (`forEach(i => out.push(...))` fails). Explicit `: any` never evolves. Prefer an explicit annotation or single-expression construction (items 23/27) — evolving any gives weaker checking.
- **Detect**: the exact error string above; empty-array init far from its pushes; hover showing `any[]` on one line and `number[]` later.

### Item 42 — Use `unknown` instead of `any` for values of unknown type
- **Rule**: `any`'s two powers — assignable *to* everything and *from* everything — are set-theoretically incoherent and disable the checker. **`unknown`** keeps the first property only: everything is assignable to it, but you can do *nothing* with it (no property access, no calls, no arithmetic) until you narrow via assertion, `instanceof`, or a user-defined guard (which must first prove `typeof v === 'object' && v !== null`). Use it for parser returns (`safeParseYAML(y): unknown`), grab-bag fields (GeoJSON `properties`), and double assertions (`as unknown as T` — a leaked `unknown` errors loudly; a leaked `any` spreads). A bare return-only generic `<T>(yaml: string): T` is a disguised assertion — return `unknown` instead. `{}` = everything but `null`/`undefined`; `object` = non-primitives; both rarely better than `unknown` post-TS3.0.
- **Detect**: `JSON.parse`-shaped function returning `any`; `<T>` used only in a return position; property access on freshly-parsed data with no validation step.

### Item 43 — Prefer type-safe approaches to monkey patching
- **Rule**: Don't hang data on `window`/`document`/DOM nodes/prototypes — it's global state with hidden coupling. If forced (legacy, library requirement): (a) **interface augmentation** `declare global { interface Document { /** … */ monkey: string } }` — typed, documented, autocompleted, but global in scope and can't model "assigned later" (consider `string | undefined`); or (b) a **narrower assertion type** `(document as MonkeyDocument).monkey = ...` — scope controlled by imports, and the per-use assertion is friction that encourages refactoring. `(document as any).monkey` loses spelling *and* type checks.
- **Detect**: assignment to a property that doesn't exist on a built-in type; `as any` on `window`/`document`; `RegExp.prototype.x = ...`.

### Item 44 — Track your type coverage to prevent regressions
- **Rule**: `noImplicitAny` doesn't end the story: `any`s persist via *explicit* annotations that outlive their reason (an `: any` return added when a util returned `any` — now it throws away real types) and enter *silently* via third-party declarations (`declare module 'my-module'` whole-module stubs; buggy @types worked around with assertions). Measure with `npx type-coverage` (percent of symbols not-`any`) and `--detail` (each `any`'s location); treat a coverage drop on a diff as a leak; periodically revisit old `any`s — their justification may be gone.
- **Detect**: bodyless `declare module`; stale `: any` returns whose callee is now typed; no coverage number tracked anywhere.

## ch-6 — Type Declarations and @types {#ch-6}

### Item 45 — Put TypeScript and @types in devDependencies
- **Rule**: Types don't exist at runtime → `typescript` and all `@types/*` belong in `devDependencies`, never `dependencies` (you publish JS; JS users shouldn't fetch types). Never install TypeScript system-wide — version skew across the team; run the project-local `npx tsc`.
- **Detect**: `@types/*` under `dependencies` in `package.json`; setup docs saying `npm install -g typescript`.

### Item 46 — The three versions involved in type declarations
- **Rule**: A dependency involves **three versions**: the library, its `@types`, and TypeScript. Match library and @types at major.minor (patch streams differ legitimately — @types patches fix declaration bugs). Failure modes → fixes: library updated, @types stale → new APIs error → update @types (or augment, or contribute); @types *ahead* of installed lib → checker approves calls that fail at runtime → align versions; @types needs newer TS → errors *inside* `.d.ts` → upgrade TS, pin `@types/x@ts3.1`, or stub; transitive @types conflict → duplicate/unmergeable declaration errors → `npm ls @types/foo`, reconcile. Publishing: **bundle types only if the library is written in TS** (tsc generates them); otherwise DefinitelyTyped — community maintenance, multi-version support, tested against new TS releases.
- **Detect**: type errors after a dependency bump with no code change; errors pointing into `node_modules/@types/...`.

### Item 47 — Export all types that appear in public APIs
- **Rule**: If a type appears in an exported signature it is *effectively public* — users can extract it anyway (`ReturnType<typeof getGift>`, `Parameters<typeof getGift>[0]`). Not exporting buys zero flexibility and costs users friction. Export them.
- **Detect**: exported function whose parameter/return types are module-private.

### Item 48 — Use TSDoc for API comments
- **Rule**: `/** … */` JSDoc/TSDoc comments (with `@param`, `@returns`, Markdown) are surfaced by editors at call sites; `//` comments are not. Document exported functions, classes, types, and *fields*. Never restate types in the docs (no `@param {string}` — item 30); keep them short.
- **Detect**: public API documented with line comments; type braces inside TSDoc in a `.ts` file.

### Item 49 — Provide a type for `this` in callbacks
- **Rule**: `this` is dynamically scoped (call-site-bound). If your API sets callbacks' `this`, model it with a **`this` parameter**: `fn: (this: HTMLElement, e: KeyboardEvent) => void` — the checker then enforces `fn.call(el, e)` (plain `fn(e)` errors on `this` context) and callback authors get a typed `this` (and are caught if they use an arrow function expecting it). Class callback footgun: a method reference loses its instance — bind in the constructor or use an arrow-function property.
- **Detect**: an API that invokes callbacks via `.call/.apply` with no `this` param in its declarations; runtime "Cannot read property … of undefined" from an unbound method passed as a handler.

### Item 50 — Prefer conditional types to overloaded declarations
- **Rule**: Overloads resolve one-at-a-time, so a *union-typed* argument matches none of them (`double(x: number|string)` fails both `(number)=>number` and `(string)=>string` overloads). A **conditional type** — `function double<T extends number|string>(x: T): T extends string ? string : number` — distributes over unions and covers single types and unions with one declaration. Read conditionals like a type-space ternary.
- **Detect**: growing overload ladder; call with a union argument erroring against the last overload.

### Item 51 — Mirror types to sever dependencies
- **Rule**: If your published types need only a fragment of another library's types (Node's `Buffer` → `interface CsvBuffer { toString(encoding: string): string }`), declare the structural subset locally instead of making every consumer install `@types/node`. Structural typing keeps real `Buffer`s assignable. Applies to test/production decoupling too (item 4's `DB` interface). If the mirrored surface grows large or essential, declare the real @types dependency instead.
- **Detect**: a web-facing library whose declarations import Node/framework types for one method; JS users asking why they need `@types/*`.

### Item 52 — Pitfalls of testing types
- **Rule**: Testing declarations *inside* the type system is fraught: merely calling the function checks almost nothing; assigning to a typed variable / `assertType<T>(x)` checks **assignability, not equality** — extra object properties pass, and a fewer-parameter function is assignable to a longer signature (JS callback convention). Test the callback's *parameter types and `this`* directly (non-arrow function; `Parameters<...>`/`ReturnType<...>` to split function types). Worst pitfall: `declare module 'x';` (whole-module `any`) passes every in-system test while destroying all safety — `any` is symmetric-assignable and nearly undetectable from within. Prefer an external textual tool: **dtslint** `$ExpectType` comments compare the *displayed* type (distinguishes `string` from `any`).
- **Detect**: a published declaration file with call-only "tests"; assertType helpers guarding an API; no dtslint/@ExpectType in a @types package.

## ch-7 — Writing and Running Your Code {#ch-7}

Governing principle: **TC39 defines the runtime; TypeScript innovates solely in type space.** The runtime features TS added before that policy are historical exceptions — avoid them so "TS = JS + erasable types" stays true.

### Item 53 — Prefer ECMAScript features to TypeScript features
- **Rule**: Avoid the four non-erasable/TS-only constructs:
  - **Enums** — number enums accept any number; `const enum` rewrites emit (build-tool-dependent); **string enums are nominally typed**, the sole non-structural type in the language, so JS callers pass `'vanilla'` happily while TS callers must import the enum. Use a **union of string literals** instead: same safety, same autocomplete, plain strings at runtime. ↔ contra `refactoring-typescript` ch-5, which reaches for outcome *enums*: in this monorepo both are sanctioned (sr-007), but Vanderkam's default is the literal union.
  - **Parameter properties** (`constructor(public name: string)`) — generate code, look unused, and mixed with declared fields hide the class's true shape. Use sparingly, never mixed.
  - **Namespaces / triple-slash `/// <reference>`** — pre-ES2015 module system; use `import`/`export`.
  - **Decorators** — non-standard (stage-2 era), Angular-only justification; liable to break.
- **Detect**: `enum`, `constructor(public …)`, `/// <reference`, `@decorator` (outside Angular) in a diff.

### Item 54 — Know how to iterate over objects
- **Rule**: `for (const k in obj)` types `k` as `string` — *correctly*, because any value assignable to the param may carry extra keys (item 4), and prototype pollution can add more. If the object is a local constant with a closed key set, declare `let k: keyof typeof obj` and index safely. For the general case use `Object.entries` and accept `[string, any]` — "hard to work with, but honest." Forcing `keyof T` onto a function parameter lies about the value type (`v: string|number` when a `Date` may arrive).
- **Detect**: "Element implicitly has an 'any' type because type … has no index signature" inside for-in; a `keyof` assertion on a structurally-open parameter.

### Item 55 — Understand the DOM hierarchy
- **Rule**: Know the containment chain `EventTarget ⊃ Node ⊃ Element ⊃ HTMLElement ⊃ HTML*Element` and the event chain `Event ⊃ UIEvent/MouseEvent/KeyboardEvent/…`. `currentTarget` is `EventTarget | null`; `getElementById` returns `HTMLElement | null` (specific-tag lookups like `querySelector('div')` do better). When you know the page, an assertion (`as HTMLDivElement`, `!` for null) is legitimate (item 9's canonical case). Prefer *inlining* handlers and precise event param types (`MouseEvent`) so context (item 26) supplies types. DOM declarations are generated from the spec (item 35).
- **Detect**: "Property 'clientX' does not exist on 'Event'"; "'value' does not exist on HTMLElement"; scattershot `!` on DOM lookups with no reasoning.

### Item 56 — Don't rely on `private` to hide information
- **Rule**: `private`/`protected` are type-system constructs — erased at emit and bypassable even in TS via `(obj as any).secret`. For real information hiding: **closures** in the constructor (truly private; costs per-instance method copies and blocks cross-instance access) or **`#private` fields** (runtime-enforced, WeakMap fallback on old targets). Security concerns go further still (prototype tampering).
- **Detect**: secrets/credentials in `private` fields; tests reading private state through `as any`.

### Item 57 — Use source maps to debug TypeScript
- **Rule**: You run generated JS, and it can diverge wildly from your source (async/await → state machines on old targets). Set `"sourceMap": true` and debug the original TS in the browser/Node debugger. Ensure bundler/minifier maps chain *back to TS*, not to intermediate JS. Don't ship inline-source maps if the source (comments, internal URLs) shouldn't be public.
- **Detect**: breakpoints being set in emitted JS; a `.js.map` that references generated JS as its "source".

### Item 58 — Write modern JavaScript
(Formally ch-8's opener; usable everywhere.) See ch-8 below.

## ch-8 — Migrating to TypeScript {#ch-8}

Evidence for the pitch: a 2017 study found ~15% of fixed JS bugs on GitHub were TypeScript-preventable; an Airbnb postmortem review put it at 38%. Strategy: gradual, measured, monotonic — experiment (item 59), coexist (60), convert in dependency order (61), then ratchet strictness (62).

### Item 58 — Write modern JavaScript first
- **Rule**: Modernizing JS *is* the first migration step — TS understands modern JS best, and tsc is your transpiler for old targets. Checklist: **ES modules** (`import`/`export`, never require/AMD/concat — module-by-module migration depends on it); **classes** over prototype manipulation (quick-fix exists); `let`/`const` over `var` (and function expressions over hoisted statements); `for-of`/`forEach` over C-style and especially `for-in`; **arrow functions** for lexical `this` (`noImplicitThis` checks it); compact literals + destructuring; **default params** (double as inference hints); **async/await** over promises/callbacks; drop `'use strict'` (TS's `alwaysStrict` is stricter and emits it for you).
- **Detect**: `require(...)`, `var`, `.prototype.method =`, callback pyramids in files slated for conversion.

### Item 59 — Use @ts-check and JSDoc to experiment
- **Rule**: Before converting, add `// @ts-check` to a JS file for an ultra-loose checker pass. Expect four error families: **undeclared globals** (declare them in a `types.d.ts` — the seed of your project declarations); **unknown libraries** (install `@types/jquery` etc. — you get library typings without migrating); **DOM element types** (JSDoc casts: `/** @type {HTMLInputElement} */(document.getElementById('age'))` — parens required); **inaccurate legacy JSDoc** (now actually checked — fix the lies). The quick-fix can infer JSDoc param types from usage (verify: it happily infers structurally-absurd shapes). Don't over-invest — the goal is `.ts`, not perfectly-annotated `.js`.
- **Detect**: a JS codebase evaluating TS; extensive-but-unenforced JSDoc.

### Item 60 — Use allowJs to mix TypeScript and JavaScript
- **Rule**: Large projects can't "stop the world." `allowJs` lets `.ts` and `.js` import each other (JS files get essentially no checking — that's the point). **Wire TS into build and test before converting any module**: bundler plugin (tsify/webpack), `ts-jest`, or the universal fallback `outDir` (emit JS beside/parallel to source and run the old chain over it). You need running tests as the safety net while renaming files.
- **Detect**: a migration PR that flips the build *and* converts modules simultaneously.

### Item 61 — Convert module by module up your dependency graph
- **Rule**: Adding types to a module surfaces errors in its *dependents*, so convert each module once by going **up the dependency graph**: third-party `@types` first (you depend on them, they don't depend on you), external-API types next (generate from specs, item 35), then leaf/utility modules upward, **tests last** (top of the graph — they keep passing throughout, unchanged). Visualize with `madge` (expect a utils/tickers-style cycle at the bottom). **Add types, don't refactor** — log smells (the 45-member god class you just made visible) for later. Expect three error families: *undeclared class members* (quick-fix adds them; then replace its `any` guesses); *values with changing types* (`const state = {}` then assignment — build all at once, item 23, or a temporary `as T`); *lost JSDoc enforcement* (`@ts-check`+JSDoc types stop applying in `.ts` — quick-fix copies JSDoc types into annotations; then delete the JSDoc, item 30).
- **Detect**: conversion PR that also "cleans up" logic; a module converted before its dependencies; JSDoc types left alongside real annotations.

### Item 62 — Migration isn't done until noImplicitAny is on
- **Rule**: Without `noImplicitAny`, wrong type declarations are *masked*: declare `indices: number[]` when reality is `[number, number][]`, and `r[0]` on a `number` still silently types `any` — no error anywhere. Ratchet strategy: enable `noImplicitAny` locally, drive the error count to zero committing fixes as you go, *then* commit the tsconfig flip. `strict: true` is the eventual destination; let the team acclimate first — `noImplicitAny` alone captures most of the value.
- **Detect**: a "fully migrated" repo with `noImplicitAny: false`; class members typed by guesswork that no usage has ever validated.

---

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| `as T` / `<T>x` on an object literal or expression | Prefer declaration `: T`; assertions skip conformance and excess-property checks | Assertion = "trust me", declaration = "verify me" | ch-2 |
| `x!` non-null assertion | Allowed only with knowledge the checker lacks; else write the null check | `!` is erased; wrong guess = runtime TypeError | ch-2 |
| `as unknown as T` / `as any as T` double assertion | Red flag: arbitrary conversion; justify or replace with validation; prefer the `unknown` form | Leaked `unknown` errors loudly; leaked `any` spreads silently | ch-2/ch-5 |
| `: any` on a variable, param, or return | Narrow to expression-level `as any`, use `any[]`/`{[k:string]:any}`/`(...args:any[])=>any`, or `unknown` | Scoped/returned `any` is contagious through callers | ch-5 |
| Function returning parsed/external data typed `any`, or bare return-only generic `<T>` | Return `unknown`; force callers to narrow (guard/assert) | Bare-generic return is a disguised assertion | ch-5 |
| `instanceof X` where `X` is an interface/type | Use a tagged union, `in` check, or a class — types are erased | No runtime value to check against | ch-1 |
| Interface with several union-typed props whose arms correlate | Convert to a tagged union of interfaces | Excludes invalid cross-products; enables narrowing | ch-4 |
| State type where flags/optionals can encode contradictions | Redesign as a tagged union of valid states only | Invalid-state-admitting inputs make consumers unimplementable | ch-4 |
| Return type full of optional fields/unions | Return the canonical strict type; keep loose `-Like` shapes for params only | Postel: liberal in, strict out | ch-4 |
| Function returns a struct/tuple of independently-nullable values | Make the aggregate nullable, members non-null | Null at the perimeter, not interleaved | ch-4 |
| Class fields `X \| null` populated by separate async calls | Static async factory awaits all; constructor takes complete data | 2^n null-combinations infect every method | ch-4 |
| Field's legal values documented in a comment | Union of string literals (not `enum`, not `string`) | Checkable, autocompletable, erases to plain JS | ch-4/ch-7 |
| `key: string` param used to index an object | `K extends keyof T` (and `T[K]` return) | Correct inferred value types; catches bad keys | ch-4 |
| `.then` chains / callback APIs in new code | `async/await`; any Promise-returning function declared `async` | Uniform async, try/catch, types flow | ch-3 |
| Cache/memo wrapper with a synchronous hit path | Make both paths async | Half-synchronous functions reorder observable state | ch-3 |
| `const out = []` + loop pushes, or `let x = null` + try/catch assign | Annotate explicitly or build in one functional expression | Evolving any gives weak checking, confusing errors | ch-5/ch-3 |
| Extract-variable refactor introduces type errors with no logic change | Add annotation or `as const`; you stripped inference context | Widening + context loss, not a real bug | ch-3 |
| Alias created (`const box = p.bbox`), original then checked | Check and use the alias consistently; prefer destructuring | Aliases break control-flow narrowing | ch-3 |
| Array param never mutated by the function | Declare `readonly T[]` | Catches mutations; accepts broader inputs | ch-2 |
| Object built field-by-field onto `{}` | Build all at once; spread to compose | A value's type is fixed at creation | ch-3 |
| Two hand-maintained types share fields; `-Update`/`-Partial` variants retyped | Derive with `extends`/`Pick`/`Partial`/mapped types | DRY applies in type space | ch-2 |
| Value must enumerate a type's properties (sync map, comparison fn) | Gate it with a mapped type over `keyof T` | New property = compile error at the decision point | ch-2 |
| Index signature over statically-knowable keys | `Record`/interface/mapped type; index signatures only for truly dynamic data | Index signatures allow wrong keys and require none | ch-2 |
| Precision-increasing typings change (tuples, arities) | Test against the spec + valid/invalid corpus; incomplete beats inaccurate | Uncanny valley: wrong precise types force user assertions | ch-4 |
| Types hand-written from a sample payload | Generate from the spec/schema (GraphQL, OpenAPI, @types) | Samples miss legal edge cases (GeometryCollection) | ch-4 |
| Structurally-compatible impostors possible (units, path kinds, sortedness) | Brand the type; produce only via constructors/guards | Nominal invariants atop structural typing | ch-4 |
| `@types/*` under `dependencies`, or globally-installed tsc | Move to devDependencies; project-local TypeScript | Types are dev-time only; version consistency | ch-6 |
| Type errors after a dependency bump; errors inside `.d.ts` | Diagnose as three-version skew (lib / @types / TS); realign | The version triple drifts independently | ch-6 |
| Exported function with unexported param/return types | Export them | Users extract them anyway (`ReturnType`, `Parameters`) | ch-6 |
| Overload ladder failing on a union-typed argument | Replace with a conditional type (distributes over unions) | Overloads resolve one-by-one | ch-6 |
| Published types import a heavy @types for one method | Mirror the structural fragment locally | Sever nonessential type dependencies | ch-6 |
| API sets callbacks' `this` | Add a `this` parameter to the callback type | Checker enforces call context; users get typed `this` | ch-6 |
| `enum` / parameter properties / triple-slash / decorators in a diff | Prefer ES equivalents (literal unions, explicit fields, imports); decorators only under Angular | TS should innovate in type space only | ch-7 |
| `obj[k]` inside `for-in` errors "no index signature" | `keyof typeof` for closed local objects; `Object.entries` otherwise | Parameters may structurally carry extra keys | ch-7 |
| Secret in a `private` class field | Closure or `#private`; `private` is erased and `as any`-bypassable | Type-level privacy isn't privacy | ch-7 |
| JS→TS conversion PR that also refactors | Split: types now, refactors logged for later | Two risk classes in one change defeat the safety net | ch-8 |
| Migration declared complete with `noImplicitAny` off | Not complete; ratchet errors to zero, then flip the flag | Loose mode masks wrong declarations entirely | ch-8 |

## Anti-patterns

- **Contagious any** — an `any` return type silently untypes every transitive caller. Cue: function without a return annotation whose body produces `any`; `type-coverage` drop on a diff. (ch-5)
- **Stringly typed code** — `string` where a literal union / `keyof` / `Date` belongs. Cue: comments enumerating legal values; adjacent same-typed string params (swap bugs compile). (ch-4)
- **Interface of unions** — correlated union-typed properties in one interface. Cue: arms that must move together; assertions in consumers. (ch-4)
- **Half-synchronous function** — sometimes calls back synchronously (cache hit), sometimes async. Cue: a callback invoked outside any async boundary in one branch. (ch-3)
- **Aspirational JSDoc / type-echo comments** — docs restating (or contradicting) types; "does not modify" prose instead of `readonly`. (ch-4/ch-6)
- **Uncanny-valley typings** — precise-but-wrong declarations forcing consumer assertions. Cue: downstream `as any` appearing after a "types improvement" PR. (ch-4)
- **Evolving-any accumulator** — `const out = []` mutated across a loop/callback. Cue: "implicitly has type 'any[]' in some locations". (ch-5)
- **Monkey patch on built-ins** — data hung on `window`/`document`/prototypes, papered over with `as any`. (ch-5)
- **Type/value space confusion** — `instanceof` on types; destructuring "annotations" that rename values. Cue: "only refers to a type, but is being used as a value"; "Duplicate identifier 'string'". (ch-1/ch-2)
- **Wrapper-object types** — `String`/`Number`/`Boolean` in annotations. (ch-2)
- **Declaration-merge surprise** — a second `interface X` block augmenting the first unintentionally; internal types left augmentable when they must not be. (ch-2)
- **Whole-module any stub** — `declare module 'foo';` left in place after real types exist; passes every in-system type test while destroying safety. (ch-5/ch-6)
- **Assignability-as-equality type tests** — `assertType<T>(x)` style checks that extra properties and fewer-arg functions sail through. (ch-6)
- **Refactor-during-migration** — design changes mixed into JS→TS conversion commits. (ch-8)

## Applicability & exemptions

- **Assertions are sometimes right.** DOM element identity (`getElementById('x') as HTMLDivElement`), externally-validated values, `unknown`-narrowing after a parse, and unsafe casts *hidden inside a well-typed function* (item 40) are sanctioned — don't flag every `as`/`!`. The bar: the author demonstrably knows something the checker cannot.
- **`any` is legitimate** during gradual migration (ch-8), for expression-scoped silencing of checker limitations, and inside well-typed wrappers. The rules govern *scope and containment*, not absolute prohibition.
- **Index signatures** are correct for genuinely dynamic keys (CSV columns, user-defined maps). Only flag them when the key set is statically knowable. (ch-2)
- **Strictness flags**: many rules presume `strict`/`noImplicitAny`/`strictNullChecks`. In a codebase mid-migration, their absence is a roadmap item, not a per-diff violation; per item 2, don't diagnose behavior without reading `tsconfig.json` first.
- **Enums**: the avoid-enums rule yields to codebase consistency; this monorepo's sr-007 explicitly allows enums *or* `as const` objects for status values — enforce the local standard, not the book's, but don't introduce `const enum` into bundler-built code. (ch-7)
- **Interface vs type** is convention-first: neither is wrong for plain object shapes; require consistency, and `interface` for published augmentable declaration files. (ch-2)
- **Postel asymmetry**: broad *parameter* unions/optionals are good design — only broad *return* types are the smell. Don't flag liberal inputs. (ch-4)
- **DOM/browser items** (55, parts of 43/59) don't apply to Node-only or non-browser code; item 55 says so explicitly.
- **Precision limits**: don't push type precision past what the spec guarantees or past usable error messages/autocomplete — acknowledged incompleteness (`unknown`, wider types) is the sanctioned fallback. (ch-4)
- **`for-in` string keys and extra-parameter callbacks are features, not bugs**: TS deliberately models JS's permissiveness (structural openness, fewer-arg function assignability). Rules that fight these (forcing `keyof` on open params) create false precision. (ch-7, ch-6)
- **Book vintage**: written against TypeScript 3.7 (2019). Superseded in detail — `#private` fields and optional chaining are now standard; template-literal types, `satisfies`, and TS 4/5 features postdate it — but the reasoning model (erasure, structural typing, sets-of-values, any-hygiene, Postel signatures) is stable. Verify any specific compiler behavior against current TS.

## Candidate lexicon rows

| function's return type is `any` (annotated or inferred), or a bare generic `<T>` used only in the return position | **No contagious any** — a returned `any` silently disables checking in every transitive caller; return a real type or `unknown` | Does anything escape this function as `any`? | blocker | review | src: effective-typescript ch-5 |
| parsed/external/boundary data (JSON, YAML, API payload) enters typed code | **`unknown` at the boundary** — type ingress as `unknown` and force a guard or assertion, because a declared type on unvalidated data is fiction | Where is the narrowing step between the wire and the typed world? | should | write | src: effective-typescript ch-5 |
| `as T`, `x!`, or `as unknown as T` added in a diff | **Assertions need a why** — prefer `: T` declarations; an assertion is only valid when the author knows something the checker cannot, and it skips excess-property checking | What does the author know here that TypeScript doesn't? | should | review | src: effective-typescript ch-2 |
| Promise-returning function implemented with `.then` chains, or declared without `async` | **Async all the way** — declare Promise-returning functions `async`; `async` guarantees the Promise contract and never double-wraps | Is every Promise producer in this diff an `async` function? | should | write | src: effective-typescript ch-3 |
| cache/memo/batch wrapper where one branch invokes the callback or resolves synchronously | **No half-synchronous functions** — a function must be always-sync or always-async; a synchronous fast path reorders callers' observable state | Do both branches cross the same microtask boundary? | blocker | review | src: effective-typescript ch-3 |
| interface has multiple union-typed or paired-optional properties whose values must correlate | **Union of interfaces, not interface of unions** — model each valid combination as its own tagged arm so invalid cross-pairings are unrepresentable | Could a value mix arm A's field with arm B's? | should | plan | src: effective-typescript ch-4 |
| state/config type admits flag combinations no code path should produce | **Valid states only** — redesign as a tagged union of exactly the legal states; consumers narrow instead of arbitrating contradictions | Which representable values must never occur? | should | plan | src: effective-typescript ch-4 |
| function returns independently-nullable fields, or class holds `X \| null` members filled by separate awaits | **Null at the perimeter** — one nullable aggregate with non-null members; construct objects only when data is complete | Is one field's nullness secretly correlated with another's? | should | write | src: effective-typescript ch-4 |
| `string`-typed field/param whose legal values are enumerable (often listed in a comment) | **Literal unions over string** — a union of string literals is checkable, autocompletable, and erases to plain JS (prefer over TS `enum`) | Could the checker reject a typo in this value today? | should | write | src: effective-typescript ch-4 |
| `const out = []` / `let x = null` later mutated across a loop, branch, or callback | **Don't lean on evolving any** — annotate the accumulator or build the value in one functional expression | What is this variable's type on the line it's declared? | judgment | write | src: effective-typescript ch-5 |
| new named object type added, or a second `interface X` block appears for an existing name | **type/interface by convention and augmentability** — follow project style; `interface` only where declaration merging is wanted (published APIs), `type` where augmentation would be a bug | Should a consumer be able to merge fields into this type? | judgment | review | src: effective-typescript ch-2 |
| types hand-written for a format/API that has a spec or schema (OpenAPI, GraphQL, GeoJSON, DOM) | **Generate from the spec, not from data** — sample-derived types miss legal edge cases the spec guarantees | What does the spec allow that our examples never showed? | should | plan | src: effective-typescript ch-4 |
