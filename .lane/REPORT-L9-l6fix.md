# L9-l6fix report — repair three confirmed defects in 0d50d98f

## 1. IMPORT PROVENANCE check output

Command, from `/home/ubuntu/w/int9/apps/prototype-description-service`, before the first pytest:

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -c "import scripts.eval_harness.strata as m; print(m.__file__)"
```

Verbatim output:

```text
/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/strata.py
```

Path starts with `/home/ubuntu/w/int9`. No evidence from the shared venv `.pth` pin of `/home/ubuntu/vlm6-base/...`.

## 2. RED / GREEN / REVERT-RED (B.1, B.3, B.4)

### Defect 1 (FIR-ORCH-BR-28) — frozen S2A report banner

HEAD bytes before revert: `5628c4de91358fb489e5bc5ce2abbd29e17e549e2c0eb967c260096337e91873`
Parent / pin: `5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c`

**B.1 RED** (banner still in the frozen artifact):

```text
_ test_committed_anchor_digests_match_frozen[S2A-determinism-anchor-run-20260811-report.md-5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c] _

name = 'S2A-determinism-anchor-run-20260811-report.md'
expected = '5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c'

    @pytest.mark.parametrize("name,expected", list(_FROZEN_DIGESTS.items()))
    def test_committed_anchor_digests_match_frozen(name: str, expected: str) -> None:
        """Pin machine-diffable digests so a silent rewrite of the freeze goes red (TEST-15 base)."""
        path = _ANCHOR_DIR / name
        assert path.is_file(), f"missing committed anchor artifact: {path}"
>       assert _sha256(path) == expected
E       AssertionError: assert '5628c4de9135...0096337e91873' == '5131d552f1bc...24aeff1ab339c'
E
E         - 5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c
E         + 5628c4de91358fb489e5bc5ce2abbd29e17e549e2c0eb967c260096337e91873

scene/tests/test_eval_harness_determinism_anchor.py:243: AssertionError
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_determinism_anchor.py::test_committed_anchor_digests_match_frozen[S2A-determinism-anchor-run-20260811-report.md-5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c]
```

(The same parametrize also failed the other three freeze files. Those three already mismatch on parent `27025796`; see HONEST STATUS. `_FROZEN_DIGESTS` was not edited.)

**B.3 GREEN** after `git checkout 27025796 -- …/S2A-determinism-anchor-run-20260811-report.md` (MD sha restored to pin; figures untouched):

```text
.                                                                        [100%]
1 passed in 1.01s
```

**B.4 REVERT-RED** — banner re-inserted under the H1, same param:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_ test_committed_anchor_digests_match_frozen[S2A-determinism-anchor-run-20260811-report.md-5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c] _
...
E       AssertionError: assert '5628c4de9135...0096337e91873' == '5131d552f1bc...24aeff1ab339c'
E
E         - 5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c
E         + 5628c4de91358fb489e5bc5ce2abbd29e17e549e2c0eb967c260096337e91873
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_determinism_anchor.py::test_committed_anchor_digests_match_frozen[S2A-determinism-anchor-run-20260811-report.md-5131d552f1bc38e6ae3441d8346a35ca560a2412d802008f2e924aeff1ab339c]
1 failed in 1.09s
```

Banner restored off the freeze. Sidecar: `docs/tasks/vlm/bakeoff-results/SUPERSEDED.md`.

**Other 19 bannered files vs `_FROZEN_DIGESTS`:** none are pinned.

Caption pins (filenames only): `S2A-determinism-anchor-manifest-20260811.json`, `S2A-determinism-anchor-run-20260811.json`, `S2A-determinism-anchor-run-20260811-report.json`, `S2A-determinism-anchor-run-20260811-report.md`. Only the last was bannered.

Face pins: `S2A-face-determinism-anchor-manifest-20260811.json`, `S2A-face-determinism-anchor-run-20260811.json`, `S2A-face-determinism-anchor-run-20260811-face-report.json`, `S2A-face-determinism-anchor-run-20260811-face-report.md`. None bannered.

The other 19 bannered reports (S0 in this directory + 18 under `docs/tasks/{altq,20.0,vlm}/`) are not in either pin map. S0 keeps its in-file banner (not frozen) and is listed in the sidecar. The 18 outside `bakeoff-results/**` are out of allowlist; reported, not edited; listed in the sidecar.

### Defect 2 (FIR-ORCH-BR-29) — markdown refuse assertion cannot fail

The weak `assert "REFUSED" in md` lives in `test_zero_rule_baseline.py::test_delta_markdown_refuses_straddle_in_place_of_the_number`, not in `test_anti_straddle_delta.py` (brief mis-filed it). Characterization of the old assert: deleting the Δ-refuse banner (`- REFUSED ({invariant})` → `- skipped ({invariant})` in `report.py:_baseline_delta_lines`) left the old test green:

