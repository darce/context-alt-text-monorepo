# FIR-4 S5 adversarial code review (grok / fir-4-grok)

**Subject:** `b86938e0` (S5 license isolation) on `feature/fir-4`  
**Contract:** plan Contract Impact extras matrix + Docker stance + Checklist for S5 in `docs/tasks/fir/FIR-4-runtime-integration-task-plan.md`  
**Role:** adversarial CODE reviewer (independent; attack)  
**HEAD at review:** `b86938e02586ff08fc9aa647a18a41466e79d81e`

## VERDICT: pass_with_findings

S5 delivers the Contract Impact matrix: `[face]`→`[bench]` (insightface only), `[gpu]` = Linux `onnxruntime-gpu` only, Dockerfile `pip install ".[bench]"` (insightface **stays** for dark default), ORT 1.22+ numeric smoke, `fetch_face_pipeline_models.py --verify-only` (no network; fail-closed via `load_verified_model`), mac/install script default = face_pipeline fetch (`--bench` = insightface), docs/runbook/setup/README honesty, import-guard + string-sweep tests. Live `.[face]` / `[local]` install consumers are gone. Residual findings are **regression-guard and coverage gaps**, not a current prod dark-default boot break.

### Test evidence (this session)

```text
cd apps/prototype-description-service
uv sync --locked --extra dev   # EXIT 0 (venv lacked pytest until sync)
.venv/bin/python -m pytest \
  recognition/tests/unit/test_bench_extra_isolation.py \
  recognition/tests/unit/test_no_face_extra_strings.py \
  recognition/tests/unit/test_face_pipeline_provenance.py -q
→ 24 passed in 1.90s, exit 0
```

---

## Findings

### S5R-01 — medium

**File:line:** `apps/prototype-description-service/recognition/tests/unit/test_no_face_extra_strings.py:42-45,141-151` + `Dockerfile:40-41`  
**Heuristic:** SERVE-03, RLSE-08, TEST-06  
**Failure scenario:** Plan acceptance requires “Docker default target still boots the incumbent (**asserted**)”. Current guards assert pyproject has `bench = [` + `insightface` and not `face = [`, and forbid live `[face]` strings — but **nothing asserts the Dockerfile still installs `".[bench]"`** (or otherwise pulls insightface). A future “slim the image” edit to `pip install .` / drop the extra would leave the dark-default profile importable but insightface-absent → production `Unavailable*` at boot, while the S5 grep suite stays green.

**Fix:** Add a one-line Dockerfile text guard (e.g. require `".[bench]"` or `.[bench]` on the install RUN) next to `test_pyproject_defines_bench_not_face`, or extend packaging tests to require insightface via the bench extra on the image install path until FIR-6.

### S5R-02 — medium

**File:line:** `apps/prototype-description-service/recognition/tests/unit/test_no_face_extra_strings.py:42-45` (`_SCAN_ROOTS`)  
**Heuristic:** SERVE-03, RLSE-08, TEST-06  
**Failure scenario:** Plan text is **repo-wide** consumer update + grep-clean. The sweep only walks `apps/prototype-description-service` and `docs/runbooks`. A regression reintroducing `--extra face` / `.[face]` under `infra/`, `.github/`, root `scripts/deploy/`, or monorepo Makefiles would not fail CI. Manual attack this session found no live leftovers outside allowlisted plan/history docs — so **current tree is clean**; the guard is incomplete relative to the stated contract surface.

**Fix:** Expand `_SCAN_ROOTS` to at least `infra/`, `.github/`, `scripts/` (or monorepo root with tight allowlists), and drop dead allowlist prefixes that are never under scanned roots.

### S5R-03 — low

