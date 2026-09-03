VERDICT: FAIL

NOTE: `npx vitest run js/admin --reporter=basic` cannot start on Vitest 4.1.5 (`Failed to load custom Reporter from basic`; built-ins are default/agent/minimal/blob/verbose/dot/json/tap/tap-flat/junit/tree/hanging-process/github-actions). This evidence is from `./node_modules/.bin/vitest run js/admin --reporter=verbose`. EXIT=1. HEAD=4d83a8270a116ba779b3d7098ed4f08860d57bb1.

 Test Files  6 failed | 230 passed (236)
      Tests  15 failed | 2969 passed (2984)
   Duration  367.53s (transform 8.81s, setup 43.13s, import 35.55s, tests 146.47s, environment 104.16s)

## FAILING FILES
js/admin/api/__tests__/refreshRestNonce.test.ts
js/admin/utils/__tests__/logger.test.ts
js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx
js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts
js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx
js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx

## FAILING TESTS

⎯⎯⎯⎯⎯⎯ Failed Tests 15 ⎯⎯⎯⎯⎯⎯⎯

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

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/15]⎯

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

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[2/15]⎯

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

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[3/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > shows a friendly inline message when merge rejects a self-target request
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:773:3
    771|   });
    772|
    773|   it('shows a friendly inline message when merge rejects a self-target…
       |   ^
    774|     (api.mergeCluster as Mock).mockRejectedValueOnce(
    775|       new Error(

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[4/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > shows undo when merge completes and reverts on request
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:830:3
    828|   });
    829|
    830|   it('shows undo when merge completes and reverts on request', async (…
       |   ^
    831|     const mergeDeferred = createDeferred<unknown>();
    832|     const revertDeferred = createDeferred<unknown>();

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[5/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > renders face thumbnail when media_url is provided
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:923:3
    921|   });
    922|
    923|   it('renders face thumbnail when media_url is provided', async () => {
       |   ^
    924|     const identityWithMediaUrl = {
    925|       ...baseIdentity,

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[6/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > allows clicking the unlabeled text to start editing
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:946:3
    944|   });
    945|
    946|   it('allows clicking the unlabeled text to start editing', async () =…
       |   ^
    947|     const unlabeled = {
    948|       ...baseIdentity,

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[7/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > allows unlinking an identity (wrong person) only for singletons
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:976:3
    974|   });
    975|
    976|   it('allows unlinking an identity (wrong person) only for singletons'…
       |   ^
    977|     const reassignDeferred = createDeferred<unknown>();
    978|     (api.reassignClusterIdentity as Mock).mockReturnValue(reassignDefe…

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[8/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > allows splitting a cluster
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:1028:3
    1026|   });
    1027|
    1028|   it('allows splitting a cluster', async () => {
       |   ^
    1029|     const splitDeferred = createDeferred<unknown>();
    1030|     (api.splitCluster as Mock).mockReturnValue(splitDeferred.promise);

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[9/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > issues exactly one batched suggestions fetch at projection depth for N unlabeled cards
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:1087:5
    1085|       }));
    1086|
    1087|     it('issues exactly one batched suggestions fetch at projection dep…
       |     ^
    1088|       const identities = makeUnlabeled(5);
    1089|       await renderWithClient(<IdentityClusterList identities={identiti…

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[10/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > resolves an inline prompt on every one of 60 unlabeled cards from a single batch
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:1103:5
    1101|     });
    1102|
    1103|     it('resolves an inline prompt on every one of 60 unlabeled cards f…
       |     ^
    1104|       const identities = makeUnlabeled(60);
    1105|       // Several identities carry >=2 pending suggestions (guards the …

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[11/15]⎯

 FAIL  js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > renders nothing for an identity absent from the keyed envelope (empty-match)
Error: Test timed out in 5000ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:1128:5
    1126|     });
    1127|
    1128|     it('renders nothing for an identity absent from the keyed envelope…
       |     ^
    1129|       const identities = makeUnlabeled(2);
    1130|       vi.mocked(api.fetchIdentitiesSuggestions).mockResolvedValue({

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[12/15]⎯

 FAIL  js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts > isAbortError > treats non-DOMException TimeoutError name as abort [CARD-24]
AssertionError: expected false to be true // Object.is equality

- Expected
+ Received

- true
+ false

 ❯ js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts:36:31
     34|     const err = new Error('The operation timed out.');
     35|     err.name = 'TimeoutError';
     36|     expect(isAbortError(err)).toBe(true);
       |                               ^
     37|   });
     38|

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[13/15]⎯

 FAIL  js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx > useClusterSuggestionsLoader > findClusterByLabel short-circuits non-DOMException TimeoutError abort [CARD-24]
AssertionError: expected [ { ts: 1788394406993, …(4) } ] to have a length of +0 but got 1

- Expected
+ Received

- 0
+ 1

 ❯ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx:184:65
    182|     await expect(result.current.findClusterByLabel('Alice')).resolves.…
    183|     expect(consoleWarn).not.toHaveBeenCalled();
    184|     expect(records.filter((record) => record.level === 'warn')).toHave…
       |                                                                 ^
    185|
    186|     consoleWarn.mockRestore();

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[14/15]⎯

 FAIL  js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx > useLiveReviewTarget > probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]
AssertionError: expected 'live' not to be 'live' // Object.is equality

Ignored nodes: comments, script, style
[36m<html>[39m
  [36m<head />[39m
  [36m<body>[39m
    [36m<div />[39m
  [36m</body>[39m
[36m</html>[39m
 ❯ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx:233:41
    231|
    232|     await waitFor(() => {
    233|       expect(result.current.status).not.toBe('live');
       |                                         ^
    234|       expect(result.current.error).not.toBeNull();
    235|     });
 ❯ runWithExpensiveErrorDiagnosticsDisabled node_modules/@testing-library/dom/dist/config.js:47:12
 ❯ checkCallback node_modules/@testing-library/dom/dist/wait-for.js:124:77
 ❯ Timeout.checkRealTimersCallback node_modules/@testing-library/dom/dist/wait-for.js:118:16

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[15/15]⎯

## LOG TAIL

```
+ false

 ❯ js/admin/pages/workbench/identity-clusters/__tests__/clusterMutationUtils.test.ts:36:31
     34|     const err = new Error('The operation timed out.');
     35|     err.name = 'TimeoutError';
     36|     expect(isAbortError(err)).toBe(true);
       |                               ^
     37|   });
     38|

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[13/15]⎯

 FAIL  js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx > useClusterSuggestionsLoader > findClusterByLabel short-circuits non-DOMException TimeoutError abort [CARD-24]
AssertionError: expected [ { ts: 1788394406993, …(4) } ] to have a length of +0 but got 1

- Expected
+ Received

- 0
+ 1

 ❯ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx:184:65
    182|     await expect(result.current.findClusterByLabel('Alice')).resolves.…
    183|     expect(consoleWarn).not.toHaveBeenCalled();
    184|     expect(records.filter((record) => record.level === 'warn')).toHave…
       |                                                                 ^
    185|
    186|     consoleWarn.mockRestore();

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[14/15]⎯

 FAIL  js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx > useLiveReviewTarget > probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]
AssertionError: expected 'live' not to be 'live' // Object.is equality

Ignored nodes: comments, script, style
[36m<html>[39m
  [36m<head />[39m
  [36m<body>[39m
    [36m<div />[39m
  [36m</body>[39m
[36m</html>[39m
 ❯ js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx:233:41
    231|
    232|     await waitFor(() => {
    233|       expect(result.current.status).not.toBe('live');
       |                                         ^
    234|       expect(result.current.error).not.toBeNull();
    235|     });
 ❯ runWithExpensiveErrorDiagnosticsDisabled node_modules/@testing-library/dom/dist/config.js:47:12
 ❯ checkCallback node_modules/@testing-library/dom/dist/wait-for.js:124:77
 ❯ Timeout.checkRealTimersCallback node_modules/@testing-library/dom/dist/wait-for.js:118:16

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[15/15]⎯


 Test Files  6 failed | 230 passed (236)
      Tests  15 failed | 2969 passed (2984)
   Start at  00:10:05
   Duration  367.53s (transform 8.81s, setup 43.13s, import 35.55s, tests 146.47s, environment 104.16s)
```
