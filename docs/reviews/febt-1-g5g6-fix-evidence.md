# FEBT-1 G5/G6 fix evidence

HEAD: bc0281ef840d290bcf485474b5c0ea0c8079f4d3

The execution sandbox exposed this history-stripped base commit rather than the host-worktree
SHA `ec83a8956de6a81bf1738cb87a621aee637c8e31`; its subject is
`sandbox base (feature-febt-1-g1-e248d59a, history-stripped, remote-severed)`.

## RED baseline

Command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx --reporter=verbose
```

Verbatim tail:

```text
/bin/bash: line 1: ./node_modules/.bin/vitest: No such file or directory
```

The required runner did not start, so the sandbox could not reproduce the supplied RED suite.

## Task 1

I chose option (a): the live-target existence probe now treats abort and timeout as terminal,
alongside 404, before delegating other errors to `shouldRetryRequest`. This prevents a timed-out
probe from retrying into a false `live` result (RES-13) while retaining the shared 429 and
503-with-`Retry-After` cooldown retry behavior (RES-06). The contradictory blanket-5xx comment
was corrected to document that carve-out (REF-33).

Diff summary: imported `isAbortOrTimeout`, short-circuited the probe retry predicate for
404/abort/timeout, and updated its comment. `shouldRetryRequest` and the status derivation were
not changed.

Verbatim `useLiveReviewTarget.test.tsx` tail after the fix:

```text
/bin/bash: line 1: ./node_modules/.bin/vitest: No such file or directory
```

## Task 2

Static inspection confirmed that `renderWithClient` creates userEvent with
`advanceTimers`, while `actFlow` added an explicit outer `act()` around `user.click()` and
`user.clear()` calls. The test file now awaits those userEvent interactions directly (or through
`runWithTimers`) and reserves `actFlow` for raw cache updates, deferred resolution, and timer
flushes. This removes the nested act ownership that prevented fake-timer queues from settling;
the behavioral assertions remain intact (TEST-15, TEST-17). No product file was changed.

Diff summary: moved every userEvent call out of `actFlow`, separated clicks from deferred
resolution, and removed explicit act wrapping from associated RTL `fireEvent` calls.

Verbatim `IdentityClusterList.test.tsx` tail after the fix:

```text
/bin/bash: line 1: ./node_modules/.bin/vitest: No such file or directory
```

## GREEN (or residual)

Final full verification command:

```text
./node_modules/.bin/vitest run js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/useLiveReviewTarget.test.tsx --reporter=verbose
```

Verbatim tail:

```text
/bin/bash: line 1: ./node_modules/.bin/vitest: No such file or directory
```

VERDICT: BLOCKED

Exact failing test names: none observed. The Vitest process never started because the required
`apps/prototype-wp-alt-context/node_modules/.bin/vitest` executable is absent, and the lane
explicitly forbids installing dependencies. Post-fix pass/fail status therefore remains
unverified rather than being inferred from the edits.