**File:line:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_provenance.py:504-582` vs `scripts/fetch_face_pipeline_models.py:281-302`  
**Heuristic:** PROV-08, TEST-06  
**Failure scenario:** `--verify-only` correctly delegates to `load_verified_model` (missing model, model hash mismatch, **license missing/hash mismatch** all raise → CLI exit 1). S5 unit coverage adds missing + model-hash + happy path + CLI exit-1-on-missing, but **no `verify_only` / `main(--verify-only)` case for license-mismatch**. Behavior is sound today via the shared loader; a future `verify_only` that only checks model bytes would still pass the new tests while lying about “model + license” docs.

**Fix:** One test: good model bytes + wrong `license_sha256` → `verify_only` raises / `main` returns 1; optional assert no `urlopen` call.

### S5R-04 — low

**File:line:** `apps/prototype-description-service/scripts/fetch_face_pipeline_models.py:14-16,323-326`  
**Heuristic:** PROV-08  
**Failure scenario:** Module docstring and `--verify-only` help advertise “missing or hash-mismatched models” only. License integrity failures also exit non-zero (via `load_verified_model`) but are not named in operator-facing copy. Dark-env preflight operators debugging a tampered LICENSE may think verify-only “only checks ONNX”.

**Fix:** Help/docstring: “missing, model hash mismatch, or license hash mismatch (no network)”.

### S5R-05 — low

**File:line:** `apps/prototype-description-service/recognition/tests/unit/test_bench_extra_isolation.py:19-35,63-98`  
**Heuristic:** TEST-06  
**Failure scenario:** Guard patches `builtins.__import__` only. Production insightface loads use `from insightface.app import …` (IMPORT_NAME → builtins) so the guard matches current code. `importlib.import_module("insightface")` can bypass the patch on CPython; the second test also exercises only the **empty-models Unavailable** face_pipeline branch (not a successful shared-runtime build). Not vacuous for “modules import + factory face_pipeline path without insightface”, but not a full sys.modules poison of a successful load path.

**Fix:** Prefer `sys.meta_path` finder that always raises for `insightface*`, and/or assert successful face_pipeline construction under the block when models are present (fixture models dir).

---

## Attack surface results (checklist)

### 1. Dark-default safety [SERVE-03][RLSE-08]

| Check | Result |
| --- | --- |
| Dockerfile installs insightface via `.[bench]` | **Yes** (`Dockerfile:40-41`; `pyproject` `bench = [insightface…]`) |
| Remaining live `.[face]` / `--extra face` install consumers | **None** in service, runbooks, infra, `.github` (only plan/archive/assessment history) |
| Prod would boot Unavailable from missed rename | **No** on current tree |
| Residual risk | **S5R-01** — no automated assert Dockerfile keeps `.[bench]` |

Not high on present HEAD.

### 2. Extras semantics: `[gpu]` drops insightface

| Check | Result |
| --- | --- |
| Matrix | `[gpu]` = `onnxruntime-gpu` Linux-only; insightface only under `[bench]` — matches plan |
| Deploy / runbook / compose using `--extra gpu` alone for incumbent | **No** — README labels gpu as ORT-GPU only; Dockerfile uses `.[bench]` not gpu; infra/oci has no face/gpu pip extra install for this service |
| Break if someone used gpu-only as “full face stack” | Would need insightface separately — **docs honest** |

No finding.

### 3. ORT image smoke [SERVE-07][PROV-08]

Exact expression (`Dockerfile:45`):

```python
parts=v.split('.'); assert len(parts)>=2 and (int(parts[0]), int(parts[1])) >= (1, 22), v
```

Numeric major/minor tuple — **not** string compare. Lexicographic trap (`'1.9' > '1.22'`) does **not** apply. Pre-release garbage in the minor token fails the `int()` hard (fail closed). No finding.

### 4. `--verify-only`

| Case | Behavior |
| --- | --- |
| Missing model | `ModelIntegrityError` → `ModelFetchError` → exit 1 |
| Tampered model hash | same |
| License missing / license hash mismatch | same (via `load_verified_model`) |
| Network | `verify_only` only calls `load_verified_model` — **no** `urlopen` / download |
| Leftover `.partial` only | final ONNX path missing → missing-model failure; `.partial` not accepted as verified |
| S5 tests | missing + model hash + happy CLI + CLI missing exit 1; **license path untested at verify_only layer (S5R-03)**; help text incomplete (**S5R-04**) |

### 5. `install_insightface_mac.sh` replacement

| Path | Behavior |
| --- | --- |
| Default | `cd PROJECT_ROOT`; `uv run python …/fetch_face_pipeline_models.py` (or `PYTHON_BIN` fallback) — invocation correct |
| `--bench` on Darwin arm64 | prior insightface SDK-aware install; message points at `uv sync --extra bench` |
| `--bench` non-Darwin | prints `uv sync … --extra bench`, exit 0 (no silent install) — `setup.sh` uses `uv sync --extra bench` on non-mac |
| `setup.sh` | default = model fetch via script; `--bench` installs insightface; `--no-face` skips fetch |

Default path is coherent with docs. No high finding.

### 6. Sweep test (`test_no_face_extra_strings.py`)

| Check | Result |
| --- | --- |
| Catches README / Dockerfile / setup.sh / pyproject `face = [` | **Yes** (under service root + pattern set) |
| Allowlist too broad for live surfaces? | Allowlist is plan/history docs; those paths mostly **outside** `_SCAN_ROOTS` (dead allowlist entries) |
| Wrong roots | **S5R-02** — misses infra/.github/deploy scripts |

### 7. Import-guard (`test_bench_extra_isolation.py`) [TEST-06]

- Removes insightface from `sys.modules`, blocks re-import via `builtins.__import__`.
- Re-imports `runtime_factory` + `face_pipeline_adapter` under the block; asserts callables and no insightface in `sys.modules`.
- Async factory test: `profile="face_pipeline"` + empty models → `Unavailable*` without insightface.
- **Not vacuous** for stated claim; limitations in **S5R-05**.

### 8. `test_face_pipeline_provenance.py` +81

- Additive S5 block only: `verify_only` missing / hash mismatch / happy + `main` exit 1 on missing.
- No edits that weaken prior fetch/provenance assertions (size, partial cleanup, license-on-load, etc.).
- No finding on weakening; coverage hole = **S5R-03**.

### 9. `uv.lock` delta

Diff is **extras re-cut only**: `face`→`bench`, drop insightface from `gpu`, `provides-extras` rename, single insightface marker `extra == 'bench'`. No unrelated package version drift. Pass.

### 10. Docs honesty

| Claim | Reality |
| --- | --- |
| insightface stays in image through FIR-4 | Dockerfile `.[bench]` + comments + deploy runbook |
| `[bench]` for bake-off / incumbent local | README, setup `--bench`, mac script `--bench` |
| Models fetched at provisioning, not image build | Dockerfile explicitly no model-fetch; runbook dark-env provision + `--verify-only` |
| `[local]` install strings | replaced with `[bench]` in adapter/factory errors |

Matches reality. No finding.

---

## Contract checklist (S5) mapping

| Checklist item | Status under attack |
| --- | --- |
| Extras rename; every `[face]` consumer updated | **Met** on live surfaces; history docs intentionally retain old names |
| Dockerfile `".[bench]"`; insightface remains | **Met** in code; **assertion weak (S5R-01)** |
| `--verify-only`; not in image build | **Met** |
| Mac script → face_pipeline fetch default | **Met** |
| Docs/runbooks sweep; uv sync matrix claimed in commit | Docs **met**; matrix not re-run this session beyond unit tests |

---

## No-finding attack list (explicit)

1. **Missed live `.[face]` consumer in prod path** — not found (service/runbooks/infra/.github clean of install-extra forms).
2. **`[gpu]`-only deploy break for incumbent** — no such deploy path; docs do not claim gpu implies insightface.
3. **ORT lexicographic version smoke** — resisted (int tuple compare).
4. **`--verify-only` silent success on missing/tampered model** — resisted.
5. **`--verify-only` network call** — resisted (code path).
6. **`.partial` accepted as verified model** — resisted.
7. **Import-guard vacuous (no reimport / no factory exercise)** — resisted for stated claim.
8. **Provenance suite weakened by +81** — not found.
9. **`uv.lock` unrelated version drift** — not found.
10. **Docs claim models baked / insightface already removed from image** — not found (wording matches FIR-4 keep-in-image stance).
