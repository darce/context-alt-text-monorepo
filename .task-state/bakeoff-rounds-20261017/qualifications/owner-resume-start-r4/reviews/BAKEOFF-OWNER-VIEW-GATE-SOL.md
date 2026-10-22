# BAKEOFF-OWNER-VIEW-BUDGET-20261020 — Sol high gate

Verdict: **pass** for the supplied source diff. No actionable source defects found. This is a review-only source verdict; merge acceptance still needs the orchestrator to resolve the unavailable pinned-canon verification described below. No subject file was changed, and no restage or live use was performed.

```FINDINGS
[]
```

Reviewed on 2026-10-20 in the managed sandbox on branch `feature/bakeoff-owner-view-budget-20261020`. The sandbox has a history-stripped base `88c74d28b0c973dadbee0bc09a9c643f89734c27`; the requested tip `6f72bfa523a2a6fbdcec9ee6e2238be2930928d0` is not present as a commit object. All six tracked subject blobs match the new-side blob IDs in the supplied diff: `owner-custody.py` `0f384783b730680174b83af36f859792587d1773`, `owner-window.py` `624c15f7680c33d0017704512906c579f7d48b23`, `approved-scripts.json` `30de999d43f9d3e3e5416bb8f3aea0fb4614f1a1`, `test_view_budget.py` `30d2aa42edc23b06e084153af580e26dd8975525`, `test_resume_start.py` `917edb980f2f7e3323709e5533d16e6114da6e9d`, and `test_window_checkpoint.py` `600533b86a7ada889835f5bc9fe477fd894ad88d`.

The guard at `owner-custody.py:285` only branches on authority records at or above the predecessor sequence. Dropped records were already ignored by its older-record branch. Projection retains newer-record and equal-sequence conflict checks, the unchanged `high <= previous['sequence']` requirement, rejection history, all runtime/durable publications, and deferred STOP evidence. Foreign publications and foreign deferred STOP retain their refusal messages. First use now checks the total `intent_count`, including when the projected intent map is empty. Projection additionally rejects malformed record types before the guard; such source state still fails closed.

Guardian captures the predecessor floor once at line 385 and uses that same value for preflight and every post-effect read (lines 386 and 416). `sha256` covers the exact raw source bytes, including fields and fenced records omitted from the projection. Thus changes below the floor, or formatting-only changes, cannot produce the unchanged-state `not-published` result. The before/after comparison still intentionally removes load evidence from the preflight comparison. The persisted-candidate `published` branch is unchanged. Reconciliation uses its selected published candidate's sequence; inspect uses `None`, selecting the high-water sequence.

`checkpoint_floor()` and `checkpoint_selection()` derive their maximum from the same published candidates (lines 520–524 and 561–564). Selection refuses duplicate candidate sequences/nonces before admitting the predecessor, so tie-breaking cannot create a different accepted floor. Both checkpoint reads recompute from the same immutable operation inventory; recovery revalidates that inventory against the sealed manifest. Older current publications and deferred STOP candidates are retained through their independent publication/deferred evidence and original candidate custody, not through discarded authority records. Resource proofs still hash the complete source bytes and retain file identity checks.

The result-size bound is conditional on an admissible custody state, rather than a universal constant-size projection for arbitrary input. On the supported successful continuation, authority has no newer sequence than the predecessor, and accepted native history has one owner for that sequence; only that record can remain at the floor. The guardian fences prevent authority growth between preflight and post-effect reads. Fenced history below the floor contributes only a count and digest to the native-job result. Fixed-environment publications and loads remain separate inputs. The `<60000` native-job result limit is unchanged.

There are still O(total-records) results in refusal cases: first use with floor zero retains all records; a stale predecessor can retain many newer records; a nonempty rejection list is copied in full. These states already require refusal, so a result-budget refusal before effects is acceptable. A valid first use requires an empty authority and has a small result. Checkpoint with no published operation also uses floor zero; it can succeed for completed refused/not-published operations only when authority/publications/deferred state satisfy the empty first-use guard. A nonempty authority in that case was already ineligible for archival selection and does not need a successful read to enable a valid live continuation. Checkpoint runs directly, not through `native_job()`, and keeps its file/manifest bounds. Inspect with a healthy native ledger selects its newest record; conflicting/rejected/corrupt ledgers may still exceed the result budget and refuse.

Full source parsing/hashing remains O(total bytes), capped by the existing 1 MiB source-file limit. Authority exceeding that limit will refuse before publication; this change does not provide unlimited ledger lifetime or resolve native-authority reclamation. Native-only reclamation remains the separate BKR-INTENT-RECLAIM-01 work identified in the brief. No budget increase, authority purge, or preflight bypass is proposed here.

Manifest verification passed against both tracked and working bytes:

- `owner-custody.py`: `e86b763b95ce9be67964b925c2f6ce7ea3c73ddbd4ababd70b4d36a95c407c2f`.
- `owner-window.py`: `60c0cfdceedbf778be717300d7d0d5c071a07860be333abcd694e4e0c430281b`.

The new size controls execute the complete SHA-pinned publication writer, real guardian, native fork/pipe result budget, filesystem fences, and private source files. The controller authority ledger is explicitly emulated, not qualified as a live controller. Positive START/STOP/AUTO publication paths do not stub the writer. The nonpublication and below-floor-change negative controls deliberately replace the writer effect; the latter checks retained UNKNOWN custody instead of accepting a false `not-published`. Existing dispatch and controller-role substitution controls retain their stated unit-only limitations. No new mutation campaign or Root qualification was run.

Verification command (the mandated lane suite, using the required managed interpreter):

```sh
lane_root="$(git rev-parse --show-toplevel)" || { echo 'cannot resolve lane root' >&2; exit 1; }
resolved_python="$lane_root/.venv/bin/python"
if [ ! -x "$resolved_python" ]; then echo 'lane interpreter unavailable' >&2; exit 1; fi
"$resolved_python" -B -m pytest .task-state/bakeoff-rounds-20261017/qualifications/owner-resume-start-r4/test_view_budget.py .task-state/bakeoff-rounds-20261017/qualifications/owner-resume-start-r4/test_resume_start.py .task-state/bakeoff-rounds-20261017/qualifications/owner-resume-start-r4/test_window_checkpoint.py .task-state/bakeoff-rounds-20261017/qualifications/owner-resume-start-r4/test_window_ttl.py -q
```

Result: **33 passed, 77 subtests passed in 62.25 seconds; exit 0**. The owned lane is a standalone review/script scope with no importable Python project package or package setup configuration; package import-origin control is inapplicable. Tests explicitly load the reviewed custody script from their lane directory and read pinned writer bytes from this worktree.

Canon verification is **unavailable**: `/Users/daniel/Development/heuristics-canon-current` does not exist in this sandbox, so its `AGENTS.md`, release manifest, relevant row/card text, and digests could not be read or verified. The brief cites v0.26.2 while its trailing canon pointer cites v0.25.3; neither is asserted as a verified release here. RES-05 and STOR-10 requirements above are reviewed as supplied task requirements, not independently verified canon quotations. The orchestrator must supply the pinned read-only release or a compact digest-verifiable canon brief and complete that qualification before treating this report as full merge acceptance. Graph tools were also not exposed; exact source reads and literal searches were used.
