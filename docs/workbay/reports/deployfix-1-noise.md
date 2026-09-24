VERDICT: 3 confirmed, 1 refuted, 2 unverified, 0 new

## D6 — CONFIRMED — MEDIUM

- **Evidence:** scripts/deploy/recognition-service.sh:2837
  > printf '%s' "\$networks" | grep -q "\\\"\$network\\\"" || {

  This line is in the unquoted EDGE_RESTORE heredoc opened at line 2717. The local reproduction generated this remote line:
  > printf '%s' "$networks" | grep -q "\\"$network\\""

  With JSON containing the key acx-prod-net, Bash passed grep the pattern \acx-prod-net\ and grep printed “Trailing backslash”. The branch then reports the present network missing and returns 1. The result propagates through restore_edge_backups (line 2849) and restore_runtime_and_edge (line 3657), so rollback can be reported failed even when the inspected network map contains the expected key.
- **Mechanism:** Expansion of the unquoted heredoc reduces the source backslashes; remote Bash then consumes the escaped quotes while expanding the network variable. The resulting grep pattern ends in a backslash.
- **Failure scenario:** Caddy’s NetworkSettings.Networks JSON contains acx-prod-net → grep exits 2 → verify_edge_networks returns 1 → edge restoration returns failure and automatic rollback reports failure.
- **Canon:** OBS-04 — a false failure trains operators to distrust rollback diagnostics.
- **Fix design:** In restore_edge_backups, use a quoted EDGE_RESTORE delimiter and pass env, edge_dir, backup_root, transaction ID, and prefer_flip as positional arguments. Match each JSON key with a remote-side quoted_network variable and grep -Fq -- "$quoted_network".
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — run the captured EDGE_RESTORE payload with docker inspect returning all expected network keys; assert restoration exits 0 and stderr contains neither “Trailing backslash” nor “missing restored network”.

## D9a — UNVERIFIED — LOW

- **Evidence:** scripts/deploy/recognition-service.sh:646
  > [\[{]

  The boot-smoke success path passes its health message through sanitize_deploy_diagnostic at line 2544; the sanitizer’s awk program contains this character class. The incident log records the awk escape warning during that path.
- **Evidence gap:** The warning text came from operator-pasted deploy output, not a retained log. macOS BWK awk 20200816 (the local deploy host's awk), GNU Awk 5.2.1, and mawk 1.3.4 all run this class silently in isolation; the emitting implementation is unidentified. Fix stays low-cost and behaviour-preserving, so it ships regardless.
- **Mechanism:** Some awk implementations warn that the unnecessary escape before [ is treated as a plain [. The resulting character class still matches either [ or {; local GNU Awk 5.2.1 and mawk 1.3.4 both matched those two characters and rejected x.
- **Failure scenario:** A healthy boot smoke sanitizes “smoke health OK” → awk emits an escape warning to stderr → smoke still exits successfully, leaving a warning beside the success message.
- **Canon:** OBS-04 — the warning is non-actionable and competes with deploy diagnostics.
- **Fix design:** In sanitize_deploy_diagnostic, express the opener as alternatives outside the character class, such as (\[|[{]), in both quoted-key regexes. Keep the character matching unchanged and remove the implementation-dependent warning.
- **Regression test:** scripts/deploy/tests/test_sanitize_deploy_diagnostic.py — feed double- and single-quoted secret mappings opened by [ and {; assert values are redacted and stderr has no awk escape warning.

## D9b — CONFIRMED — LOW

- **Evidence:** scripts/deploy/recognition-service.sh:2898
  > # Failed stop is not confirmed absence (MCP10415). Query explicit

  The preceding stop in abort_cutover_candidate is conditional at line 2894. The next lines query the unit state, and line 2925 accepts cleanup only for LoadState=not-found, ActiveState=inactive, and SubState=dead.
- **Mechanism:** systemctl stop writes its “Unit not loaded” diagnostic before the script checks its nonzero status. A confirmed absent unit is an accepted cleanup state; any other state preserves the stop failure and makes the remote cleanup fail.
- **Failure scenario:** The candidate unit was already unloaded → systemctl prints “Failed to stop … Unit … not loaded” → systemctl show confirms not-found/inactive/dead → candidate cleanup continues successfully. The message is logged noise, not a silently ignored arbitrary stop failure.
- **Canon:** OBS-04 — expected absence should not look like an operator-action error.
- **Fix design:** Capture systemctl stop output in abort_cutover_candidate. Discard it only after the explicit absent-state check succeeds; emit a useful warning and preserve the stop status for every other state.
- **Regression test:** scripts/deploy/tests/test_cutover_recovery_safety.py, test_abort_payload_succeeds_when_candidate_unit_is_absent — retain the zero exit and cleanup assertions, and assert stderr omits “Failed to stop”. Keep test_abort_payload_propagates_genuine_cleanup_failure failing closed.

## D9c — CONFIRMED — LOW

- **Evidence:** apps/prototype-description-service/scripts/verify_identity_schema.py:109
  > unexpected_tables = sorted(actual_table_set - expected_table_set)

  At line 360 the checker separately reads alembic_version for the migration revision. Its output at line 541 prints every remaining table as a warning. The normal test catalog at apps/prototype-description-service/recognition/tests/scripts/test_verify_identity_schema.py:238 includes alembic_version.
- **Mechanism:** EXPECTED_SCHEMA_TABLES contains identity schema relations, while alembic_version is migration metadata read by a separate revision check. Since it is not included in the identity-table set, a healthy database is labelled unexpected even though the verifier accepts it.
- **Failure scenario:** A normally migrated database has every expected identity table plus alembic_version → the schema verifies successfully but prints warning: unexpected_tables=alembic_version.
- **Canon:** OBS-04 — this known-good metadata table creates a false warning on every normal database.
- **Fix design:** In verify_identity_schema.py, keep alembic_version outside the required identity-schema table set, but exclude this recognized metadata relation from the advisory unexpected_tables difference. Continue checking its revision through the existing revision query.
- **Regression test:** No scripts/deploy/tests file owns this verifier. Extend apps/prototype-description-service/recognition/tests/scripts/test_verify_identity_schema.py to assert that the healthy fixture including alembic_version has no unexpected_tables warning and still validates its revision.

## D9d — UNVERIFIED — LOW

- **Evidence:** Makefile:1109
  > -include Makefile.d/*.mk

  Makefile.d is absent from this snapshot, so Makefile.d/lane-gate.mk cannot be inspected. In the visible mk files, test-scripts prerequisite declarations appear at mk/evals.mk:32, mk/deploy.mk:359, and mk/lane-overlaps.mk:81; check-all prerequisite declarations appear at mk/lane-maintenance.mk:37 and mk/lane-overlaps.mk:82. These lines contain no recipes, and do not establish an overriding-recipe warning.
- **Mechanism:** The hypothesized second recipe source is absent, so the claimed overlap and warning cannot be verified here.
- **Failure scenario:** UNVERIFIED — if Makefile.d/lane-gate.mk defines recipes for targets already given recipes elsewhere, make may report an override; this checkout does not contain that file to compare.
- **Canon:** none — the triggering duplicate is unavailable for review.
- **Fix design:** In a checkout containing Makefile.d/lane-gate.mk, give each overlapping target one recipe owner and express additional work as prerequisites or dependencies. Inspect the actual target definitions before changing ownership.
- **Regression test:** No scripts/deploy/tests file applies. Add a make-level check in the checkout containing Makefile.d that invokes the affected target and asserts stderr has no “overriding recipe for target”.

## D12 — REFUTED — LOW

- **Evidence:** The sweep found one mis-expansion, already reported as D6. The other remote heredoc forms include scripts/deploy/recognition-service.sh:2317
  > $(cat <<'SMOKE'

  and scripts/deploy/recognition-service.sh:1900
  > docker network create \\

  The quoted inner SMOKE heredoc protects its body; the EDGE line continuation reduces to one remote backslash as intended.
- **Mechanism:** The checked REMOTE, EDGE, SMOKE_WRAP, FLIP_EDGE, and SCOPED_PRODUCER payloads either inject local values intentionally, preserve remote variables with escaped dollar signs, or use an inner quoted heredoc. None showed another real mis-expansion. The LOADMEDIA heredoc in smoke-gate.sh feeds the current shell’s loop; it is not a remote or child-shell payload.
- **Failure scenario:** No additional concrete failure was found beyond D6.
- **Canon:** none — the remaining inspected payloads behaved as intended.
- **Fix design:** Keep remote heredoc bodies quoted where possible and pass dynamic values as arguments or environment values. Apply the D6-specific repair in restore_edge_backups; no separate D12 change is supported by this sweep.
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — assert captured FLIP_EDGE and SCOPED_PRODUCER payloads preserve intended remote variables and literal patterns; retain the D6 JSON-network assertion above.

## New defects

None. D6 is the only real heredoc mis-expansion found and is already listed.

## Method

- Read scripts/deploy/recognition-service.sh in bounded ranges: 630–672, 910–954, 1880–1960, 2230–2609, 2700–2980, 3070–3150, 3628–3774, 3778–3855, 3950–4080, 4370–4505, and 4680–4730.
- Read scripts/deploy/lib/smoke-gate.sh:130–205 and 276–300; searched every heredoc delimiter in the main script and deploy library files.
- Read verify_identity_schema.py:1–122, 350–365, and 535–550; 001_identity_schema.py:90–138; and the verifier test ranges 190–260 and 610–660.
- Inspected Makefile inclusion at Makefile:1–45 and 143–155, its optional Makefile.d include at line 1109, and target declarations in mk/*.mk. Makefile.d is absent.
- Reproduced D6 by writing the copied unquoted heredoc line to /tmp/deployfix_d6_remote.sh, then running it under Bash with networks={"acx-prod-net":{"Driver":"bridge"}}. The remote payload showed grep -q "\\"$network\\"" and Bash passed grep \acx-prod-net\, producing “grep: Trailing backslash”.
- Ran the source awk character class with GNU Awk 5.2.1 and mawk 1.3.4. Both matched [ and { and rejected x; neither local implementation printed a warning.
