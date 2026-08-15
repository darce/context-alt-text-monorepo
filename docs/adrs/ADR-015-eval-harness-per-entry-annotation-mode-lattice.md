# ADR-015: Eval-harness per-entry `annotation_mode` lattice is raw-mapping-only

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** FIR-11 Slice 2 (S2R3-10 pin; S2R4-20 record)
- **Context task:** FIR-11 (`docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md`)
- **Related:** `scripts/eval_harness/manifest.py` (`GoldenEntry` / `GoldenManifest`), `scripts/eval_harness/report.py` (`_resolve_score_annotation_mode`), `test_per_entry_lattice_is_raw_mapping_only`
- **Heuristics:** rg-009 (no task-specific logic in generic modules — the lattice is a contract, not a FIR-11 special case), AUDIT-08 (durable record of an intentional unreachability)

## Status

Accepted

## Date

2026-08-15

## Context

Detection P/R is only honest when `annotation_mode=exhaustive` (every face is
boxed). `roster_only` means the labelled face count is a **lower bound**, so
scoring it as exhaustive overstates precision/recall. Identification P/R is
only honest when every identity claim has per-face box lineage.

The scorer resolves a single detection contract from entry stamps
(`_resolve_score_annotation_mode` in `report.py`). That resolver implements a
lattice:

- every scored entry must carry a stamp and those stamps must agree
- mixed stamps fail loud (`detection_refuses_mixed_annotation_mode`)
- an explicit argument may only **narrow** (most-restrictive-wins);
  explicit `exhaustive` never overrides a `roster_only` stamp
- omission is not exhaustive

On disk, a v3 `GoldenManifest` has a **document-level** `annotation_mode`.
`GoldenEntry` has **no** `annotation_mode` field and `extra="forbid"`.
`test_per_entry_lattice_is_raw_mapping_only` asserts both facts — it **pins
the unreachability**. The mixed-stamp guard and the explicit-cannot-widen
rule are therefore exercised only through raw dicts, never through a
loaded manifest file.

Two source comments record the pin (`manifest.py` ~538–540, `report.py`
~381–385). There was no ADR. This document freezes the design so a later
schema change cannot treat the pin as an accident.

### Constraints from prior review

- Do not invent detection numbers on `roster_only` ground truth.
- Do not guess which contract applies when stamps disagree.
- Typed `GoldenEntry` stays `extra="forbid"`; new per-entry keys are
  schema changes, not silent extras.
- On-disk v3 manifests stay document-homogeneous (one mode per file).

## Current State Inventory

| Surface | What it does with `annotation_mode` |
| --- | --- |
| `GoldenManifest.annotation_mode` | Document-level required field. Every on-disk v3 manifest, including `scene/tests/seed/golden.json` (`roster_only`). |
| `GoldenEntry` | **No field.** `extra="forbid"`. A JSON key `annotation_mode` on an entry fails validation. |
| `cli._cmd_score` | Dumps typed entries and stamps the **parent** document mode onto every dict. Never reads a per-entry key from disk. |
| `fusion_runner.manifest_entries_as_dicts` | Same: stamps `manifest.annotation_mode` onto every dumped entry. |
| `report._entries_as_dicts` / `_stamp_missing_annotation_mode` | On a typed manifest, fills omitted stamps from the document mode. Never overwrites a real stamp. Blank/whitespace is not omitted (S2R3-02). |
| `report._resolve_score_annotation_mode` | The lattice. Reads `entry["annotation_mode"]` from raw mappings only. |
| `score_run_record` / `score_face_run_record` | Consume the resolved mode. Roster-only / missing / mixed / empty → refuse (or raise on the face path). |
| `test_per_entry_lattice_is_raw_mapping_only` | Pins `'annotation_mode' not in GoldenEntry.model_fields` and rejects a constructor kwarg. |

### Raw-dict callers (the only way the lattice is reached)

1. **Flatteners that homogenize a typed document** — `cli._cmd_score`,
   `fusion_runner.manifest_entries_as_dicts`, `_entries_as_dicts`. These
   always stamp one parent mode. They never produce mixed stamps.
2. **Tests** — `test_score_roster_only_refusal.py`,
   `test_identification_boxed_gt.py`, `test_exhaustive_detection_arithmetic.py`,
   and several `scene/tests/test_eval_harness_*.py` helpers pass raw dicts
   (stamped, unstamped, mixed, blank) straight into `score_run_record`.
3. **Any future programmatic caller** that builds entry mappings by hand
   and calls `score_run_record` / `_resolve_score_annotation_mode` without
   going through `load_manifest`.

There is **no** on-disk caller of a per-entry mode.

### What the guard therefore does and does not protect

**Protects**

- A programmatic or test caller that hands the resolver mixed stamps, a
  partial stamp, a blank stamp, or `explicit=exhaustive` against a
  `roster_only` stamp. Those fail loud or refuse; they do not score.
- A flattener regression that starts writing disagreeing stamps: mixed
  still dies at resolve time.

**Does not protect**

- On-disk JSON. A v3 file cannot express a per-entry mode at all, so it
  cannot express a mixed-mode corpus. The operator cannot opt a single
  image into `exhaustive` inside a `roster_only` file.
- Homogenizing flatteners. `load_manifest` → dump → stamp-parent erases
  any hypothetical per-entry key **before** the resolver would have seen
  it (and `GoldenEntry` already rejected the key).
- Caption-only honesty. Refusal is about face metrics; caption scoring
  still runs.

## Decision

