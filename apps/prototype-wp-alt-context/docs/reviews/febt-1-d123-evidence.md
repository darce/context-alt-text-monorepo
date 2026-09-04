# HEAD:

`e58c4862cc7c570d079a89b3964fd5213676c90d`

# INSTALL:

Command: `npm ci --ignore-scripts && ls -la ./node_modules/.bin/vitest`

```text
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@2.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me

added 648 packages in 8s

173 packages are looking for funding
  run `npm fund` for details
lrwxrwxrwx 1 gate gate 20 Sep  3 04:49 ./node_modules/.bin/vitest -> ../vitest/vitest.mjs
EXIT_CODE=0
```

# TASK 1 EXPERIMENT:

Temporary diff:

```diff
@@ -403,7 +403,7 @@ export const fetchApi = async <T>(endpoint: string, options: HTTPOptions = {}):
 export const fetchRequiredApi = async <T>(endpoint: string, options: HTTPOptions = {}): Promise<T> => {
   const payload = await fetchApi<T>(endpoint, options);
   if (payload === undefined) {
-    throwAsAppError(new Error(`Request to ${endpoint} succeeded but returned an empty response body.`));
+    throw new Error(`Request to ${endpoint} succeeded but returned an empty response body.`);
   }
   return payload;
 };
```

Before, with `throwAsAppError`:

```text
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

js/admin/utils/__tests__/http.test.ts(740,20): error TS2339: Property 'stack' does not exist on type 'AppError'.
  Property 'stack' does not exist on type 'AppErrorBase<"http"> & { readonly status: number; readonly endpoint: string; readonly retryAfterMs?: number | undefined; }'.
js/admin/utils/__tests__/http.test.ts(741,20): error TS2339: Property 'stack' does not exist on type 'AppError'.
  Property 'stack' does not exist on type 'AppErrorBase<"http"> & { readonly status: number; readonly endpoint: string; readonly retryAfterMs?: number | undefined; }'.
js/admin/utils/__tests__/http.test.ts(742,7): error TS2322: Type 'AppError' is not assignable to type 'Error'.
  Property 'name' is missing in type 'AppErrorBase<"http"> & { readonly status: number; readonly endpoint: string; readonly retryAfterMs?: number | undefined; }' but required in type 'Error'.
js/admin/utils/http.ts(408,3): error TS2322: Type 'Awaited<T> | undefined' is not assignable to type 'T'.
  'T' could be instantiated with an arbitrary type which could be unrelated to 'Awaited<T> | undefined'.
EXIT_CODE=2
```

After, with the temporary bare throw:

```text
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

js/admin/utils/__tests__/http.test.ts(740,20): error TS2339: Property 'stack' does not exist on type 'AppError'.
  Property 'stack' does not exist on type 'AppErrorBase<"http"> & { readonly status: number; readonly endpoint: string; readonly retryAfterMs?: number | undefined; }'.
js/admin/utils/__tests__/http.test.ts(741,20): error TS2339: Property 'stack' does not exist on type 'AppError'.
  Property 'stack' does not exist on type 'AppErrorBase<"http"> & { readonly status: number; readonly endpoint: string; readonly retryAfterMs?: number | undefined; }'.
js/admin/utils/__tests__/http.test.ts(742,7): error TS2322: Type 'AppError' is not assignable to type 'Error'.
  Property 'name' is missing in type 'AppErrorBase<"http"> & { readonly status: number; readonly endpoint: string; readonly retryAfterMs?: number | undefined; }' but required in type 'Error'.
EXIT_CODE=2
```

Verdict: **(A) CONFIRMED**. TS2322 at `http.ts:408` disappears when the branch uses a bare throw, proving the issue is never-return CFA rather than generic `Awaited<T>` friction.

# TASK 1 REVERTED:

Command: `git checkout -- js/admin/utils/http.ts && git diff --stat && git status --short`

```text
(no output; working tree clean)
EXIT_CODE=0
```

# D1 DIFF:

```diff
diff --git a/apps/prototype-wp-alt-context/js/admin/utils/logger.ts b/apps/prototype-wp-alt-context/js/admin/utils/logger.ts
index 812ef5f..f55b767 100644
--- a/apps/prototype-wp-alt-context/js/admin/utils/logger.ts
+++ b/apps/prototype-wp-alt-context/js/admin/utils/logger.ts
@@ -135,12 +135,12 @@ const projectBoundaryError = (value: Error): FlattenedError | null => {
 };
 
 const flattenCause = (cause: unknown): unknown => {
-  if (isAppError(cause)) {
-    return projectAppError(cause);
-  }
   if (cause instanceof Error) {
     return flattenError(cause, false);
   }
+  if (isAppError(cause)) {
+    return projectAppError(cause);
+  }
   if (cause === null || typeof cause !== 'object') {
     return cause;
   }
@@ -162,12 +162,12 @@ const flattenError = (value: Error, includeCause: boolean): FlattenedError => {
 };
 
 const flattenFieldValue = (value: unknown): unknown => {
-  if (isAppError(value)) {
-    return projectAppError(value);
-  }
   if (value instanceof Error) {
     return flattenError(value, true);
   }
+  if (isAppError(value)) {
+    return projectAppError(value);
+  }
   return value;
 };
```

