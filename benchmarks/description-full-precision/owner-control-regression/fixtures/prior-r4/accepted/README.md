# Offline snapshot cursor correction

`snapshot_cursor.py` uses the genuine, byte-for-byte supplied
`snapshot_source.py`. A transaction with no predecessor first projects with
`floor=None`, then pins the returned `highest_sequence` as its numeric floor.
Later observations use that same inclusive floor, retaining changes to the
initial newest record as new sequences arrive. An explicit predecessor keeps
its own inclusive sequence, including zero; invalid predecessor values refuse.
All reads retain the full raw-byte SHA-256, total record count,
`highest_sequence`, and `rejected_sequences`. Nothing deletes stored history.

`caller.patch` is a minimal unified patch for the exact three-line supplied
`caller_excerpt.txt` (identified original caller lines 385-387). It is a
review artifact. Baseline `view()` (owner-custody.py:171) returns
`dict(authority=..., publications=..., loads=..., deferred=...)`, so the
patch pins `v['authority']['highest_sequence']`; the R3 seed read top-level
`v['highest_sequence']` and raised `KeyError` on every first observation
(review 1659, finding F-01). Later reads (baseline line 416) reuse `floor`.
Surrounding owner, fence, guard and publication lines are unchanged.

The caller harness evaluates the exact baseline `view()` return expression
and the exact native encoding plus strict `len(encoded) < 60000` predicate,
both parsed via AST from the pinned review packet
(`be6fdc99e44e0dcbdc1b54d1651a315810f4ba76dad084cbeae81571d920685a`); the
controller is never imported or invoked. `ActualViewShapeTests` cover empty
and 258-record first observations, pinned reuse, and a retained control
proving the seed patch still raises `KeyError` on the actual shape.

| Evidence | Records | Full projection bytes | Newest projection bytes |
|---|---:|---:|---:|
| Supplied live measurements, not rerun | 258 | 124811 | 2102 |
| Synthetic regression, compact JSON encoding | 258 | 144527 | 715 |
| Synthetic nested view, baseline `json.dumps` encoding | 258 | 145891 | 794 |

The unchanged limit is **60000 bytes**. The synthetic two-record cause-removal
control returns 1267 bytes using the unchanged original caller. Oversized
newest records or a growing pinned suffix still refuse at the limit. The
example's serializer is explicitly synthetic; the live serializer is absent.

Run from the workspace root with Python 3.9+ and stdlib only. All generated
fixtures, reports and logs go to the sibling output directory:

```sh
task_output="$(pwd)/../output/offline-snapshot-fix"
mkdir -p "$task_output"
PYTHONDONTWRITEBYTECODE=1 python3 offline-snapshot-fix/verify_inputs.py --output "$task_output" > "$task_output/verify-inputs.log" 2>&1
# Expected RED: exit 1, genuine original caller exceeds the fixed limit.
PYTHONDONTWRITEBYTECODE=1 SNAPSHOT_CALLER_ORIGINAL=1 python3 -m unittest discover -s offline-snapshot-fix -v -k test_initial_caller_fits > "$task_output/old-red.log" 2>&1
# Expected GREEN: exit 0, all 20 tests (15 original + 5 actual-view-shape).
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s offline-snapshot-fix -v > "$task_output/corrected-green.log" 2>&1
PYTHONDONTWRITEBYTECODE=1 python3 offline-snapshot-fix/snapshot_cursor.py --output "$task_output" > "$task_output/example.log" 2>&1
```

Tests cover the original RED and corrected GREEN, small cause removal, numeric
pinning across three observations (258, 259, 260), failure of a moving newest
view to retain record 258, older unreturned mutations changing the full digest,
exact-byte hashing, explicit predecessor/zero behavior, malformed input and
boolean type refusal, tied sequences, empty history, and the exact byte limit.

Lineage: readonly inputs are at
`/home/gate/description-offline-snapshot-inputs-20261023T2231`.
`verify_inputs.py` verifies all nine entries against the pinned input manifest
(`52a60cba514014701d3eb5e2f229bcfd1b2fc14a9bd4b81c4241af9b5a0b0a0a`),
the exact AST codemap, and identical supplied/copied pure source
(`04917b66480bca3621e60668c06cae29c8c591941638f334c3e979869d8f98a0`).
The original source identity is
`e86b763b95ce9be67964b925c2f6ce7ea3c73ddbd4ababd70b4d36a95c407c2f`;
its complete source is unavailable, so that identity remains supplied metadata.

The retained canon proposal is dispatch 3, following a missing-carrier failure
and an automatic-review rejection, with no earlier candidate patch. RES-05 and
the original distilled *Release It!*, ch. 4.11, motivate reducing the returned
collection while retaining the fixed acceptance limit. TEST-15 and the original
distilled *The Pragmatic Programmer*, ch. 9, motivate the genuine failing test
and causal control. GRPH-14 and Principles 9/11/18 motivate verified lineage,
refusal on unknown input, and machine-checkable results. GRPH-31/32 add no
parallel work here: the named data dependency is first `highest_sequence` to
subsequent numeric `floor`. The supplied source's inherited STOR-10 comment
does not establish a native sequence fence; the proposal explicitly calls
that reference inert. This offline artifact implies no source adoption,
native operation, or model-quality approval.
