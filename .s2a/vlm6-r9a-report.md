# Lane vlm6-s2-runner / r9a — VLM6-R2-C-02 wording fix

**Item:** VLM6-R2-C-02 follow-up (`#717` / `#719`)
**Not in scope this pass:** VLM6-R2-G-02 (already closed at HEAD; caption freeze not touched), VLM6-S7-01 (removed; stripped sandbox cannot resolve destination SHAs)

## Verdict

Done. Caveat no longer reads trap-media count as an FN share. Manifest digest unchanged. Both caveat tests watched fail on the old phrasing, then went green after restore.

## Final emitted caveat line (verbatim)

```
- ⚠ fixture-local detection frame — recall is NOT a population estimate: fn=5 includes misses from 2 deliberate trap media (9 `localwp/uploads/stranger-fn-miss.jpg`, 10 `localwp/uploads/mixed-fn-miss.jpg`) added so the pre-HARM-01 named-only FN formula goes red; the attributable FN share is not derivable from this table because a trap image with several GT faces misses several; this corpus is a synthetic determinism anchor (11 images), not a sampled population.
```

## Digests (sha256sum of generator output)

| Artifact | Old | New |
| --- | --- | --- |
| manifest | `32eff309b37822deb4474ca05dac4b0343e7a2378e4d25ab013020b5c565b5bd` | `32eff309b37822deb4474ca05dac4b0343e7a2378e4d25ab013020b5c565b5bd` **UNCHANGED** |
| run | `5a589466630eb7dc9296f7a947563b06d1e3908dbdb905123b4d334a291ac8f4` | `f0e8298a96df12c6ea114c05a65158abe2bba24b6362407594a9d71354e384db` |
| report-json | `cd56435dca8542f915a4decb9955e95c750ab1560bc8399521d8b361d08a32e9` | `b6d6b88534a6616546eaaebda4120c2196d5d1e7abd9ddf454ee92cfd2bf4524` |
| report-md | `92c464416b961622a0a31606e865dad6cca749d4c3abe30849a59faa61a2d3c2` | `b739f5ea10fb661f4667d283b28c93ab261e4466c1c40e1f7c5b112ea4852b26` |

Corpus body unchanged: only `corpus_traps[0].note` (media 9) and the MD caveat sentence moved.

## What changed

- **A** `report.py` `_fixture_local_detection_caveat_line`: `fn=M includes misses from N deliberate trap media`; N is trap MEDIA; docstring cites rg-015 (no invented FN share).
- **B** media 9 note: `1 of 4 detection FN on the freeze` → `contributes exactly 1 detection FN`. Media 10/11 notes left alone.
- **C** generator regen (not hand-edit). `_FROZEN_DIGESTS` re-pinned from `sha256sum`.
- **D** both caveat tests pin the new sentence + `"{n} of fn=" not in` + keep kind-only / stripped / empty / None negatives.
- Face test also live-renders with `affects` intact so a renderer mutation can go red (committed-MD checks cannot see a renderer-only regression).

Caption freeze (`S2A-determinism-anchor-*`) not touched.

## TEST-15 mutation transcripts

Mutation (uncommitted, then restored): renderer return value set back to
`"{n} of fn={fn} come from deliberate trap media ..."`.

### test_fixture_local_detection_caveat_filters_on_affects_only — RED

```
scene/tests/test_eval_harness_report.py:4487: in test_fixture_local_detection_caveat_filters_on_affects_only
    assert "fn=5 includes misses from 1 deliberate trap media" in line
E   AssertionError: assert 'fn=5 includes misses from 1 deliberate trap media' in '- ⚠ fixture-local detection frame — recall is NOT a population estimate: 1 of fn=5 come from deliberate trap media (9...1 named-only FN formula goes red; this corpus is a synthetic determinism anchor (11 images), not a sampled population.'
```

### test_fixture_local_detection_caveat_present_and_disappears_without_affects — RED

```
scene/tests/test_eval_harness_face_determinism_anchor.py:455: in test_fixture_local_detection_caveat_present_and_disappears_without_affects
    assert "fn=5 includes misses from 2 deliberate trap media" in live_md
E   AssertionError: assert 'fn=5 includes misses from 2 deliberate trap media' in '# Face Bake-off Eval Report\n\n- schema: `acx-eval/v1` kind: `report` report_kind: `face_bakeoff`\n- model_ids: `synt... in FIR-5)\n  - synthetic↔real divergence uses Wilson half-width rule (replaces scope >1/3)\n\n## Failures\n\n- none\n'
```

### Restored green

`git checkout --` not needed: renderer body restored to the committed wording; `git status --porcelain` empty of that mutation.

```
2 passed
scene/tests/test_eval_harness_report.py::test_fixture_local_detection_caveat_filters_on_affects_only PASSED
scene/tests/test_eval_harness_face_determinism_anchor.py::test_fixture_local_detection_caveat_present_and_disappears_without_affects PASSED
```

## Gates

- `pytest scene/tests/test_eval_harness_face_determinism_anchor.py scene/tests/test_eval_harness_determinism_anchor.py -q -p no:randomly` → 49 passed (caption 21, face 28). Caption digests unchanged.
- `pytest scene/tests/test_eval_harness_report.py -q -p no:randomly` → 149 passed (#720).

## Commits

1. `2253cd7` A — renderer wording
2. `4893e79` B — media 9 note
3. `dc4c4cd` C — regen + digest re-pin
4. `653e46e` D — test pins
5. `b2f76f2` live-render hook so face TEST-15 can fail
6. this report
