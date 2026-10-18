# HEAD:

`0ccf1c69e6c69274052fb47c9e40b1979ea91927`

# INSTALL:

Command:

```text
npm ci --ignore-scripts
```

Verbatim outcome:

```text
npm warn deprecated abab@2.0.6: Use your platform's native atob() and btoa() methods instead
npm warn deprecated whatwg-encoding@0.0.0: Use @exodus/bytes instead for a more spec-conformant and faster implementation
npm warn deprecated domexception@4.0.0: Use your platform's native DOMException instead
npm warn deprecated node-domexception@1.0.0: Use your platform's native DOMException instead
npm warn deprecated glob@10.5.0: Old versions of glob are not supported, and contain widely publicized security vulnerabilities, which have been fixed in the current version. Please update. Support for old versions may be purchased (at exorbitant rates) by contacting i@izs.me

added 648 packages in 13s

173 packages are looking for funding
  run `npm fund` for details
```

Note: the emitted `whatwg-encoding` warning reported version `0.0.0` in this sandbox.

# TASK 1 DIFF:

```diff
diff --git a/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts b/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts
index c6c31a0..175b573 100644
--- a/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts
+++ b/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts
@@ -83,6 +84,7 @@ export const getInvalidTargetClusterMessage = (label: string): string =>
 export const getClusterMutationUserError = (error: unknown, label = 'that label'): ClusterMutationUserError => {
   const classified = classifyError(error);
   const code = getClusterErrorCode(error);
+  const rawMessage = error instanceof Error ? error.message : '';
 
   if (classified._tag === 'auth_expired') {
     return {
@@ -116,7 +118,7 @@ export const getClusterMutationUserError = (error: unknown, label = 'that label'
     };
   }
 
-  if (code === 'projection_not_ready') {
+  if (code === 'projection_not_ready' || (code === null && isProjectionNotReadyError(rawMessage))) {
     return {
       kind: 'projection_not_ready',
       message: getProjectionNotReadyMessage(),
@@ -124,7 +126,7 @@ export const getClusterMutationUserError = (error: unknown, label = 'that label'
     };
   }
 
-  if (code === 'invalid_target_cluster_id') {
+  if (code === 'invalid_target_cluster_id' || (code === null && isInvalidTargetClusterError(rawMessage))) {
     return {
       kind: 'invalid_target',
       message: getInvalidTargetClusterMessage(label),
```

# TASK 1 RESULT:

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx --reporter=verbose
```

Verbatim tail (24 passed, 0 failed):

```text
 ✓ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > renders nothing for an identity absent from the keyed envelope (empty-match) 29ms

 Test Files  1 passed (1)
      Tests  24 passed (24)
   Start at  04:24:44
   Duration  4.67s (transform 1.18s, setup 242ms, import 1.62s, tests 2.19s, environment 451ms)
```

# TASK 2 DIFF:

```diff
diff --git a/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts b/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts
index c6c31a0..175b573 100644
--- a/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts
+++ b/apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts
@@ -1,6 +1,7 @@
 import { __, sprintf } from '@wordpress/i18n';
 
 import { classifyError, toUserMessage } from '../../../utils/appError';