**Keep the per-entry `annotation_mode` lattice raw-mapping-only.** Do not
add `annotation_mode` to `GoldenEntry`. On-disk manifests stay
document-homogeneous. The mixed-stamp guard and the explicit-cannot-widen
rule remain a defensive net for raw callers and tests, not an operator
feature.

### Chosen design rules

1. **One mode per document.** `GoldenManifest.annotation_mode` is the
   only on-disk contract. Mixed detection contracts are two manifests,
   scored separately.
2. **Typed entries cannot carry a stamp.** `GoldenEntry` stays
   field-absent + `extra="forbid"`. The pin test stays red if anyone adds
   the field without a deliberate schema change.
3. **Flatteners stamp the parent, they do not invent exhaustiveness.**
   Omission is not exhaustive. Blank/whitespace is not inheritable.
4. **Raw mappings keep the lattice.** Mixed / cannot-widen / missing
   remain executable against dicts so a future caller cannot silently
   score a Frankenstein corpus.

### Target outcome

An operator reading a v3 file can name the detection contract from one
field. A reviewer reading `test_per_entry_lattice_is_raw_mapping_only`
knows the unreachability is intended. A schema change that adds a
per-entry mode has a checklist (below) instead of a silent field add.

## Why This Decision

### Mixed modes in one report are not a product need

Detection P/R under `exhaustive` and a lower-bound count under
`roster_only` are different claims. Averaging them in one
`faces.detection` block would be the same greenwash the refusal exists
to stop. Two files, two reports is the honest split.

### The pin is already the contract

S2R3-10 did not "forget" to add the field. It forbade it and wrote a
test that dies if the field appears. Recording that as an ADR stops the
next slice from "fixing" the unreachability by making the lattice
loadable without a schema review.

### Flatteners would fight a reachable field

If `GoldenEntry` grew `annotation_mode` tomorrow but flatteners kept
stamping the parent, on-disk per-entry values would still be overwritten
(or only filled when missing). Reachability without a flattener rewrite
is a lie.

## Alternatives Considered

### 1. Make the lattice reachable on disk (add `GoldenEntry.annotation_mode`)

Rejected as the current design, **recorded as the honest alternative**
if a future corpus actually needs mixed stamps in one file.

What would have to change:

1. Add an optional `annotation_mode` field on `GoldenEntry` (schema bump
   / documented additive field; `extra="forbid"` otherwise still holds).
2. Rewrite `test_per_entry_lattice_is_raw_mapping_only` — it currently
   **forbids** that field. Replace it with a pin that the field is
   optional and that mixed files fail at load or at resolve, deliberately.
3. Stop flatteners (`cli._cmd_score`, `manifest_entries_as_dicts`,
   `_entries_as_dicts`) from blindly stamping the parent over a real
   per-entry value. Keep `_stamp_missing_annotation_mode` fill-only.
4. Decide load-time policy: refuse mixed files at `load_manifest`, or
   load them and let the resolver refuse at score. Prefer load-time —
   fail before GPU harvest.
5. Document the operator rule: a per-entry `exhaustive` stamp is a claim
   that **that image** is fully boxed, not a way to sneak detection P/R
   out of a `roster_only` document.
6. Cross-link the two source comments in `manifest.py` and `report.py`
   (out of scope for this lane; see HANDOFF).

Why not now: no on-disk consumer needs mixed stamps. The shipped golden
is uniformly `roster_only`. Adding the field would expand the schema for
a test-only lattice and invite a flattener bug that re-homogenizes
away the new field.

### 2. Drop the raw-mapping lattice entirely

Rejected. Then a programmatic caller that mixes stamps, or a flattener
that goes wrong, fails open into a scored P/R. The lattice is cheap and
already tested.

### 3. Leave the pin undocumented (status quo before this ADR)

Rejected. Two comments plus a test name are not a decision record.
S2R4-20 exists because reviewers could not tell whether unreachability
was a bug or a choice.

## Consequences

### Positive

- The unreachability is citable: `ADR-015`, not "read the pin test".
- Future schema work has an explicit change list instead of a drive-by
  field add.
- Operators keep one mode per file; wrappers and docs can talk about
  "the shipped golden is `roster_only`" without per-entry footnotes.

### Negative

- A mixed-mode corpus cannot live in one JSON file. That is accepted:
  split the file.
- The mixed-stamp and cannot-widen tests look like "dead" production
  paths because no disk file reaches them. They are not dead; they
  guard raw callers.

### Guardrails for a follow-on schema change

- Do not add `GoldenEntry.annotation_mode` in a cleanup slice. It is a
  schema decision that supersedes this ADR.
- If that field is added, land a new ADR (or amend this one) **before**
  deleting `test_per_entry_lattice_is_raw_mapping_only`.
- Flatteners must preserve per-entry stamps; fill-missing only.
- `load_manifest` must take a position on mixed files (prefer refuse).
- Do not special-case `task_ref` or FIR-11 in the resolver (rg-009).

## References

- Pin: `scripts/eval_harness/tests/test_score_roster_only_refusal.py` —
  `test_per_entry_lattice_is_raw_mapping_only`
- Comments to cross-link (not edited in this lane):
  `scripts/eval_harness/manifest.py` (`GoldenEntry` class comment),
  `scripts/eval_harness/report.py` (`_resolve_score_annotation_mode`
  docstring, `_entries_as_dicts` docstring)
- Task plan: `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md`
- Exit / refusal contract: `scripts/eval_harness/README.md` (S2R4-09 / S2R4-10)