# D1 RESULT:

The two named red tests passed, but the required whole-file run exposed one regression. Verbatim tail:

```text
 FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > AppError field values flatten to a tagged safe projection [O-05][REF-19]
AssertionError: expected { name: 'HTTPError', …(3) } to deeply equal { tag: 'http', …(3) }

- Expected
+ Received

  {
    "endpoint": "/jobs",
    "message": "HTTP 500",
+   "name": "HTTPError",
    "status": 500,
-   "tag": "http",
  }

 ❯ js/admin/utils/__tests__/logger.test.ts:452:37
    450|     createLogger('http').error('classified', { error: classified });
    451|
    452|     expect(records[0].fields.error).toEqual({
       |                                     ^
    453|       tag: 'http',
    454|       message: 'HTTP 500',

 Test Files  1 failed (1)
      Tests  1 failed | 24 passed (25)
   Duration  1.10s (transform 191ms, setup 241ms, import 166ms, tests 45ms, environment 465ms)

EXIT_CODE=1
```

Root cause of the newly red test: its purported plain-object fixture is `classifyError(leakingHttpError())`. `HTTPError` now has `_tag = 'http'`, so `classifyError` immediately returns the live `HTTPError` instance through its first `isAppError` branch. The prescribed Error-first logger behavior therefore correctly produces a name-shaped boundary projection. A genuinely plain-object AppError was not exercised by this test.

# D2 DIFF:

```diff
@@ -92,9 +92,9 @@ const normalizeOptionalString = (value: unknown): string | undefined =>
-const softNonEmptyString = (value: unknown, field: string): string => {
+const softNonEmptyString = (value: unknown, field: string, requestLog: Logger): string => {
   if (typeof value !== 'string' || value.trim() === '') {
-    configLog().warn(
+    requestLog.warn(
@@ -103,6 +103,7 @@ const softNonEmptyString = (value: unknown, field: string): string => {
 export const normalizeConfig = (raw: ApiConfig): NormalizedConfig => {
+  const requestLog = configLog().withRequest();
@@ -113,8 +114,8 @@ export const normalizeConfig = (raw: ApiConfig): NormalizedConfig => {
-    nonce: softNonEmptyString(raw.nonce, 'nonce'),
-    ajaxUrl: softNonEmptyString(raw.ajaxUrl, 'ajaxUrl'),
+    nonce: softNonEmptyString(raw.nonce, 'nonce', requestLog),
+    ajaxUrl: softNonEmptyString(raw.ajaxUrl, 'ajaxUrl', requestLog),
```

# D2 RESULT:

Not run because the Task 2 instructions require stopping immediately if any previously passing logger test turns red. No shared-requestId assertion was added for the same reason.

# D3 DIFF:

```diff
diff --git a/apps/prototype-wp-alt-context/js/admin/utils/http.ts b/apps/prototype-wp-alt-context/js/admin/utils/http.ts
@@ -403,7 +403,7 @@ export const fetchApi = async <T>(endpoint: string, options: HTTPOptions = {}):
   const payload = await fetchApi<T>(endpoint, options);
   if (payload === undefined) {
-    throwAsAppError(new Error(`Request to ${endpoint} succeeded but returned an empty response body.`));
+    return throwAsAppError(new Error(`Request to ${endpoint} succeeded but returned an empty response body.`));
   }
diff --git a/apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts b/apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts
@@ -733,6 +733,9 @@ describe('fetchApi throw boundary emits tagged Errors [FEBT1-W2A-01]', () => {
       expect(error).toBeInstanceOf(Error);
       expect(isAppError(error)).toBe(true);
+      if (!(error instanceof Error)) {
+        throw new Error('expected thrown value to be an Error instance');
+      }
       if (!isAppError(error)) {
```

The D3 implementation uses `return throwAsAppError(...)`: `never` is assignable to the generic return type and the explicit return makes the branch terminal without relying on the const-arrow never-CFA exception confirmed by Task 1. Runtime behavior remains a throw.

# D3 RESULT:

Not run because the Task 2 instructions require stopping immediately on the logger regression.

# TYPECHECK:

Final typecheck not run because the Task 2 instructions require stopping immediately on the logger regression. The pre-edit baseline had 4 errors, quoted under TASK 1 EXPERIMENT.

# LINT:

Not run because the Task 2 instructions require stopping immediately on the logger regression. `git diff --check` passed, and the source diff contains none of the forbidden casts or suppression comments.

# REGRESSION:

Not run because the Task 2 instructions require stopping immediately on the logger regression.

# VERDICT:

PARTIAL — the decisive experiment confirmed (A), both named D1 failures cleared, but logger.test.ts remains red: `AssertionError: expected { name: 'HTTPError', …(3) } to deeply equal { tag: 'http', …(3) }` in the mislabeled plain-object AppError test; D2/D3 were implemented but not verified because the brief explicitly requires stopping on this regression.
