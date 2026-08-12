# VLM-6 lane report — `vlm6-lc4-infra`

**Lane:** `vlm6-lc4-infra`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6-lc4` (sandbox: history-stripped base)  
**Actor:** grok-4.5  

## Verdict

**merge_ready** — all six inlined findings addressed in lane-owned files; report committed.

## Owned paths edited

| Path | Role |
| --- | --- |
| `infra/oci/cpu-batch-cloud-init.yaml` | RH-05 idle reaper; RH-08 GGUF pins |
| `Makefile` | R1-08 `eval-captions` default determinism |
| `docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md` | R1-02 gate truth; R1-06 37-count |
| `apps/prototype-description-service/scripts/eval_harness/README.md` | S2A-F5-02 operator surface; 37-count |
| `.s2a/vlm6-lc4-infra-report.md` | this report |

## Per-finding table

| Finding ID | Severity | What changed | How verified |
| --- | --- | --- | --- |
| **VLM6-R1-02** | high | Plan S0/S1 no longer claim `score --check-determinism` alone proves freeze integrity. S0 goal now names two gates: seed-stability (`--check-determinism` / default `make eval-captions`) vs freeze compare (`--check-determinism --expect-report` / `make eval-anchor-check`). S1 proof + verification strategy + contract Verification column + S0/S1 checklist updated accordingly. | Plan prose re-read: S0 goal states seed-stability "does **not** read a freeze"; S1 proof requires expect-report. Offline caption gate still green against committed freeze (see commands). |
| **VLM6-R1-06** | medium | Corpus count corrected to **37** throughout the plan (and README intro). Explicit media_id gap: ids 1–38 with **22 absent**. Procurement "62 new" → **63** (100−37). Historical subset renamed golden-38 → **golden-37** where it meant membership/count. Max `media_id` 38 kept as ID scheme, not count. | `python3` load of `golden.json` → 37 entries; missing `[22]`. Committed report `images: 37/37 scored`. Plan grep shows no bare "38-image" claim left without the gap explanation. |
| **VLM6-RH-05** | medium | Idle reaper: (1) provision writes `/opt/acx-cpu/.provisioned` only after success; (2) timer + service `ConditionPathExists=/opt/acx-cpu/.provisioned`; (3) script early-exits if sentinel missing; (4) awk activity pattern widened to `llama-server\|python3?\|cmake\|cc1plus\|make\|curl\|rsync\|sshd`. | YAML parses via `yaml.safe_load`. Grep confirms sentinel, ConditionPathExists on timer+service, widened regex. |
| **VLM6-S2A-F5-02** | low | README operator path: primary freeze surface is monorepo-root **`make eval-anchor-check`**; CLI example now includes `--expect-report` (no sibling inference). States seed-stability alone does not catch schema/manifest edits. | `make -n eval-anchor-check` shows both caption + face legs with `--check-determinism --expect-report`. Live caption leg exit 0 with `matches --expect-report`. |
| **VLM6-R1-08** | low | `make eval-captions` now defaults to `cli run --check-determinism $(EVAL_ARGS)`. Plan S0 checklist names that default and the separate freeze-compare command. | `make -n eval-captions` → `… cli run --check-determinism`. |
| **VLM6-RH-08** | low | Removed open TODO. HF tree API confirmed both GGUF filenames (HTTP 302). Pinned LFS SHA-256 oids in `acx-cpu.env`; provision runs `sha256sum -c` after each curl (wrong-but-200 fails closed). Documented Workload 2 as PARKED S3–S6 scaffolding, not S0–S2 gate. | HF API listed `Qwen3VL-4B-Instruct-Q4_K_M.gguf` + `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf` with LFS oids matching env pins. YAML parses. |

## Commands executed

```text
# corpus truth
python3 -c "… golden.json …"  # count 37; missing [22]

# HF filename + LFS oid verify
curl -sI …/Qwen3VL-4B-Instruct-Q4_K_M.gguf          # 302
curl -sI …/mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf      # 302
curl -sL https://huggingface.co/api/models/Qwen/Qwen3-VL-4B-Instruct-GGUF/tree/main

# documented make surfaces
make -n eval-captions
# → … cli run --check-determinism

make -n eval-anchor-check
# → score … --check-determinism --expect-report …S2A-determinism-anchor…
# → score-face … --check-determinism --expect-report …face-report…

# live offline freeze compare (caption leg of eval-anchor-check)
cd apps/prototype-description-service && uv run --extra dev python -m scripts.eval_harness.cli score \
  --manifest scene/tests/seed/golden.json \
  --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
  --check-determinism \
  --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json \
  --rubric-gate skip
# EXIT 0; scored=37/37; matches --expect-report

# face leg
… score-face … --check-determinism --expect-report …face-report.json
# (run in-session; see tests_run)

# lane gate (yaml)
uv run --project apps/prototype-description-service --extra dev python -c \
  "import yaml; yaml.safe_load(open('infra/oci/cpu-batch-cloud-init.yaml')); print('cloud-init YAML parses')"
# → cloud-init YAML parses

# make -n check-all
# pre-existing sandbox failure: No rule to make target 'check-agent-workflows' (history-stripped tree).
# Not introduced by this lane; Makefile recipe syntax for owned targets parses under make -n.
```

## Deliberately not fixed / out of scope

| Item | Why |
| --- | --- |
| Python under `scripts/eval_harness/` | Sibling lanes own those files; hard boundary. |
| Frozen anchors under `docs/tasks/vlm/bakeoff-results/` | Coordinator-owned; must not regenerate. |
| Enforcing `manifest_matches_fetch` as a hard exit in `report.py` / `cli.py` | Code path owned by sibling lanes; this lane fixed the **plan false-green claim** and operator/make surfaces that name the real freeze gate (`--expect-report`). |
| Runbook `docs/runbooks/oci-vm-reachability-tailscale-vcn-plan.md` step-8 wording | Not in owned_paths; cloud-init self-documents verified URLs + checksum fail-closed. |
| `make -n check-all` full success in this sandbox | Missing `check-agent-workflows` target is pre-existing on the stripped base, not a lane regression. |

## Security

No secrets, OCIDs, tenancy IDs, IPs, or SSH keys introduced. Model URLs are public Hugging Face resolve links; checksums are public LFS oids.
