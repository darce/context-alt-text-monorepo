# Lens B — observability
**Verdict:** IN PROGRESS

Tree: `git rev-parse HEAD` at review start after stub = `2c73a3b20bc9a6229e3d410cd3781ab1d2aefd80` (sandbox history-stripped `master`; pinned `82bb245a0` is not in this clone). All excerpts below are from files read at that tree.

### F-1 Module-level requestId is a logger-instance UUID, not a request/job/session id
- severity: medium
- file: apps/prototype-wp-alt-context/js/admin/utils/logger.ts:181
- rule: OBS-03
- evidence: `bindCorrelationId` mints `requestId` once per `createLogger()` call, then every later `log.*` from that instance reuses it. Module-scope loggers therefore share one import-time UUID across unrelated user actions, and distinct modules cannot be grepped as one transaction:

```
const bindCorrelationId = (fields: LogFields): LogFields => {
  if (typeof fields.requestId === 'string' && fields.requestId !== '') {
    return fields;
  }
  return { ...fields, requestId: newRequestId() };
};

export const createLogger = (scope: string, fields: LogFields = {}): Logger => {
  const parentFields = bindCorrelationId(flattenFields(fields));
```

Emit sites with no `log.child({ jobId })` (and no other job/session key):
- `apps/prototype-wp-alt-context/js/admin/main.tsx:67` `bootstrapLog.warn(...)`
- `apps/prototype-wp-alt-context/js/admin/api/config.ts:85` `configLog().warn(...)`
- `apps/prototype-wp-alt-context/js/admin/hooks/useJobPersistence.ts:88` `log.error('Failed to parse persisted jobs', { error })`
- `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineMutations.ts:110` `log.error('Scan submission failed', ...)` then `logJobEvent(log, 'scan.submit', ...)` with no jobId
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterSuggestionsLoader.ts:213` `log.warn('Failed to find cluster by label', ...)`

`logger.test.ts:255-263` asserts two loggers get *distinct* requestIds, which documents that a scan submit (`jobStateMachineMutations`) and its SSE stream (`hooks.jobProgressStream`) cannot share one grep key unless the caller passes `jobId`.
- failure scenario: operator greps the `requestId` from a `Scan submission failed` line hoping to find the later SSE stall/done lines for that attempt → zero hits; those lines live under a different module-lifetime UUID (or under `jobId` only after submit succeeds).
- fix: mint `requestId` per unit of work (scan/cluster/page session) and pass it into `child()`, or require `jobId`/`identityId` on every emit and stop treating import-time UUIDs as OBS-03 compliance.

### F-2 scan.submit keeps only jobIds[0]; sibling job IDs are dropped
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineMutations.ts:99
- rule: OBS-03, OBS-06
- evidence: success path sums `total` across all jobs then binds correlation to the first id only:

```
const jobId = jobIds[0];
const jobLog = jobId ? log.child({ jobId }) : log;
logJobEvent(jobLog, 'scan.submit', {
  status: jobIds.length > 0 ? 'pending' : 'completed',
  jobId,
  done: 0,
  total,
  failedCount: 0,
});
```

`useJobStateMachineMutations.test.ts:124-137` drives `scanResponse(['job-1', 'job-2'], 4)` (two jobs, `addJob` called twice, `onScanComplete(['job-1','job-2'])`) and asserts the wide event's `jobId` is `'job-1'` with `total: 8`. `job-2` never appears in `fields`.
- failure scenario: batch analyze returns two jobs; job-2 later emits `sse.connection_closed` / `stream.done` with its own `jobId`. Grep of the submit line's `jobId=job-1` does not reconstruct job-2. High-cardinality identifiers were bucketed away to a single slot.
- fix: log `jobIds` (full array) and `batchRunId` on the wide event, and attach `child({ jobId })` per job or put the batch id on every subsequent stream logger.

### F-3 Retry and nonce-refresh decisions emit no telemetry
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/hooks/clusterAutoRetry.ts:114
- rule: OBS-01, AGT-10
- evidence: `noteError` schedules the next cluster POST when `canAutoRetryCluster` is true and returns `true` with no logger call:

```
noteError: (error: unknown): boolean => {
  if (disposed) {
    return false;
  }
  if (canAutoRetryCluster(attempts, error)) {
    const seconds = resolveClusterRetryDelaySeconds(error);
    listener.onQueued(seconds);
    timer = setTimeout(() => {
      timer = null;
      listener.onQueued(null);
      fire();
    }, seconds * 1000);
    return true;
  }
```

Caller `useJobStateMachineMutations.ts:159-163` only forwards to the controller:

```
onError: (error) => {
  retryControllerRef.current.noteError(error);
},
```

Same gap on the QueryClient path: `appQueryClient.ts:28-31` calls `shouldRetryRequest` / `getRetryDelay` with no log; `retryPolicy.ts:23-41` returns a boolean and is silent. HTTP nonce-403 retry swallows the refresh error without a record (`http.ts:303-309`):

```
try {
  await refreshRestNonce();
} catch {
  throwIfAborted(signal);
  throw new AuthExpiredError({ endpoint, status: 403 });
}
```
- failure scenario: recognition returns 429; cluster auto-retry waits N seconds and POSTs again. Console/sink show nothing until a later terminal UI error. Operator cannot tell a successful first try from two invisible retries that then succeeded, and cannot tell a nonce-refresh failure from a generic session-expiry.
- fix: emit one structured line per retry decision (`attempt`, `delayMs`, `tag`/`status`, `jobId`/`identityId` if known) and log the caught `NonceRefreshFailedError` before mapping it to `AuthExpiredError`.

### F-4 Quiet SSE stall is silent; reconnect churn is the only stream noise
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts:132
- rule: OBS-08, OBS-01, OBS-02
- evidence: stall detector ticks every 1s and dispatches `STALL_TICK` with no log:

```
const updateStallState = () => {
  const now = Date.now();
  dispatch({ type: JOB_EVENT.STALL_TICK, now });
  const baseline = lastEventAt ?? streamOpenedAtRef.current;
  if (!baseline) {
    setStalledForSeconds(null);
    return;
  }
  const elapsedMs = now - baseline;
  setStalledForSeconds(elapsedMs >= stallThresholdMs ? Math.floor(elapsedMs / 1000) : null);
};
```

`jobMachine.ts:117-126` `failReconnectCeiling` builds `Reconnect ceiling exceeded (3 attempts)` only in reducer state. The hook discards that state (`useJobProgressStream.ts:62` `const [, dispatch] = useReducer(...)` — agrees with banked FEBT1-W2C-01). Meanwhile every EventSource error logs a thin warn, including auto-reconnects (`useJobProgressStream.ts:304-309`):

```
jobLog.warn('sse.connection_error', streamEventFields(event));
...
jobLog.warn('sse.connection_closed', { readyState: EventSource.CLOSED });
```

Happy-path `progress` listeners (`:229-255`) never call the logger, so a server that stops sending while EventSource stays OPEN produces zero log lines.
- failure scenario: 200-image job; proxy holds the socket OPEN but stops forwarding events. UI `stalledForSeconds` climbs; reducer would fail after 3 quiet ticks of 30s; logs stay empty. Operator cannot distinguish "no events because capture is broken" from "job still running". Conversely a flaky reconnecting socket emits one `sse.connection_error` warn per browser reconnect — many thin lines, still no stall/terminal wide event.
- fix: log a sampled/terminal `sse.stalled` / `sse.reconnect_ceiling` wide event with `jobId`, `quietMs`, `reconnectAttempts`; keep per-reconnect lines at debug or fold them into that event.

### F-5 sse.progress_parse_failed is ERROR for a dropped event that does not fail the job
- severity: medium
- file: apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts:236
- rule: OBS-04
- evidence: a malformed/schema-invalid progress payload logs ERROR then returns; the EventSource stays open and later events can still complete the job:

```
const parsed = parseProgressEvent<JobStatus>(event.data as string, startTimeRef);
if (!parsed) {
  jobLog.error('sse.progress_parse_failed');
  return;
}
```

`parseProgressEvent` returns null on JSON failure *or* non-finite `completed`/`total` (`useJobProgressStreamHelpers.ts:80-95`). Contrast: expected EventSource reconnect churn was correctly placed at warn (`sse.connection_error` / `sse.connection_closed`). `sse.done_parse_failed` at `:264` is closer to ERROR (terminal event lost) but still does not fail the job itself.
- failure scenario: producer emits one schema-evolved progress frame per job; every describe run logs ERROR while the job still reaches `completed`. On-call sees a red line that requires no action (next event or `done` recovers) and habituates to real `sse.server_error` / parse-of-done failures.
- fix: log progress parse misses at warn with `{ reason: 'json'|'schema' }` and reserve ERROR for `done` parse failure plus an explicit job FAIL dispatch.

### F-6 fields.endpoint carries search=<cluster label> (PII)
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterSuggestionsLoader.ts:213
- rule: OBS-06, WEB-44
- evidence: the warn copies `classified.endpoint` verbatim (no pathname redaction, unlike `classifiedLogFields` in `useJobStateMachineMutations.ts:21-25`):

```
log.warn('Failed to find cluster by label', {
  tag: classified._tag,
  ...('status' in classified ? { status: classified.status } : {}),
  ...('endpoint' in classified ? { endpoint: classified.endpoint } : {}),
});
```

`listRecognitionClusters` puts the typed label into the query string (`clusterApiQueries.ts:93-94` `url.searchParams.set('search', params.search)`). The unit test pins the leak: `useClusterSuggestionsLoader.test.tsx:199` uses `endpoint: '/acx/v1/recognition/clusters?search=Alice'` and asserts only that `fields.endpoint` *contains* that path — it does not strip `search=Alice`.
- failure scenario: operator types a person's name into the cluster label box; the list call 500s; console shows `endpoint: "...?search=Alice"`. Roster names (PII) land in the log sink. Contrast: scan mutation tests explicitly forbid `secret-token` in the serialized records.
- fix: reuse the mutations pathname redactor (or logger `redactEndpoint`) so `fields.endpoint` is path-only; keep `search` out of telemetry.

