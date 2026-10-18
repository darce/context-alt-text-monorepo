HEAD: 9de1fa7aa71c3ac0aa431733ec771816886f0591
RUNS: scoped x3, full x2 (+ committed run1 = 3 full observations)

The execution checkout is a history-stripped, remote-severed sandbox snapshot. `git rev-parse HEAD`
returned the HEAD above; the committed run1 evidence records source HEAD
`4d83a8270a116ba779b3d7098ed4f08860d57bb1`, which is not present in this sandbox's object
database. The worktree remained unchanged throughout all new observations. The full-suite command
discovered 236 files (not the 250 stated in the assignment objective) and 2,984 tests on every run.

## OBSERVATION MATRIX

| test | scoped 1 | scoped 2 | scoped 3 | full 1 (run1) | full 2 | full 3 | LABEL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `refreshRestNonce (UXP-NET-2 slice 1) > missing ajaxUrl fails SOFT: config stays usable, only refresh degrades (UXPNET2-BR-02) [TEST-15]` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `boundary error redaction [O-03][O-05] > characterises exact LogRecord.fields.error for HTTPError, ResponseParseError, and NonceRefreshFailedError [W2-L5][TEST-15]` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `boundary error redaction [O-03][O-05] > HTTPError message secrets are absent from the serialized record [O-03][REF-19]` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > shows a friendly inline message when merge rejects a self-target request` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > shows undo when merge completes and reverts on request` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > renders face thumbnail when media_url is provided` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > allows clicking the unlabeled text to start editing` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > allows unlinking an identity (wrong person) only for singletons` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > allows splitting a cluster` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > inline suggestion batching > issues exactly one batched suggestions fetch at projection depth for N unlabeled cards` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > inline suggestion batching > resolves an inline prompt on every one of 60 unlabeled cards from a single batch` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `IdentityClusterList > inline suggestion batching > renders nothing for an identity absent from the keyed envelope (empty-match)` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `isAbortError > treats non-DOMException TimeoutError name as abort [CARD-24]` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `useClusterSuggestionsLoader > findClusterByLabel short-circuits non-DOMException TimeoutError abort [CARD-24]` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |
| `useLiveReviewTarget > probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]` | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | DETERMINISTIC |

## PER-RUN RAW TAILS

### Scoped 1

```text
 Test Files  6 failed (6)
      Tests  15 failed | 72 passed (87)
   Start at  01:32:30
   Duration  55.55s (transform 1.69s, setup 1.18s, import 2.36s, tests 48.03s, environment 2.82s)

EXIT=1
```

### Scoped 2

```text
 Test Files  6 failed (6)
      Tests  15 failed | 72 passed (87)
   Start at  01:33:33
   Duration  57.59s (transform 2.58s, setup 1.62s, import 3.38s, tests 48.36s, environment 3.17s)

EXIT=1
```

### Scoped 3

```text
 Test Files  6 failed (6)
      Tests  15 failed | 72 passed (87)
   Start at  01:34:37
   Duration  55.00s (transform 1.30s, setup 1.28s, import 1.84s, tests 47.87s, environment 2.95s)

EXIT=1
```

### Full 1 (committed run1)

```text
 Test Files  6 failed | 230 passed (236)
      Tests  15 failed | 2969 passed (2984)
   Start at  00:10:05
   Duration  367.53s (transform 8.81s, setup 43.13s, import 35.55s, tests 146.47s, environment 104.16s)

EXIT=1
```

### Full 2

```text
 Test Files  8 failed | 228 passed (236)
      Tests  17 failed | 2967 passed (2984)
   Start at  01:35:37
   Duration  389.26s (transform 10.81s, setup 47.16s, import 40.00s, tests 152.17s, environment 109.71s)

EXIT=1
```

### Full 3

```text
 Test Files  8 failed | 228 passed (236)
      Tests  17 failed | 2967 passed (2984)
   Start at  01:42:13
   Duration  398.80s (transform 10.26s, setup 47.16s, import 40.55s, tests 158.79s, environment 111.80s)

EXIT=1
```

Both new full runs also failed these two tests, which passed in committed run1 and were outside
the six-file scoped group:

- `E15-25 slice 1: radio-group stylesheet > ships radio-group rules in the production admin CSS bundle`
- `E15-25 slice 3: target-card stylesheet > ships target-card rules in the production admin CSS bundle`

