# Lane r8c report — FIR-12 BR-76

## Outcome and judgement

Chose option **(a)**. The effective upstream guard already existed at base commit
`3835cef2` in `_normalise_gallery_map`; the defect remaining at base was the dead
duplicate in `_assert_invariants`. I removed that downstream loop and left a
comment identifying the upstream observation point. This is a refactor-only
change: no new behaviour was introduced, and the existing BR-65 test already
exercises caller-supplied mismatches at the correct boundary.

## Construction paths and call sites

Repository search used:

```text
rg -n --glob '*.py' "GallerySplit\(|build_disjoint_galleries\(|Template\(" .
```

The entry and split construction paths are:

1. Public `GallerySplit(g1=..., g2=..., ...)`: callers provide arbitrary mapping
   keys and `Template.subject_id` values independently. Therefore it can produce
   a mismatching pair. `_normalise_gallery_map` must compare their independently
   normalised identities before `_with_subject` rewrites the template. Direct
   uses exist in `scene/tests/test_eval_harness_gallery_split.py` and
   `scene/tests/test_eval_harness_fir_search_adapter.py`.
2. `dataclasses.replace(existing_split, g1=..., g2=...)`: generated construction
   reruns `GallerySplit.__post_init__` and can likewise receive a mismatching
   replacement mapping. This path is exercised in the owned gallery-split tests.
3. `build_disjoint_galleries` with caller-supplied `Template`: `_as_template`
   compares the normalised `Template.subject_id` with the normalised roster key
   before canonicalisation, so a mismatch is possible as input but rejected at
   that earlier builder boundary. The production caller is
   `scripts/eval_harness/fir_bakeoff_run.py`; tests also call the builder.
4. `build_disjoint_galleries` with a string template id: `_as_template` constructs
   `Template(..., subject_id=canonical_subject)`, so this path cannot create a
   mismatch.
5. The builder's internal enrollment path: `_enroll_component` keys `enrolled`
   with the same `subject_id` used to select templates from `by_subject`, whose
   entries have already passed `_as_template`; its final `GallerySplit(...)`
   therefore cannot create a mismatch.
6. Internal `_with_subject`, `_canonical_template`, and probe tuple
   normalisation create replacement `Template` instances, but none is an
   independent gallery key/template construction boundary. `_with_subject` is
   precisely the actuator that made the old `_assert_invariants` loop unable to
   observe caller input.

Because paths 1 and 2 can supply a mismatch, deletion without an upstream guard
(option b) would silently relabel caller media and is not valid.

## Baseline

Command (from `apps/prototype-description-service`, with the required venv and
`PYTHONPATH=$PWD`):

```text
python -m pytest scene/tests/test_eval_harness_gallery_split.py \
  scene/tests/test_eval_harness_fir_bakeoff_run.py -q -p no:cacheprovider
```

Result: **108 passed, 0 failed** in 4.61s.

## TEST-15 mutant proof

Existing evidence test:
`test_gallery_map_key_subject_mismatch_raises`, parameterised for both G1 and G2.
The mutant removed the production guard before `_with_subject`:

```diff
@@ -182,11 +182,6 @@ def _normalise_gallery_map(
     for subject_id, template in gallery_map.items():
         key = _normalise_subject_id(subject_id, gallery=gallery)
-        template_key = _normalise_subject_id(template.subject_id, gallery=gallery)
-        if template_key != key:
-            raise GallerySplitError(
-                f"{gallery} key {key!r} holds template for {template.subject_id!r}"
-            )
         if key in out:
```

Full owned-suite result with mutant: **2 failed, 106 passed** in 2.54s. The REDs
were exactly:

```text
test_gallery_map_key_subject_mismatch_raises[g1] — DID NOT RAISE
test_gallery_map_key_subject_mismatch_raises[g2] — DID NOT RAISE
```

The mutant was reverted using an explicit patch before the final run.

## Final verification

After removing only the dead downstream duplicate, the final owned-suite result
was **108 passed, 0 failed** in 2.58s. `git diff --check` also passed.

## Limitations / transport blocker

The workspace permission profile exposes `.git` read-only. The required commit
failed before staging with:

```text
fatal: Unable to create '/home/ubuntu/l1/r8c/.git/index.lock': Read-only file system
```

Consequently I could not commit either the refactor or this report. I did not
attempt a prohibited sandbox escalation. The initial worktree also contained
pre-existing untracked `PING.md` and `codex.log`, which are outside this lane's
owned files; I did not edit or remove them. Thus a clean working tree and the
required committed report were impossible under the supplied permissions.
