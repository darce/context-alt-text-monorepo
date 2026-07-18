# FIR-3 S1 adversarial review (grok / fir-3-grok)

**Target:** `b8e1890b1a5ed6830e408d7507343ab8dbf36b9b` — FIR-3 S1 face_pipeline model provenance + fetch  
**Role:** hostile / review-only (no implementation edits)  
**Heuristics cited:** rg-008, AGT-02, TEST-06, TEST-08, rg-013, rg-015  

## VERDICT: pass_with_findings

Loader fail-closed for missing / sentinel / size / sha256 is real and covered by unit tests. Manifest pins match on-disk YuNet/SFace ONNX + committed LICENSE files in this worktree. Remaining issues are verify-order in the fetch path, license not enforced at load (S2/S3 contract surface), and test honesty gaps on production pins.

---

### S1-GR-01 — medium

**File:** `apps/prototype-description-service/scripts/fetch_face_pipeline_models.py:62-65,111-119`  
**Rules:** rg-008, AGT-02  

**Evidence + failure scenario:** `download_file` writes the full response to `dest.suffix + ".partial"` then `tmp.replace(dest)` **before** any sha256/size check. Verification runs only afterward in `fetch_one` (`_verify_file` / `load_verified_model`). On a clean exception path, `fetch_one` unlinks the model/license — but a kill, hard crash, or power loss after `replace` and before verify leaves **unverified** ONNX bytes at the production path. README claims the script “refuses to leave unverified artifacts in place” (`models/README.md:51-53`); that is false under crash. Concurrent processes (or an operator `cp`/open) can observe the final path in the partial-download window. **Fix shape:** hash in memory (or hash the `.partial`), only `replace` after match; treat final path as publish-after-verify.

---

### S1-GR-02 — medium

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/provenance.py:95-134`  
**Rules:** rg-008, rg-015  

**Evidence + failure scenario:** `ModelProvenance` carries `license_file` + `license_sha256`, but `load_verified_model` never opens or hashes the license. Only the ONNX path is checked. S2/S3 adapters are instructed to load exclusively through this function; a missing, empty, or swapped `LICENSE.yunet` / `LICENSE.sface` still yields a verified model path. Task plan S1 requires “sha256 + license hashes” as the integrity surface; runtime contract currently drops the license half. **Failure:** distribution ships correct ONNX hashes with wrong/missing license audit trail; commercial-use review thinks licenses were fail-closed at load. **Fix shape:** optionally verify license next to model (or document explicitly that license is fetch-time only and out of loader contract).

---

### S1-GR-03 — medium

**File:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_provenance.py:131-147` (gap); production pins in `provenance.py:48-75`  
**Rules:** TEST-06, AGT-02  

**Evidence + failure scenario:** All integrity tests monkeypatch synthetic `MODEL_MANIFEST` entries. `test_module_manifest_covers_yunet_and_sface` only checks field presence and “64 hex or PENDING” shape — it never asserts that committed `models/LICENSE.yunet` / `LICENSE.sface` match `license_sha256`, nor that pinned model `sha256`/`size_bytes` match any fixture or re-fetched bytes from `source_url`@`source_ref`. A hand-edited wrong pin, or a license file replaced without updating the manifest, still green-lights CI. (This worktree’s on-disk models/licenses happen to match — that is operator state, not a test.) **Fix shape:** unit test that hashes the committed LICENSE.* paths against the production manifest; optional offline fixture or recorded digest check for model pins.

---

### S1-GR-04 — low

**File:** `apps/prototype-description-service/recognition/tests/unit/test_face_pipeline_provenance.py:150-168`  
**Rules:** TEST-06, rg-013  

**Evidence + failure scenario:** Import purity only iterates `vars(mod)` for values that are already `ModuleType`. It does not catch (a) function-level `import cv2` / `import onnxruntime` inside loaders added later, (b) `from cv2 import ...` (binds callables, not a module entry), or (c) `importlib.import_module`. Current S1 sources are stdlib-only — the package is clean — but the guard can pass against a broken future import. **Fix shape:** AST scan of package sources or import-linter contract (task plan already names import-linter as the intended bar).

---

### S1-GR-05 — low

**File:** `apps/prototype-description-service/scripts/fetch_face_pipeline_models.py:62-67`  
**Rules:** rg-008  

**Evidence + failure scenario:** On `OSError` during `tmp.write_bytes` / `tmp.replace`, the handler raises `ModelFetchError` but never unlinks the `.partial`. A half-written `face_recognition_sface_2021dec.onnx.partial` (or `.onnx.partial`) remains under `models/` (gitignored). Not loaded by `load_verified_model` (looks for exact `file_name`), but pollutes disk and can confuse operators. **Fix shape:** `try/finally` unlink partial on any failure before promotion.

---

### S1-GR-06 — low

**File:** `apps/prototype-description-service/recognition/infrastructure/face_pipeline/provenance.py:112-134`  
**Rules:** rg-008 (fail-closed claim)  

**Evidence + failure scenario:** After size+sha256 succeed, the function returns a `Path`. Docstring: “Never returns an unverified path.” Between return and the adapter’s first `open`/`cv2` read, a local attacker (or buggy parallel fetch) can replace the file. Content integrity is only guaranteed for the instant of hashing, not for subsequent opens of the returned path. Acceptable for a trusted operator models dir, but the absolute claim is overstated. **Fix shape:** document TOCTOU; or return bytes/fd opened before hash close; or re-hash at adapter open.

---

## Attempted attacks that did **not** land (defeated or non-issues)

| Attack | Result |
| --- | --- |
| `load_verified_model` skip-hash via missing file | Raises `ModelIntegrityError` (`is_file` gate) |
| Directory at model path | `is_file()` false → missing error |
| Empty / truncated file with production size_bytes | Size mismatch then/or sha256 mismatch |
| `PENDING_OPERATOR_FETCH` sentinel with file present | Raises; no path returned |
| Unknown logical name | `ModelIntegrityError`, not bare `KeyError` |
| Tampered same-length bytes | sha256 mismatch (tested) |
| Symlink at model path | Content of target is hashed; integrity of bytes holds if target matches pin |
| Case-insensitive FS name collision | Hash still gates content; no bypass observed |
| Production hashes fabricated vs local models | Worktree ONNX + LICENSE sha256/size match `MODEL_MANIFEST` (operator-fetched) |
| Import of cv2/onnxruntime/worker/HTTP in face_pipeline S1 | Package root + provenance are stdlib-only |
| Fetch HTTP error silent success | `ModelFetchError` paths; wrong-bytes fetch test raises |
| Nondeterminism (TEST-08) | Synthetic bytes + fixed digests; no time/network in unit path |
| License text wrong family for named models | LICENSE.yunet is MIT (Shiqi Yu); LICENSE.sface is Apache-2.0 text; matches README roles |

## Contract notes for S2/S3 (rg-015)

Safe to build on: `MODEL_MANIFEST` keys `yunet`/`sface`, `load_verified_model(name, models_dir=...) -> Path`, `ModelIntegrityError`, frozen `ModelProvenance` fields, `OPENCV_ZOO_COMMIT` pin, `DEFAULT_MODELS_DIR`.  
Do not assume: license files present/valid at load; fetch left only verified ONNX after crash; import-purity test blocks future cv2 imports inside adapter modules (adapters will intentionally import cv2/ORT — purity bar is package layering, not this weak vars() scan alone).

## Tests run this session

```text
cd apps/prototype-description-service && uv run pytest recognition/tests/unit/test_face_pipeline_provenance.py -q
# 9 passed in 0.03s
```
