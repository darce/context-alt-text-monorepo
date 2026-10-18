# Lane R7-gsplit — FIR-12-BR-65 / FIR-12-BR-66

## Finding: both target defects were already fixed in base b2ad134a

Scope was `apps/prototype-description-service/scripts/eval_harness/gallery_split.py`
and its tests (`apps/prototype-description-service/scene/tests/test_eval_harness_gallery_split.py`).
Before writing anything, I read the current file and found the guard tests the
brief said don't exist already present at test file lines 650-754:

- `test_gallery_map_key_subject_mismatch_raises[g1|g2]` (BR-65, map-level check,
  `gallery_split.py` `_normalise_gallery_map` ~L183-192)
- `test_builder_roster_key_subject_mismatch_raises` (BR-65, `_as_template` roster-key
  check, ~L234-241)
- `test_withheld_probe_templates_are_sorted_and_stripped_independent_of_insertion`
  (BR-66, constructor-site `withheld_probe_templates` normalisation, ~L104-110)

`git log --oneline -- <test file>` traces these to commit
`a829e663d9b3bf94440730afac24c07daf80a2dd` ("fix(eval): FIR-12 BR-65/BR-66 pin key
mismatch and withheld normalisation", lane F40), which is an ancestor of this lane's
base `b2ad134a` (merged into `int/round4` via `lane-f42`'s merge chain before this
lane started). No code or test edit was needed or made in this lane — writing a
second, near-duplicate set of tests over the same guards would not add coverage.

Per TEST-15 / "independent review beats self-triage" I did not take lane F40's own
report (`docs/tasks/fir/lane-reports/F40.md`) on faith. I re-ran all three control
mutants myself on the remote gate, independently, from a clean b2ad134a tree, one
throwaway commit per mutant, reverted with `git reset --hard HEAD~1` after each RED
confirmation. Working tree is clean at `b2ad134a` again; no fix commits exist for
Fix 1 / Fix 2 because there was nothing left to fix.

## Mutant A — BR-65, `_normalise_gallery_map` raise arm (gallery_split.py ~L186-189)

Deleted:
```python
if template_key != key:
    raise GallerySplitError(
        f"{gallery} key {key!r} holds template for {template.subject_id!r}"
    )
```
Gate (`gate-lane.sh r7-gsplit -k gallery_split`), commit `48babf2cd` (reverted):
```
FAILED scene/tests/test_eval_harness_gallery_split.py::test_gallery_map_key_subject_mismatch_raises[g1]
FAILED scene/tests/test_eval_harness_gallery_split.py::test_gallery_map_key_subject_mismatch_raises[g2]
2 failed, 33 passed, 1638 deselected in 12.18s
```
RED confirmed independently.

## Mutant B — BR-65, `_as_template` roster-key raise (gallery_split.py ~L238-241)

Deleted:
```python
if template_subject != canonical_subject:
    raise GallerySplitError(
        f"template {value.template_id!r} subject_id {value.subject_id!r} "
        f"does not match roster key {subject_id!r}"
    )
```
Gate, commit `5d4a417f3` (reverted):
```
FAILED scene/tests/test_eval_harness_gallery_split.py::test_builder_roster_key_subject_mismatch_raises
1 failed, 34 passed, 1638 deselected in 5.19s
```
RED confirmed independently. (The map-level test stays green here, as expected —
it exercises the other check.)

## Mutant C — BR-66, constructor-site withheld normalisation (gallery_split.py ~L104-110)

Replaced:
```python
_normalise_template_tuple(
    self.withheld_probe_templates, gallery="withheld_probe_templates"
),
```
with a bare `tuple(self.withheld_probe_templates),`.
Gate, commit `4a55c1106` (reverted):
```
FAILED scene/tests/test_eval_harness_gallery_split.py::test_withheld_probe_templates_are_sorted_and_stripped_independent_of_insertion
AssertionError: assert [('Zoe ', 'z1'), ('Ann ', 'n1')] == [('Ann', 'n1'), ('Zoe', 'z1')]
1 failed, 34 passed, 1638 deselected in 5.02s
```
RED confirmed independently.

All three throwaway mutant commits were reset out (`git reset --hard HEAD~1`);
`git status` and `git diff --stat b2ad134a` are both clean. No full-suite gate
re-run was needed post-change since no production or test line differs from the
given baseline (`1668 passed, 4 skipped, 1 deselected, 14 warnings`, per the
operator-supplied baseline — not re-measured, per instructions).

## Dead-invariant sweep (optional item)

`_assert_invariants` (gallery_split.py L340-395) is called only from
`build_disjoint_galleries`, before the `GallerySplit(...)` constructor runs.
One check shares the exact rewrite-blindness shape the brief already named for
`GallerySplit.__post_init__`:

- **L369-375** (dead):
  ```python
  for gallery_name, gallery in (("g1", g1), ("g2", g2)):
      for subject_id, template in gallery.items():
          if template.subject_id != subject_id:
              raise GallerySplitError(...)
  ```
  By the time `build_disjoint_galleries` populates `g1`/`g2`, every `Template` in
  them has already passed through `_as_template`, which calls
  `_with_subject(value, canonical_subject)` **unconditionally after** its own
  roster-key check — including under mutant B, where the check that should have
  raised is gone but the rewrite still runs. So `template.subject_id` is always
  already forced equal to the dict key by the time this loop inspects it; it is
  a sensor reading a value the actuator already normalised, canon OBS-12 ("sensors
  must touch the controlled stock" — this one touches the stock only after
  something else already wrote to it). Confirmed live-dead by mutant B above: the
  builder test still went RED, but via the earlier `_as_template` path being the
  *only* thing that could catch it — this copy fired for neither mutant A nor B in
  either of my runs.

No other check in `_assert_invariants` shares this failure mode:
- **L347-359** (`g1_ids & g2_ids`, `g1_ids/g2_ids & probe_ids`) key off
  `template_id`, a field `_with_subject` never touches — dead only if
  `build_disjoint_galleries`'s own `seen_ids` duplicate-id check (elsewhere in
  the function, upstream of `_assert_invariants`) is also live; not the same
  rewrite mechanism, not investigated further here (out of scope for this lane).
- **L360-368** (`dropped`, `both`) key off dict *keys*, which come straight from
  the roster loop's own normalised `subject_id`, never from `template.subject_id`
  — unaffected by the `_with_subject` rewrite.
- **L379-391** (media disjointness) and **L392-396** (empty gallery) operate on
  `media_ids` / dict emptiness, fields `_with_subject` does not rewrite.

Filing as a separate finding per instructions — not fixed in this lane.

## Unfinished work

None within the assigned scope. The L369-375 dead check above is reported, not
fixed, per the brief's explicit "do NOT fix them this lane" instruction.