```text
.                                                                        [100%]
1 passed, 1 warning in 1.05s
```

Fix: assert `- REFUSED (delta_refuses_straddled_stamps):` (unique to the Δ banner). Same assert added on `build_reports` in `test_anti_straddle_delta.py`. JSON refuse/stamp/attach asserts left alone. Production `report.py` restored after every mutation.

**B.1 RED** (unique assert, banner deleted):

```text
FF                                                                       [100%]
=================================== FAILURES ===================================
_________ test_delta_markdown_refuses_straddle_in_place_of_the_number __________
...
>       assert "- REFUSED (delta_refuses_straddled_stamps):" in md
E       assert '- REFUSED (delta_refuses_straddled_stamps):' in "# Caption + Face Eval Report\n\n- schema: `acx-eval/v1` kind: `report`\n- adapter(s): `zero_rule` model(s): `zero-rul...cross straddled stamps: roster_epoch candidate='pre-priv1' baseline='post-priv1'\n\n\n## Per-item failures\n\n- none\n"

scripts/eval_harness/tests/test_zero_rule_baseline.py:265: AssertionError
__________ test_delta_markdown_refuse_banner_names_straddle_invariant __________
...
>       assert "- REFUSED (delta_refuses_straddled_stamps):" in md
E       assert '- REFUSED (delta_refuses_straddled_stamps):' in "# Caption + Face Eval Report\n\n- schema: `acx-eval/v1` kind: `report`\n- adapter(s): `seeded` model(s): `seeded-fixt...cross straddled stamps: roster_epoch candidate='pre-priv1' baseline='post-priv1'\n\n\n## Per-item failures\n\n- none\n"

scripts/eval_harness/tests/test_anti_straddle_delta.py:223: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_delta_markdown_refuses_straddle_in_place_of_the_number
FAILED scripts/eval_harness/tests/test_anti_straddle_delta.py::test_delta_markdown_refuse_banner_names_straddle_invariant
2 failed, 1 warning in 1.16s
```

**B.3 GREEN** (banner restored):

```text
..............                                                           [100%]
14 passed, 7 warnings in 1.29s
```

**B.4 REVERT-RED** (banner deleted again after green):

```text
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_delta_markdown_refuses_straddle_in_place_of_the_number
FAILED scripts/eval_harness/tests/test_anti_straddle_delta.py::test_delta_markdown_refuse_banner_names_straddle_invariant
2 failed, 1 warning in 1.14s
```

Production `report.py` restored. No leftover diff.

### Defect 3 (FIR-ORCH-BR-30) — caption test asserts the code's own output

Old loop: `expected = zero_rule_caption(entry.get("context_pack") or {})`. Inverting the echo rule (`for key in reversed(CONTEXT_FIELD_ORDER)`) left that test green:

```text
.                                                                        [100%]
1 passed, 1 warning in 0.96s
```

Fix: hand-derived literal captions from fixture `context_pack` title+caption+description for all 20 golden ids. Modeled on the sibling literal-string test.

**B.1 RED** (literals vs inverted echo):

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____________ test_zero_rule_run_record_matches_held_out_split_shape ____________
...
>           assert item["describe"]["alt_text_draft"] == expected_captions[media_id]
E           AssertionError: assert 'Slate Willow...kull ice cave' == 'Slate Willow... at her side.'
E
E             - Slate Willow inside the Breiðamerkurjökull ice cave Slate Willow crouching beneath blue glacial ice in Iceland. Slate Willow, in a white climbing helmet with a headlamp and a fur-hooded black parka, crouches on wet rocks inside the blue ice cave at Breiðamerkurjökull with a camera at her side.
E             + Slate Willow, in a white climbing helmet with a headlamp and a fur-hooded black parka, crouches on wet rocks inside the blue ice cave at Breiðamerkurjökull with a camera at her side. Slate Willow crouching beneath blue glacial ice in Iceland. Slate Willow inside the Breiðamerkurjökull ice cave

scripts/eval_harness/tests/test_zero_rule_baseline.py:186: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_zero_rule_run_record_matches_held_out_split_shape
1 failed, 1 warning in 1.01s
```

**B.3 GREEN** (echo order restored): included in the 14-passed run above.

**B.4 REVERT-RED** (echo inverted again after green):

```text
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_zero_rule_run_record_matches_held_out_split_shape
1 failed, 1 warning in 1.04s
```

Same assertion message (description-first vs title-first). Production `zero_rule_baseline.py` restored. No leftover diff.

### Final suite lines

Repaired files + report/pipeline (L6 surface):

```text
92 passed, 7 warnings in 1.61s
```

Full `scripts/eval_harness/tests` (paths literal):

```text
5 failed, 317 passed, 77 warnings in 30.72s
```

