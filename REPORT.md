# F14 — FIR-12 join-boundary hygiene (`strata_join.py`)

Lane `lane/f14`. Files owned: `strata_join.py` + `test_eval_harness_strata_join.py`.
Public signatures (`load_stratum_index`, `join_by_stratum`, `StratumIndex`, `StratumReport`) kept; `StratumIndex` gained a trailing `sha256_by_media_id` field used only by the join.

Gate: `scene/tests` 1278 passed / 4 failed. Failures are the known PGPASSWORD / `InsecureProductionConfigError` quartet (`test_describe_route.py::test_create_app_registers_route_and_upload_cap` + three `test_describe_run_reclaim.py` startup tests). Nothing else new.

---

## BR-20 CLOSED (prior commit)

`49291fa477b8e2fc58aeb9cc42dfbabfc012aca7` `fix(eval): reject str/dict identities on join-record subjects`

`_subjects_of` now raises `StratumJoinError` on `str` / `dict` identity fields, matching `_identities` / `_entry_identities`. Malformed input no longer yields a plausible `unique_subjects` count.

Tests: `test_subjects_of_rejects_str_and_dict_identities`, `test_join_record_subjects_reject_str_and_dict`. Canon: **rg-008**, **rg-015**. Not re-mutated this turn (already committed before this continuation).

---

## BR-23 CLOSED (prior commit)

`b01e7f915e18aa0cc80daf9170f628ba4321dd88` `fix(eval): reject entry strata missing from strata_counts`

Load raises when `entries[i].stratum` is absent from `strata_counts`. The `.get(name, 0)` denominator path is gone; undeclared cells cannot render as complete with a zero denominator.

Test: `test_load_rejects_entry_stratum_missing_from_strata_counts`. Canon: **rg-008**, **rg-015**. Not re-mutated this turn.

---

## BR-22 CLOSED (this turn)

`c2bb51c9033ab93b30ca3c01a31c7df3307cd5d0` `fix(eval): canonicalize mixed sha256/media_id records to one image`

### What changed

`image_key = sha256 if sha256 is not None else str(media_id)` let one still keyed by sha256 (caption) and once by media_id (`FaceRunItem`) count as two images, inflating `n_images` and flipping `incomplete` (MLDATA-07). `_as_media_id` also coerced digit strings (`"6"`), a dual envelope the frozen schema never produces (rg-015).

Fix:

- Index `sha256_by_media_id` at load. Join keys every record to that canonical sha256 before inserting into the image set.
- One record carrying both keys must agree on that sha256, or raise `disagree on image`.
- Load rejects one `media_id` mapped to two sha256s (the 1:1 map would otherwise be last-write-wins).
- `_as_media_id` accepts only `int` (bool still excluded first). Digit strings and JSON bools raise `must be an int`.

`join_by_stratum` / `load_stratum_index` signatures unchanged. `StratumIndex` keeps its existing fields in the same order; `sha256_by_media_id` is appended.

### New tests

| Test | Asserts |
|---|---|
| `test_sha256_and_media_id_of_same_image_count_once` | Frozen Pacino still (`media_id=6`): `{sha256}` + `{media_id: 6}` → `n_images=1` |
| `test_face_run_item_and_sha256_caption_of_same_image_count_once` | Mixed `FaceRunItem` + caption envelope, same still |
| `test_three_envelopes_of_same_image_count_once` | sha-only + media_id-only + both-on-one-record → 1 |
| `test_mixed_keys_of_two_images_still_count_twice` | Pacino sha + Winehouse media_id stay 2 |
| `test_mixed_keys_do_not_flip_incomplete` | Declared 2, mixed keys of image 1 only → `n_images=1`, `incomplete=True`, gap reported |
| `test_mixed_keys_covering_declared_cell_is_complete` | Declared 1, three envelopes of that image → complete, no gaps |
| `test_record_keys_disagree_on_image_identity` | sha of A + media_id of B on one record raises |
| `test_digit_string_media_id_is_rejected_on_join` | `"6"` and `"06"` raise |
| `test_digit_string_media_id_is_rejected_at_load` | Manifest `media_id: "6"` raises |
| `test_bool_media_id_is_rejected_even_when_one_is_indexed` | `True` cannot join as media_id 1 |
| `test_load_rejects_media_id_mapped_to_two_sha256s` | 1:1 canonical map is load-time, not last-write-wins |

### TEST-15 mutants

**Mutant A — restore `image_key = sha256 if sha256 is not None else str(media_id)`.**
RED (5 failed):

```
FAILED ...::test_sha256_and_media_id_of_same_image_count_once - assert 2 == 1
FAILED ...::test_face_run_item_and_sha256_caption_of_same_image_count_once - assert 2 == 1
FAILED ...::test_mixed_keys_do_not_flip_incomplete - assert 2 == 1
FAILED ...::test_mixed_keys_covering_declared_cell_is_complete - assert 2 == 1
FAILED ...::test_three_envelopes_of_same_image_count_once - assert 2 == 1
```

**Mutant B — restore digit-string coerce in `_as_media_id`.**
RED (2 failed):

```
FAILED ...::test_digit_string_media_id_is_rejected_on_join - Failed: DID NOT RAISE StratumJoinError
FAILED ...::test_digit_string_media_id_is_rejected_at_load - Failed: DID NOT RAISE StratumJoinError
```

Both mutants reverted. File suite 25 passed after restore.

Canon: **rg-015** (no invented dual envelope; canonical id comes from the manifest, not `str(media_id)`), **rg-008** (reject digit-string / bool media_id at the boundary), **MLDATA-07** (mixed FaceRunItem + caption must not inflate `n_images` and hide `incomplete`).

---

## Not closed

Nothing. BR-20, BR-22, BR-23 all landed. Did not touch `fir_bakeoff_run.py`, `gallery_split.py`, or `open_set_identification.py`.
