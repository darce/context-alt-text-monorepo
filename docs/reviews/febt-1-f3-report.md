# FEBT-1 F3 lane report (provenance gap)

Lane: `febt-1-f3` on `feature/febt-1-f3` @ `707a208d1` (as cited by the
originating brief). Task: `FEBT-1`.
This file did not ship with the lane. ISSUEDAG-1 docs-corrections writes it
after the fact so the missing-report finding has a committed home.

Rules that still fail: TEST-15 (new assertions watched failing), RLSE-05
(release evidence), OBS-01 (dead SHA citations).

## What the lane claimed

F3 landed W2D-02 (reconnect counting) and W2D-01 (stalled derivation) with a
green self-verify. Implementation on inspection later looked correct. That is
not evidence: reconnect-counting and stalled-derivation tests can pass
vacuously and nothing in the tree would show it.

Sibling lane `febt-1-f3b` (`docs/reviews/febt-1-f3b-report.md`) later recorded
W2D-03 reconnect counting with a committed RED tail. It explicitly did **not**
re-fix W2D-01 / W2D-02 / W2D-04 ("already on base"). F3b is not a substitute
for F3's missing TEST-15.

## Why RED / per-fix SHAs cannot be reconstructed

The offload engine squashed the lane commits. The RED-then-green sequence and
the cited per-fix SHAs no longer exist in git history. The same class of defect
appears on f1b (bare commit bodies, no RED tail) and on F2 (cited SHAs
`1af5ae861` and `99d0420c2` are dead; squashed into `82dc82211`).

This is historically unrecoverable from the repository. Filed upstream as
`squash-loses-per-fix-provenance` in agentic-protocol-monorepo. A later green
run of the current tests does **not** prove they can fail.

## Honest status

| Claim | Status |
| --- | --- |
| Lane report existed at merge | no — this file is a gap record, not a contemporaneous report |
| Committed RED output for W2D-01 | unrecoverable |
| Committed RED output for W2D-02 | unrecoverable |
| TEST-15 proof the new assertions can fail | unrecoverable for F3; F3b later proved a *different* reconnect assertion (W2D-03) |
| Implementation "reads correct" | not evidence |

Do not treat this document as closing TEST-15. It closes only the "no committed
lane report" hole by stating the provenance is gone.