The 5 failures are all `test_regen_eval_report_gate.py` real-CLI tests. Out of allowlist; not introduced here.

`scene/tests/test_eval_harness_determinism_anchor.py` (full file):

```text
13 failed, 12 passed, 30 warnings in 20.58s
```

The L6-introduced MD digest case is green. The other failures are pre-existing freeze drift (see below). `_FROZEN_DIGESTS` was not rewritten.

## 3. Canon (verbatim table text) + satisfaction

**TEST-15** (`~/lane-canon/ENGCANON.md`):

> **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01))

Satisfaction: each repaired assert was watched going red on the mutation it claims to catch (banner rewrite / banner delete / echo invert), then green after restore. Defect 3 specifically removes an assertion on the code's own output (`zero_rule_caption(...)` as expected).

**TEST-11** (`~/lane-canon/ENGCANON.md`):

> **Measure stability, not coverage**: coverage is gameable; change-failure rate measures what you want (↔ biz [[BOOT-08]](business-marketing.md#boot-08) optimize payers per thousand, not reach; ↔ biz [[GTM-06]](business-marketing.md#gtm-06) spend where the number is actually typed and counted; ↔ sec [[SEC-12]](security.md#sec-12) clean accuracy is the paid number; a backdoor was never in it; ↔ biz [[STRAT-12]](business-marketing.md#strat-12) market price as quality proof is Mr. Market's mood, not the asset; ↔ biz [[OPS-01]](business-marketing.md#ops-01) the metric pays for the behavior it rewards at 2am; ↔ ux [[UXR-01]](interaction-ux.md#uxr-01) a downstream success is not evidence for the upstream claim it did not test)

Satisfaction: did not add coverage for its own sake. Replaced two gameable greens (substring `REFUSED`; expected==UUT) with asserts that fail when the guarded behavior is deleted. Did not skip or weaken an assert (sr-001).

**EVAL-23** (`~/lane-canon/EVALCANON.md`):

> **Readiness is the weakest category, not the total**: score data, model, infrastructure, and monitoring coverage as four separate subtotals and report the minimum as the readiness number, because the four are not substitutable and a total lets strong monitoring hide zero data tests until the untested contract fails in production (worst-unit gating on cohorts is [[FAIR-01]](ml-systems.md#fair-01); per-slice floors are [[EVAL-04]](ml-systems.md#eval-04))

Satisfaction: do not hide the weakest cell. 14/14 and 92/92 on the repaired surface do not substitute for a red freeze-regeneration cell on this branch. That cell is named below, not averaged away.

**PROV-01 / PROV-02:** genuinely absent from `~/lane-canon/EVALCANON.md` tables (`grep -nE '^\|\s*PROV-0[12]'` returns nothing). `ENGCANON.md` cross-refs `[[PROV-01]]` from OBS-06 but does not define PROV-01 or PROV-02. Same finding as the previous lane. Not invented.

## 4. Files changed

Staged work before this report was added:

```text
 .../eval_harness/tests/test_anti_straddle_delta.py |  15 +++
 .../eval_harness/tests/test_zero_rule_baseline.py  | 140 ++++++++++++++++++++-
 .../S2A-determinism-anchor-run-20260811-report.md  |   2 -
 docs/tasks/vlm/bakeoff-results/SUPERSEDED.md       |  43 +++++++
 4 files changed, 195 insertions(+), 5 deletions(-)
```

After this report is committed, `git diff --stat HEAD~1` also includes `.lane/REPORT.md`. `_FROZEN_DIGESTS` untouched. `zero_rule_baseline.py` / `report.py` / `bakeoff.py` untouched. Figures inside bake-off markdown untouched (banner only, then reverted).

## 5. HONEST STATUS

**PARTIAL**

The three named defects are fixed: frozen S2A bytes restored + sidecar; Δ-refuse markdown assert is unique and was seen red; zero-rule run-record captions are hand literals and were seen red.

What remains (out of allowlist / forbidden to "fix" by re-pinning):

1. `test_eval_harness_determinism_anchor.py` is **not** fully green (`13 failed, 12 passed`). Parent `27025796` already had manifest/run/report.json bytes ≠ `_FROZEN_DIGESTS`. Only the MD pin was broken by 0d50d98f; that pin is green again. Making the other three (and the generator/gate tests that consume them) green requires regenerating freeze artifacts or rewriting `_FROZEN_DIGESTS`. Both are invariants. Not done.
2. 18 bannered reports outside `docs/tasks/vlm/bakeoff-results/**` still carry in-file banners. None are pinned. Allowlist forbids editing them. They are listed in `SUPERSEDED.md`.
3. Full `scripts/eval_harness/tests`: `5 failed, 317 passed` — all five in `test_regen_eval_report_gate.py`. Pre-existing relative to this lane; not touched.
