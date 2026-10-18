# FEBT-1 lane f6a (teststrength) report

Lane: `febt-1-f6a-teststrength`  
Branch: `feature/febt-1-f6a`  
Closed: FEBT1-W2C-14, FEBT1-W2C-13. Tests only. Production files untouched.

`git diff` against the lane base shows **zero** production-file changes (`http.ts`, `retryPolicy.ts`, and every other non-test path). Changed files:

- `apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts`
- `apps/prototype-wp-alt-context/js/admin/utils/__tests__/retryPolicy.test.ts`
- `docs/reviews/febt-1-f6a-report.md`

Canon applied: TEST-06, TEST-15, TEST-17, REF-29, sr-001.  
Scoped gate only: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/utils/__tests__/http.test.ts js/admin/utils/__tests__/retryPolicy.test.ts`  
Did not run `npm run test`, `npm run typecheck`, or `npm run lint`. Did not relax any lint rule.

---

## FEBT1-W2C-14 — 205 no-body branch was untested

**Test:** `returns undefined for 205 responses even when a JSON body is present`

Production `parseSuccessBody` returns `undefined` for **both** 204 and 205. The existing 204 case used `new Response(null, { status: 204 })`. A copied empty-body 205 case would still pass after dropping the 205 clause, because empty text also returns `undefined` (TEST-17). Fetch forbids a body on status 205 (`TypeError: Response constructor: Invalid response status code 205`), so the pin uses a real 205 Response plus `text()` mocked to JSON.

**Mutant (verbatim):**

```ts
// 204/205 intentionally return no body.
if (response.status === 204) {
  return undefined;
}
```

(was `response.status === 204 || response.status === 205`)

### RED (mutant applied, production then reverted)

```
 ❯ js/admin/utils/__tests__/http.test.ts (45 tests | 1 failed) 108ms
     ✓ returns undefined for 204 responses 4ms
     × returns undefined for 205 responses even when a JSON body is present 10ms
...
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 23ms

 Test Files  1 failed | 1 passed (2)
      Tests  1 failed | 71 passed (72)

 FAIL  js/admin/utils/__tests__/http.test.ts > fetchApi > returns undefined for 205 responses even when a JSON body is present
AssertionError: expected { ignored: true } to be undefined

- Expected:
undefined

+ Received:
{
  "ignored": true,
}

 ❯ js/admin/utils/__tests__/http.test.ts:72:20
     70|     const result = await fetchApi<{ ignored: boolean }>('http://exampl…
     71|
     72|     expect(result).toBeUndefined();
```

The 204 test stayed green. The 205 JSON pin is the discriminating assertion (TEST-15).

### GREEN (mutant reverted)

```
 ✓ js/admin/utils/__tests__/http.test.ts (45 tests) 111ms
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 22ms

 Test Files  2 passed (2)
      Tests  72 passed (72)
```

---

## FEBT1-W2C-13 — retry bound defined only in terms of itself

**Test:** `exports a hard ceiling of exactly 3 retry attempts (RES-06)`  
**Kept:** `is bounded: stops once RETRY_MAX_ATTEMPTS is reached even for a retryable class`

**Actual constant value read from source:** `export const RETRY_MAX_ATTEMPTS = 3;` in `retryPolicy.ts`. Not assumed from finding text.

The old bound test used only `RETRY_MAX_ATTEMPTS - 1` and `RETRY_MAX_ATTEMPTS`. Changing the constant changed the test's meaning silently. Pattern copied from `clusterAutoRetry.test.ts` (`expect(CLUSTER_RETRY_MAX_ATTEMPTS).toBe(3)`).

**Also pinned in this same commit:** `expect(MAX_RETRY_DELAY_MS).toBe(30_000)` in `exports a 30s retry delay ceiling`. Several delay tests already used the `30_000` literal, but `clamps Retry-After: 3600 through the shared ceiling at the retry-delay call site [E-01]` still compared against `MAX_RETRY_DELAY_MS` itself. Same self-referential smell, same file, same commit.

**Mutant (verbatim):**

```ts
export const RETRY_MAX_ATTEMPTS = 4;
```

(was `= 3`)

### RED (mutant applied, production then reverted)

```
 ✓ js/admin/utils/__tests__/http.test.ts (45 tests) 104ms
 ❯ js/admin/utils/__tests__/retryPolicy.test.ts (29 tests | 1 failed) 30ms
     ...
     × exports a hard ceiling of exactly 3 retry attempts (RES-06) 8ms
     ✓ is bounded: stops once RETRY_MAX_ATTEMPTS is reached even for a retryable class 0ms
     ...

 Test Files  1 failed | 1 passed (2)
      Tests  1 failed | 73 passed (74)

 FAIL  js/admin/utils/__tests__/retryPolicy.test.ts > shouldRetryRequest > exports a hard ceiling of exactly 3 retry attempts (RES-06)
AssertionError: expected 4 to be 3 // Object.is equality

- Expected
+ Received

- 3
+ 4

 ❯ js/admin/utils/__tests__/retryPolicy.test.ts:106:32
    106|     expect(RETRY_MAX_ATTEMPTS).toBe(3);
```

The old bound test stayed green — that is the defect. Only the literal pin failed (TEST-15, TEST-06).

### GREEN (mutant reverted)

```
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (29 tests) 23ms
 ✓ js/admin/utils/__tests__/http.test.ts (45 tests) 102ms

 Test Files  2 passed (2)
      Tests  74 passed (74)
```

---

## Final scoped gate

```
cd apps/prototype-wp-alt-context && npx vitest run js/admin/utils/__tests__/http.test.ts js/admin/utils/__tests__/retryPolicy.test.ts
```

74 passed (45 http + 29 retryPolicy). Both mutants reverted before commit. Two separate commits; neither squashed.