These are additional full-suite inconsistencies, not rows retroactively added to the requested
15-test matrix.

## IDENTITYCLUSTERLIST TIMEOUT PROBE

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx --reporter=verbose --testTimeout=20000
```

Verbatim failed-test result lines and raw tail:

```text
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > shows a friendly inline message when merge rejects a self-target request 20050ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > shows undo when merge completes and reverts on request 20057ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > renders face thumbnail when media_url is provided 20049ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > allows clicking the unlabeled text to start editing 20058ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > allows unlinking an identity (wrong person) only for singletons 20058ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > allows splitting a cluster 20012ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > issues exactly one batched suggestions fetch at projection depth for N unlabeled cards 20041ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > resolves an inline prompt on every one of 60 unlabeled cards from a single batch 20040ms
 × js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx > IdentityClusterList > inline suggestion batching > renders nothing for an identity absent from the keyed envelope (empty-match) 20057ms

 Test Files  1 failed (1)
      Tests  9 failed | 15 passed (24)
   Start at  01:48:59
   Duration  183.43s (transform 1.01s, setup 236ms, import 1.38s, tests 181.19s, environment 450ms)

EXIT=1
```

All nine tests still hit the raised 20-second ceiling. The probe therefore rejects the hypothesis
that these are merely assertions which need slightly more than five seconds; it revealed no hidden
assertion message. The repeated stderr immediately before the affected failures was:

```text
You seem to have overlapping act() calls, this is not supported. Be sure to await previous act() calls before making a new one.
```

## CLASSIFICATION

DETERMINISTIC:

- `refreshRestNonce (UXP-NET-2 slice 1) > missing ajaxUrl fails SOFT: config stays usable, only refresh degrades (UXPNET2-BR-02) [TEST-15]`
- `boundary error redaction [O-03][O-05] > characterises exact LogRecord.fields.error for HTTPError, ResponseParseError, and NonceRefreshFailedError [W2-L5][TEST-15]`
- `boundary error redaction [O-03][O-05] > HTTPError message secrets are absent from the serialized record [O-03][REF-19]`
- `IdentityClusterList > shows a friendly inline message when merge rejects a self-target request`
- `IdentityClusterList > shows undo when merge completes and reverts on request`
- `IdentityClusterList > renders face thumbnail when media_url is provided`
- `IdentityClusterList > allows clicking the unlabeled text to start editing`
- `IdentityClusterList > allows unlinking an identity (wrong person) only for singletons`
- `IdentityClusterList > allows splitting a cluster`
- `IdentityClusterList > inline suggestion batching > issues exactly one batched suggestions fetch at projection depth for N unlabeled cards`
- `IdentityClusterList > inline suggestion batching > resolves an inline prompt on every one of 60 unlabeled cards from a single batch`
- `IdentityClusterList > inline suggestion batching > renders nothing for an identity absent from the keyed envelope (empty-match)`
- `isAbortError > treats non-DOMException TimeoutError name as abort [CARD-24]`
- `useClusterSuggestionsLoader > findClusterByLabel short-circuits non-DOMException TimeoutError abort [CARD-24]`
- `useLiveReviewTarget > probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]`

FLAKY: none among the requested 15.

ISOLATION-DEPENDENT: none among the requested 15.

## F4B CHECKPOINT AND FEBT1-W2A-06

The two checkpoint files were also run directly together:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx js/admin/utils/__tests__/userFacingError.test.ts --reporter=verbose
```

Verbatim tail:

```text
 Test Files  1 failed | 1 passed (2)
      Tests  1 failed | 18 passed (19)
   Start at  01:52:12
   Duration  3.77s (transform 374ms, setup 411ms, import 473ms, tests 1.67s, environment 892ms)

EXIT=1
```

All seven `userFacingError.test.ts` tests passed. The only checkpoint failure was:

```text
FAIL  js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx > useLiveReviewTarget > probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]
AssertionError: expected 'live' not to be 'live' // Object.is equality
```

The source comment says `never retry 404/auth/abort/timeout/5xx`, while the implementation delegates
non-404 errors to `shouldRetryRequest(failureCount, error)`. The observed TimeoutError retry consumes
the test's one rejection and then succeeds, leaving the target `live`. FEBT1-W2A-06 is therefore a
deterministic combined-tree defect, not a flake or cross-file pollution. Per the measurement-only
constraint, no production or test source was changed.
