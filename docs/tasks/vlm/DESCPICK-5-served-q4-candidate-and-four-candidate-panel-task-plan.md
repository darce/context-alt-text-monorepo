# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-28 20:49 EDT
> - **Author**: Claude Opus 5.5 (`claude-opus-5-5`)
> - **Project**: `benchmarks`
> - **Task ID**: `DESCPICK-5`
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/descpick-5`
> - **Review Coverage Target**: 2
> - **Scope Brief**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`
> - **Anchors verified at**: `43366e5d25` (2026-10-28); unchanged at main `8eece0358f`.

---

## DESCPICK-5. Served Q4 candidate and four-candidate panel

Paths are repo-relative.

## Objective

Add the build that actually serves, Qwen3-VL-30B-A3B-Instruct Q4_K_M (`incumbent-q4km`), to the description review panel as the fourth candidate. Generate it under decision 20420's shared A10 decision profile so the model choice is measured against the served baseline [EVAL-01, SERVE-07]. Deliverables: 58 cells; the operator report extended to four candidates with all 192 prior reviews kept; decision rule v2; and review-decision-v4.

## Intake

> Include this section when a P0 scope intake pass was conducted before assessment. Omit for bug fixes, tech debt tasks, and spec-derived tasks.

- **Scope one-pager**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`; eval cases GTM-SC-17 … GTM-SC-19.
- **Key Q&A decisions**: #20420 on `MAINT-desc-model-pick-20261026` (commit `c9674a2aa0484e383c51ee0a3ba28247b7dee12a`) adds the Q4 build as the fourth candidate and fixes the decision profile; #20466 scope intake.
- **Not-Doing**: candidates beyond four; re-running the three existing candidates; editing frozen review-tool files.

## Problem Statement

1. The panel compares three candidates (`benchmarks/tools/description-review/decision-rule.json`, candidates at :8) but not the build that serves. Without the served baseline, the choice cannot show that switching beats keeping [EVAL-01].
2. The served Q4 quantization has not been measured on the failure metric beside the full-precision candidates [SERVE-07, CARD-28].
3. The review tool's text and metrics assume three candidates and one data pin (`operator-review.js` candidates at :8 and :350; `operator-metrics.js` single DATA/SHA pin).

## Constraints

- **Decision profile** (20420). Every incumbent-q4km request uses:
  - runtime image id `sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb`;
  - ctx 8192, image token cap 1536, parallel 1, f16 KV cache;
  - temperature 0, seed 0, thinking off;
  - max tokens 1536 for extraction and 512 for writing;
  - lexicon off;
  - the 29 decision images named in decision 20420;
  - pipeline E0 → W0 (full120).
- **Model binding**: `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639`. The Q4_K_M GGUF sha256 starts `7ea0a652`; the mmproj-F16 sha256 starts `9f248089`. Both match `infra/oci/gpu-cloud-init.yaml` (:29-31).
- **Statistics, fixed before any review** [EXP-09, CARD-27]:
  - non-inferiority margin δ = 0.10;
  - bootstrap seed `0x51f15e`, 2000 resamples.
- All 192 reviews in `operator-reviews2.json` (sha256 starts `831a1da3`) are kept.
- **Frozen files** under `benchmarks/tools/description-review/`: `decision-rule.json`, `DESIGN.md`, `test/fixture.js`, `fixtures/**`.
- **Python**: stdlib only (`html.parser`, `json`, `hashlib`, `shlex`); no new dependency.
- **Output files**: written through `raw_generation.write_new` (O_EXCL | O_NOFOLLOW, mode 0o400). Never overwrite one; a re-run gets a new path.
- Review order is counterbalanced [EVAL-14]. Candidate labels come from the rule, never from a per-candidate constant.
- GPU runs (S2) belong to the GPU owner, inside a reserved window; no lane calls the GPU.
- `descpick-5-x1` waits for E15-39 `e15-39-i3`: its parity test reads the pinned serve argv.

## Workflow Principles

- The served build is the baseline; every candidate runs under the same profile.
- Extend, never rewrite: prior reviews and frozen files survive byte for byte.
- Seal inputs by hash; refuse a mismatch rather than guessing.

## Terminology

| Term | Meaning |
|---|---|
| incumbent-q4km | The served Q4_K_M build, model key in the panel. |
| Decision profile | The A10 serving and decoding settings fixed by decision 20420. |
| Operation | One raw-generation run, id `f"{model}/E{n}/{offset:03d}"` (`raw_generation.py`). |
| Cell | One model output for one image and stage, keyed `<input_sha256>:<model_key>:<arm>:<scope>:<output_sha256>`. |
| Review host | A report element that carries a review key (`div.operator-cell[data-review-key]`). |
| Decision cell | A cell that counts toward the decision rule. |

## Current State Analysis

| Site | Today |
|---|---|
| `benchmarks/description-full-precision/raw_generation.py` | `SCHEMA = 'description-full-precision-raw-generation/v1'`; `validate_binding` (:72); `write_new`; `execute(contract, *, operation_id, binding, keyfile, out, dry_run=False, transport=None)` writes `<out>.producer.json` |
| `benchmarks/tools/description-review/operator-review.js` | `TEXT` (:4); candidates (:8, :350); presentation orders (:23); validation (:37); export file name (~:118) |
| `benchmarks/tools/description-review/operator-metrics.js` | DATA `qwen-high-precision-12-all-history-20261025`, SHA `20bec411e94963641b1882edb680240991771bcc7b350856eb293398e3aa4d0e`; `decide` (:68); exported API (:180) |
| `benchmarks/tools/description-review/decision-rule.json` | v1; candidates (:8); `deploy_gate` (:36) |
| `benchmarks/tools/build_decision_report.py` | `main` (:205): `--source --gpu-performance --rule --assets --out [--copy-from]`; exits 2 on a rule/manifest mismatch |
| v2 operator report | sha256 starts `00674a51bed8`; 648 review hosts, 86 decision cells |
| `benchmarks/tests/test_drv_decision_view_js.py` | Node wrapper precedent: `shutil.which("node")`, then `subprocess.run([node, "--test", str(TEST)], capture_output=True, text=True, timeout=300)` |

## Target Outcome

- Two operations: `incumbent-q4km/E0/000` (20 images) and `incumbent-q4km/E0/020` (9 images), producing 58 cells.
- v3 report:
  - 706 review hosts (648 + 58);
  - 115 decision cells (86 + 29);
  - all 192 reviews still bound.
- `decision-rule.v2.json` with four candidates.
- `benchmarks/reports/qwen-high-precision-20261025/review-decision-v4/index.html` published.

## Context Loading

> List the minimum authoritative context an agent should load before implementation.
> Prefer small, role-specific surfaces over broad repo ingestion.

- **Rules**: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/testing-principles.md`.
- **Contracts**: `raw_generation.py` schema v1 (read only); `benchmarks/tools/description-review/DESIGN.md` (frozen, read only).
- **Handoff/MCP state**: the `DESCPICK-5` row; decision #20420; the S2 manifest-hash decision.
- **External docs via `ctx7` only if**: a Node `node:test` API detail is unclear.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| Decision extension manifest | Slice 1 | None | New schema `description-full-precision-decision-extension/v1` | No | `benchmarks/tests/test_decision_extension.py` |
| Operator report HTML | Slice 3 | v2: 648 hosts, 86 decision cells | v3: adds incumbent-q4km cells; prior markup unchanged | Yes: prior review keys must still bind | `benchmarks/tests/test_extend_operator_report.py` |
| Review tool candidates and pins | Slice 4a | Three candidates, one pin | N candidates from the rule; `PINS` list | Yes: v1 data still loads | `benchmarks/tests/test_drv_four_candidate_js.py` |
| Decision rule | Operator S4b | v1 (frozen) | New `decision-rule.v2.json` | v1 untouched | Builder refuses a rule/manifest mismatch |

Non-functional notes:

- **Latency**: not user-facing. The GPU window covers 87 requests (#20420) at USD 2.00 per GPU-hour.
- **Degraded behaviour**: a failed operation is re-run to a new output path (O_EXCL). A hash mismatch at any stage exits 2; nothing is patched in place.
- **Load and spikes**: none; offline batch.

## Proposed Solution

1. **Slice 1**: `decision_extension.py` prepares the two incumbent-q4km operations under the decision profile and seals them.
2. **Operator S2**: the GPU owner runs them.
3. **Slice 3**: `extend_operator_report.py` turns the v2 report into v3.
4. **Slice 4a**: the review tool takes N candidates from the rule and a list of data pins.
5. **Operator S4b, S5, S6**: rule v2, then the build, then the review.

## Files and Surfaces to Change

> Name the exact symbol(s) per file — the implementer should not have to grep for the edit site. Mark new symbols `(new)`. Prefer symbol names over line numbers.

| Surface | File | Symbol / Function | Change |
|---|---|---|---|
| Extension | `benchmarks/description-full-precision/decision_extension.py` (new) | `SCHEMA`, `prepare_extension`, `load_extension` (new) | Slice 1 |
| Extension test | `benchmarks/tests/test_decision_extension.py` (new) | tests listed in Slice 1 | RED |
| Report extender | `benchmarks/tools/extend_operator_report.py` (new) | `main`, `extend_report` (new) | Slice 3 |
| Extender test | `benchmarks/tests/test_extend_operator_report.py` (new) | tests listed in Slice 3 | RED |
| Review tool | `benchmarks/tools/description-review/operator-review.js` | `TEXT.candidate`, candidate list, orders | Slice 4a |
| Metrics | `benchmarks/tools/description-review/operator-metrics.js` | `PINS` (new), `decide` | Slice 4a |
| Review tool tests | `benchmarks/tools/description-review/test/four-candidate.test.js` (new), `benchmarks/tests/test_drv_four_candidate_js.py` (new) | four-candidate cases | RED |

## Related Files

| File | Note |
|---|---|
| `benchmarks/description-full-precision/raw_generation.py` | Reused: binding validation, `write_new`, `execute` |
| `benchmarks/tools/build_decision_report.py` | Run by the operator in S5; unchanged |
| `infra/oci/gpu-cloud-init.yaml` | Serve argv for the parity test (after E15-39 `e15-39-i3`) |
| `benchmarks/tests/test_drv_decision_view_js.py` | Node wrapper pattern |

## Verification Strategy

> Define the evidence bundle before implementation.
> Include deterministic tests first; add runtime-parity or manual verification when they are genuinely required.

- **Deterministic tests**: pytest for the extension and the extender; `node --test` through a pytest wrapper for the review tool.
- **Runtime-parity / environment checks**: argv parity between the extension profile and the GPU cloud-init serve block.
- **Contract/fixture verification**: seal hashes on every input; frozen files unchanged (`git diff --stat` excludes them).
- **Failure-mode / SLA prompts**: State p99 latency target (not average), degraded behavior when dependency X is down/slow, and spike/peak load assumptions — see planning-review-guide § Non-Functional & Failure-Mode Realism. Answered in Contract and Boundary Impact.
- **Manual verification**: operator S2, S4b, S5 and S6.

```bash
LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_decision_extension.py -q -p no:cacheprovider
```

```bash
LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_extend_operator_report.py -q -p no:cacheprovider
```

```bash
LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_drv_four_candidate_js.py benchmarks/tests/test_drv_decision_view_js.py -q -p no:cacheprovider
```

## Slice Delivery

> Each slice must name the **files and functions** it touches (`path:symbol`) and the **proof** that closes it — enough for a junior agent to implement the slice from this block alone.

### Slice 1: Decision extension

Lanes: `descpick-5-x1r` (RED) then `descpick-5-x1`, which also waits for E15-39 `e15-39-i3`.

**Goal**: the two incumbent-q4km operations are prepared under the decision profile and sealed.

Files/functions: `benchmarks/tests/test_decision_extension.py` (lane `descpick-5-x1r`); `benchmarks/description-full-precision/decision_extension.py:SCHEMA`, `:prepare_extension`, `:load_extension` (new, lane `descpick-5-x1`).

RED tests. The directory name contains a hyphen, so load both `decision_extension.py` and `raw_generation.py` by path with `importlib.util.spec_from_file_location`.

1. `prepare_extension` yields exactly two operations, `incumbent-q4km/E0/000` (20 images) and `incumbent-q4km/E0/020` (9 images), and 58 cells in total.
2. Every operation's binding passes `raw_generation.validate_binding` and carries each decision-profile value from Constraints.
3. Argv parity, using the same parse as E15-39 `e15-39-r3`:
   - read the `docker run` block in `infra/oci/gpu-cloud-init.yaml`;
   - join the continuation lines and `shlex.split` the result;
   - assert the profile's server flags and image digest reference equal the parsed ones.
4. Deterministic seal:
   - two calls with the same inputs give byte-identical manifests (sorted keys, no timestamps) and the same SHA-256;
   - `load_extension(path, expected_sha256)` returns the manifest for the right hash and raises `ValueError` for any other.

Implementation (`descpick-5-x1`):

- `SCHEMA = "description-full-precision-decision-extension/v1"`.
- `prepare_extension(images, *, cloud_init, out)` builds both operation contracts plus a manifest. It writes them with `raw_generation.write_new` and returns the manifest path.
- `load_extension(path, expected_sha256)` verifies the hash and then the schema.

Proof: RED fails because the module is missing; after `descpick-5-x1`, `benchmarks/tests/test_decision_extension.py` passes. TEST-15: change `--image-max-tokens` in the profile to 1024 → the parity test goes red; revert.

### Operator S2: GPU run

After `descpick-5-x1`. The GPU owner runs, in a reserved window:

1. `raw_generation.execute` with `dry_run=True` for each operation;
2. then each operation for real, 87 requests in total (#20420).

Outputs go to `benchmarks/reports/qwen-high-precision-20261025/q4-extension/<image_id>-E0-W<w>/response.json`. Record the manifest SHA-256 as a decision on `DESCPICK-5`.

### Slice 3: Report extension

Lanes: `descpick-5-x3r` (RED) then `descpick-5-x3`.

**Goal**: the v3 report adds the incumbent-q4km cells and keeps every prior review bound.

Files/functions: `benchmarks/tests/test_extend_operator_report.py` (lane `descpick-5-x3r`); `benchmarks/tools/extend_operator_report.py:extend_report`, `:main` (new, lane `descpick-5-x3`).

CLI: `python3 benchmarks/tools/extend_operator_report.py --source <v2.html> --source-sha256 <hex> --extension <manifest> --extension-sha256 <hex> --out <v3.html>`.

- Exit 2 on any hash mismatch or an existing `--out`.
- Use stdlib `html.parser`.
- DOM anchors: `article.image-card[data-image-id]` and `td[data-model-key] > div.operator-cell[data-review-key]`.
- Each new cell's `raw_href` is `q4-extension/<image_id>-E0-W<w>/response.json`.
- Presentation orders come from `operator-review.js` via `node -e`.

RED tests use a small synthetic v2 fixture built in `tmp_path`: two image cards with three candidates.

1. v3 adds exactly one incumbent-q4km cell per image and stage, keyed `<input_sha256>:<model_key>:<arm>:<scope>:<output_sha256>`.
2. Every prior `div.operator-cell[data-review-key]` survives byte for byte.
3. Orders are counterbalanced across four candidates.
4. A wrong `--source-sha256` exits 2.
5. When the real v2 report and S2 outputs exist (otherwise skipped), the counts are 706 review hosts and 115 decision cells.

Proof: RED fails; after `descpick-5-x3` passes.

### Slice 4a: Four candidates in the review tool

Lanes: `descpick-5-x4r` (RED) then `descpick-5-x4`.

**Goal**: the review tool handles N candidates from the rule and more than one data pin.

Files/functions:

- Lane `descpick-5-x4r`: `benchmarks/tools/description-review/test/four-candidate.test.js` and `benchmarks/tests/test_drv_four_candidate_js.py`. The wrapper copies the `test_drv_decision_view_js.py` pattern and skips when `node` is absent.
- Lane `descpick-5-x4`: `benchmarks/tools/description-review/operator-review.js:TEXT`, its candidate list and orders; `benchmarks/tools/description-review/operator-metrics.js:PINS` (new) and `:decide`.

RED tests. Build the four-candidate fixture inline and do not touch `test/fixture.js`.

1. The labels "Candidate 1" … "Candidate 4" come from the rule's candidate list.
2. The orders counterbalance four candidates.
3. The metrics load two pins and refuse a SHA mismatch.
4. `decide` handles four candidates with δ = 0.10.
5. The existing three-candidate data still loads.

Implementation:

- `TEXT.candidate = (n) => 'Candidate ' + n`.
- The candidate list is read from the rule.
- `PINS = [{ data, sha }, …]` replaces the single DATA/SHA pair, with the current pin as its first entry.
- No gettext: this is an operator-only English benchmark tool.

Proof: RED fails; after `descpick-5-x4`, both wrapper tests pass and the frozen files are unchanged.

### Operator S4b, S5 and S6

- **S4b**, before anyone opens v3 for review [EXP-09]: write `benchmarks/tools/description-review/decision-rule.v2.json`. It has four candidates, δ 0.10, bootstrap seed `0x51f15e` with 2000 resamples, and the v1 deploy gate, and it cites decision 20420.
- **S5**: run `python3 benchmarks/tools/build_decision_report.py` with:
  - `--source` set to the v3 report;
  - `--rule` set to `decision-rule.v2.json`;
  - `--gpu-performance` and `--assets` as for v2;
  - `--out` set to the directory `benchmarks/reports/qwen-high-precision-20261025/review-decision-v4`.

  `--out` is a directory: `build` creates it and writes `index.html` and `decision-build-receipt.json` inside it (`build_decision_report.py`, `args.out / name`). Do not append `index.html`, or the page lands at `review-decision-v4/index.html/index.html`. The directory must not exist beforehand, because `build` overwrites files in an existing one. The published artifact is `review-decision-v4/index.html`. It exits 2 on a rule/manifest mismatch.
- **S6**: review v4, export the reviews, and record the model decision.

## Not Doing

- Candidates beyond four, or re-running the existing three.
- Editing `decision-rule.json`, `DESIGN.md`, `test/fixture.js` or `fixtures/**`.
- Gettext in the review tool.
- Changing `raw_generation.py` or `build_decision_report.py`.

## Decomposition

Machine-checked by `plan_decomposer`; the cross-task wait on E15-39 `e15-39-i3` is in Merge Order.

```json
{
  "version": 1,
  "items": [
    {"id": "s1", "title": "X1R RED: decision extension", "independent": true, "owns": ["benchmarks/tests/test_decision_extension.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s2", "title": "X1: decision extension module", "independent": false, "owns": ["benchmarks/description-full-precision/decision_extension.py"], "depends": ["s1"], "blast": "none", "anchors": []},
    {"id": "s3", "title": "X3R RED: operator report extension", "independent": true, "owns": ["benchmarks/tests/test_extend_operator_report.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s4", "title": "X3: operator report extender", "independent": false, "owns": ["benchmarks/tools/extend_operator_report.py"], "depends": ["s3"], "blast": "none", "anchors": []},
    {"id": "s5", "title": "X4R RED: four-candidate review tool", "independent": true, "owns": ["benchmarks/tools/description-review/test/four-candidate.test.js", "benchmarks/tests/test_drv_four_candidate_js.py"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s6", "title": "X4: four-candidate review tool", "independent": false, "owns": ["benchmarks/tools/description-review/operator-review.js", "benchmarks/tools/description-review/operator-metrics.js"], "depends": ["s5"], "blast": "none", "anchors": []}
  ]
}
```

## Lane Decomposition (Multi-Agent)

> Include this section only when the task naturally splits into independent lanes.
> Omit for single-lane work that one agent can complete in a bounded session.
> Prefer the machine-checked `## Decomposition` JSON block above when lanes will
> be compiled through `plan_decomposer` → `work_graph_compiler`.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
|---|---|---|---|
| `descpick-5-x1r` | `benchmarks/tests/test_decision_extension.py` | None | pytest (red) |
| `descpick-5-x1` | `benchmarks/description-full-precision/decision_extension.py` | `descpick-5-x1r`; E15-39 `e15-39-i3` | pytest |
| `descpick-5-x3r` | `benchmarks/tests/test_extend_operator_report.py` | None | pytest (red) |
| `descpick-5-x3` | `benchmarks/tools/extend_operator_report.py` | `descpick-5-x3r` | pytest |
| `descpick-5-x4r` | `benchmarks/tools/description-review/test/four-candidate.test.js`, `benchmarks/tests/test_drv_four_candidate_js.py` | None | wrapper pytest (red) |
| `descpick-5-x4` | `benchmarks/tools/description-review/operator-review.js`, `benchmarks/tools/description-review/operator-metrics.js` | `descpick-5-x4r` | both wrapper tests |

### Merge Order

A lane dispatches once every lane it depends on has merged.

1. Wave 1: `descpick-5-x1r`, `descpick-5-x3r`, `descpick-5-x4r`.
2. Wave 2: `descpick-5-x3`, `descpick-5-x4`.
3. `descpick-5-x1` once `descpick-5-x1r` and E15-39 `e15-39-i3` have merged.
4. Operator: S2 after `descpick-5-x1`; S4b before any v3 review; S5 after S2, `descpick-5-x3`, `descpick-5-x4` and S4b; S6 after S5.

### Manifest

```bash
make lane-manifest-init TASK=DESCPICK-5 LANE_IDS='descpick-5-x1r descpick-5-x1 descpick-5-x3r descpick-5-x3 descpick-5-x4r descpick-5-x4' TASK_PLAN=docs/tasks/vlm/DESCPICK-5-served-q4-candidate-and-four-candidate-panel-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries. Implementation and RED lanes run on remote codex `gpt-6.1-sol`, high effort, FAST tier; one lane per dispatch; each brief embeds its slice block from this plan.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

**Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"DESCPICK-5"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

### Checklist for Slice 1: Decision extension

- [ ] RED lane adds `benchmarks/tests/test_decision_extension.py` covering operations, profile, argv parity and seal; it fails because the module is missing.
- [ ] `benchmarks/description-full-precision/decision_extension.py` prepares and seals both operations.
- [ ] `LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_decision_extension.py -q -p no:cacheprovider` passes.
- [ ] Operator S2 ran both operations and recorded the manifest hash.

### Checklist for Slice 3: Report extension

- [ ] RED lane adds `benchmarks/tests/test_extend_operator_report.py`.
- [ ] `benchmarks/tools/extend_operator_report.py` writes v3 with prior review hosts unchanged and refuses hash mismatches.
- [ ] `LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_extend_operator_report.py -q -p no:cacheprovider` passes.

### Checklist for Slice 4a: Four candidates in the review tool

- [ ] RED lane adds `benchmarks/tools/description-review/test/four-candidate.test.js` and `benchmarks/tests/test_drv_four_candidate_js.py`.
- [ ] `benchmarks/tools/description-review/operator-review.js` and `benchmarks/tools/description-review/operator-metrics.js` take candidates from the rule and a list of pins.
- [ ] `LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_drv_four_candidate_js.py benchmarks/tests/test_drv_decision_view_js.py -q -p no:cacheprovider` passes.

### Checklist for Operator S4b, S5 and S6

- [ ] `benchmarks/tools/description-review/decision-rule.v2.json` written before any v3 review.
- [ ] `benchmarks/reports/qwen-high-precision-20261025/review-decision-v4/index.html` built and reviewed; decision recorded.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- A per-image Q4 versus full-precision delta view in v4.

## Success Criteria

| Eval case | Proof |
|---|---|
| GTM-SC-17 | `benchmarks/tests/test_decision_extension.py` passes: 58 incumbent-q4km cells in 2 operations under the decision profile, argv parity, deterministic seal |
| GTM-SC-18 | `benchmarks/tests/test_extend_operator_report.py` and the four-candidate wrapper pass: 706 review hosts, 115 decision cells, 192 reviews kept, labels from the rule; the builder refuses a rule/manifest mismatch |
| GTM-SC-19 | review-decision-v4 published and the decision recorded |

## Canon authority (Canon v0.26.2)

| ID | Rule | Applied in |
|---|---|---|
| SERVE-07 | Gate the served quantization on the evaluated one | Served Q4 build as a candidate; argv parity |
| EVAL-01 | Offline baselines include the served system | incumbent-q4km in the panel |
| EVAL-14 | Counterbalance judge bias | Presentation orders over four candidates |
| EXP-09 | No peeking | Rule v2 and statistics fixed before review |
| CARD-27 | Margin and design effect before the run (`reasoning/margin-and-design-effect-before-the-run.md`) | δ = 0.10 and bootstrap fixed in advance |
| CARD-28 | Quantization delta on the failure metric (`reasoning/quantization-delta-on-the-failure-metric.md`) | Q4 measured beside full precision |
| CARD-30 | Signal density, not length (`reasoning/signal-density-not-length.md`) | Review scores content, not caption length |
