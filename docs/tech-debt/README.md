# Tech-Debt Register

Deferred work that is intentionally not blocking the current merge but must not be lost. One file per item. Each entry states what was deferred, why it's safe to defer, the trigger for picking it up, and the acceptance criteria.

Deferring is a decision, not a skip: every item here was consciously moved out of scope with a rationale, and is tracked so a later phase can close it.

## Open items

- [E21-5 VoiceOver AT protocol](e21-5-voiceover-at-protocol.md) — the manual screen-reader acceptance pass for the unified review queue, deferred to the next phase (UX-flow correctness prioritized first).
- [OPS-1 `acx-backend` host retention hygiene](OPS-1-vm-host-retention-hygiene.md) — no scheduled reaper for the Docker build cache, image tags, or `/home/ubuntu` scratch; deferred while the box sits at 94 GB free. Note the trap: an age-based `docker image prune -a` destroys the rollback tag history to reclaim ~80 MB.
- [OPS-2 vendored `remote_agent.sh` fork](OPS-2-vendored-remote-agent-fork.md) — our untracked 2026-07-22 copy shares the upstream sandbox root without writing the reap marker (8.8 GB unreapable and growing) and caps lanes at 3 against upstream's 20 on a shared scope namespace.
- [OPS-3 publishing redaction corrupts the workbay hook overlay](OPS-3-workbay-overlay-redacted-test-fixtures.md) — the overlay publisher rewrites finding-style ids to the literal token `internal`, inside test fixtures and the guard's own block message, so `scripts/hooks/` ships at 14 failed / 42 passed and `make check-all` can never be green. The guard's detection logic is intact and still blocks real violations; the damage is to its self-test and to the message it prints.