+import { isAbortOrTimeout } from '../../../utils/retryPolicy';
 
 export const CLUSTER_MUTATION_ERROR_COPY = {
   timeout: __('The server took too long to respond — try again', 'alt-context'),
@@ -33,7 +34,7 @@ export interface ClusterMutationUserError {
 
 export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
 
-export const isAbortError = (err: unknown): boolean => classifyError(err)._tag === 'abort';
+export const isAbortError = (err: unknown): boolean => isAbortOrTimeout(err);
 
 const readStringField = (value: unknown, key: string): string | null => {
   if (typeof value !== 'object' || value === null || !Object.hasOwn(value, key)) {
```

# TASK 2 RESULT:

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx --reporter=verbose
```

Verbatim tail (12 passed, 0 failed):

```text
 ✓ js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts > getClusterMutationUserError [FEBT1-W2A-04] > maps HTTP 409 via status, never substring, with reload recovery 1ms

 Test Files  2 passed (2)
      Tests  12 passed (12)
   Start at  04:24:56
   Duration  2.54s (transform 335ms, setup 577ms, import 385ms, tests 137ms, environment 1.10s)
```

# TYPECHECK:

Script name and command: `typecheck` via `npm run typecheck`.

Verbatim result (exit 2):

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
```

# UNDIAGNOSED-1:

`refreshRestNonce (UXP-NET-2 slice 1) > missing ajaxUrl fails SOFT: config stays usable, only refresh degrades (UXPNET2-BR-02) [TEST-15]`

```text
 FAIL  js/admin/api/__tests__/refreshRestNonce.test.ts > refreshRestNonce (UXP-NET-2 slice 1) > missing ajaxUrl fails SOFT: config stays usable, only refresh degrades (UXPNET2-BR-02) [TEST-15]
AssertionError: expected "warn" to be called with arguments: [ StringContaining "ajaxUrl", …(1) ]

Received:

  1st warn call:

  [
-   StringContaining "ajaxUrl",
-   ObjectContaining {
-     "requestId": Any<String>,
-   },
+   "[alt-context/api.config] AltContextAdmin configuration field \"ajaxUrl\" is missing or empty; dependent features degrade.",
  ]


Number of calls: 1

 ❯ js/admin/api/__tests__/refreshRestNonce.test.ts:158:18
    156|     expect(config.nonce).toBe('abc');
    157|     expect(config.ajaxUrl).toBe('');
    158|     expect(warn).toHaveBeenCalledWith(
       |                  ^
    159|       expect.stringContaining('ajaxUrl'),
    160|       expect.objectContaining({ requestId: expect.any(String) }),
```

# UNDIAGNOSED-2:

`boundary error redaction [O-03][O-05] > characterises exact LogRecord.fields.error for HTTPError, ResponseParseError, and NonceRefreshFailedError [W2-L5][TEST-15]`

```text
 FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > characterises exact LogRecord.fields.error for HTTPError, ResponseParseError, and NonceRefreshFailedError [W2-L5][TEST-15]
AssertionError: expected { tag: 'http', …(3) } to deeply equal { name: 'HTTPError', …(3) }

- Expected
+ Received

  {
    "endpoint": "/jobs",
    "message": "HTTP 500",
-   "name": "HTTPError",
    "status": 500,
+   "tag": "http",
  }

 ❯ js/admin/utils/__tests__/logger.test.ts:347:37
    345|
    346|     expect(records).toHaveLength(3);
    347|     expect(records[0].fields.error).toEqual({
       |                                     ^
    348|       name: 'HTTPError',
    349|       message: 'HTTP 500',
```

# UNDIAGNOSED-3:

`boundary error redaction [O-03][O-05] > HTTPError message secrets are absent from the serialized record [O-03][REF-19]`

```text
 FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > HTTPError message secrets are absent from the serialized record [O-03][REF-19]
AssertionError: expected { tag: 'http', …(3) } to deeply equal ObjectContaining{…}

- Expected
+ Received

- ObjectContaining {
+ {
+   "endpoint": "/jobs",
    "message": "HTTP 500",
-   "name": "HTTPError",
    "status": 500,
+   "tag": "http",
  }

 ❯ js/admin/utils/__tests__/logger.test.ts:385:23
    383|     expect(serialized).not.toContain(error.bodyPreview);
    384|     const projected = records[0].fields.error as { name?: string; mess…
    385|     expect(projected).toEqual(
       |                       ^
    386|       expect.objectContaining({
    387|         name: 'HTTPError',
```

# VERDICT:

BOTH FIXES GREEN — GATE-05 24/24 and CARD-24 clear
