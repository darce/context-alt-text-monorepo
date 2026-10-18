# GPU intent implementation reconciliation — 2026-09-08

Source candidate: `feature/gpuops-1-intent-journal` at `4c4c5eac6`, including
implementation `fb37d2633`. Incumbent baseline: `984a7af39` on main. MCP decision
`9214` designated the incumbent implementation and identified terminal nonce
expiry and requester-attributed cross-boot revocation as properties to preserve.

The consolidation merge retains the incumbent tree and both source histories.
The candidate's independent journal/controller is not installed alongside it.
The bounded semantic patch ports cross-boot revocation into the existing
`IntentAuthorityStore`; its existing terminal `expired` fence already preserves
nonce burning. This feature is not merge-ready until the requested reviews and
verification are complete.

| Candidate surface | Reconciliation |
|---|---|
| `intent_journal.py` | Use incumbent `IntentAuthorityStore`, `DeferredStopStore`, and `DecisionLogStore`; retain their sequence/nonce immutability and ambiguity handling. Port cross-boot revocation to the authority ledger. |
| `hostclock.py` | Keep the incumbent lock/clock mechanisms. Require a nonblank boot identity before authority evaluation; compare monotonic deadlines only inside the originating boot. |
| `intent.py` | Keep incumbent publication and state schemas. Persist terminal expiry plus revocation reason/boot in the existing ledger, preserving original requester provenance. |
| `reaper.py` | Keep the incumbent copy-before-evaluate, durable read source, deferred STOP and decision-log integration. Existing authority errors use AUTO rather than honoring an unverifiable grant. |
| `gpu-lifecycle-install.sh` | Keep existing authority/deferred/log paths; do not introduce the candidate-only `--intent-journal-path` flag or a second storage owner. |
| `test_intent_journal.py` | Port behavioral checks to incumbent authority/controller tests: spent nonce stays spent, host reboot revokes, process restart does not, unknown boot refuses, and requester attribution remains. |
| Candidate contract-parity tests | Review the incumbent contract and its active tests; do not transplant assertions for the discarded parallel implementation. |
| `docs/workbay/contracts/gpu-lifecycle.md` | Explicitly amend the cross-boot policy from logical-wall fallback to terminal revocation; preserve same-boot deadline semantics. |

This changes the documented reboot policy deliberately, rather than silently
reversing it (canon AGT-13). A host restart cancels an existing operator grant;
a new publication is required. Legacy records without boot identity also revoke
when next observed. Backend process restarts within a boot retain the grant.
The durable deferred-STOP mechanism remains a separate, bounded authority.

RED evidence: four failing boot/legacy/unknown-identity cases plus a passing
same-boot control at `fe9e4c821`; MCP test `1897`, recorded before production
edits. The tests use explicit clocks and boot identities. Controller tests model
a Linux boot explicitly when run on a non-Linux development host.
