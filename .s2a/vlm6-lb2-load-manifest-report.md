# Lane report: `vlm6-lb2` load_manifest classification — **reconstructed post-hoc by lane fx5**

> **Provenance warning:** This file was **not** authored by lane `lb2`.
> Lane `fx5` reconstructed it from merge `0920b1e1` / offload commit
> `51ca1558` ("Classified 6 load_manifest sites; metadata skips + TEST-15")
> and **re-verified each classification against the code at this lane's branch
> HEAD**. Do not treat the rows below as closed handoff findings.

**Lane (original):** `feature/vlm-6-lb2`  
**Task:** `VLM-6`  
**Owned paths in the merge (from commit):**
- `apps/prototype-description-service/scripts/eval_harness/bakeoff.py`
- `apps/prototype-description-service/scripts/eval_harness/fusion_runner.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff.py`
- `apps/prototype-description-service/scene/tests/test_fusion_runner.py`
- `apps/prototype-description-service/scene/tests/test_identity_merge_harness_gate.py`

Sibling lane `lb1` owns the `cli.py` call-site table
(`.s2a/vlm6-lb1-cli-hash-callsites-report.md`); this report covers the
**non-CLI** callers lb2 touched.

## Classification table (verified at HEAD)

Anchor by **function / fixture name + distinguishing kwargs**, not line numbers
(`rg-005` — line anchors rot).

| Site | Decision | Distinguishing call | Downstream that does/does not open bytes |
| --- | --- | --- | --- |
| `bakeoff.main` weave-bench branch | **skip** | `load_manifest(args.manifest, skip_hash_verification=True)` when `args.weave_bench is not None` | Text-only weave-bench replay; roster/media_id/face_boxes pins only — never opens image files |
| `bakeoff.main` live pixel branch | **images_dir** | `load_manifest(args.manifest, images_dir=images_dir)` with `GOLDEN_IMAGES_DIR` required | Live bakeoff fetch → image bytes over the wire |
| `fusion_runner.main` | **skip** | `load_manifest(args.manifest, skip_hash_verification=True)` | `run_fusion_eval` uses `_synthetic_image_bytes` from path/sha/media_id pins — never opens fixture files |
| `test_eval_harness_bakeoff.manifest` fixture | **skip** | `load_manifest(str(BAKEOFF_MANIFEST), skip_hash_verification=True)` | Transport tests use fake `image_bytes`; labels/rubrics/policy only |
| `test_entries_reuse_golden_corpus_images` | **skip** | `load_manifest(str(GOLDEN_MANIFEST), skip_hash_verification=True)` | Metadata pin compare (sha256/media_id/face_count/present_identities); no pixel open |
| `test_fusion_runner.manifest` fixture | **skip** | `load_manifest(str(BAKEOFF), skip_hash_verification=True)` | Labels/context_pack/policy/expected_attachments only |
| `test_identity_merge_harness_gate._load_scenes` | **skip** | `load_manifest(str(SEED_DIR / "golden.json"), skip_hash_verification=True)` | Synthetic faces for merge scoring; never opens image files |

## TEST-15 discrimination control (must stay red if pixel path skips)

`test_pixel_path_load_manifest_requires_hash_verification` in
`test_eval_harness_bakeoff.py`:

1. With `GOLDEN_IMAGES_DIR` unset and no `images_dir` / no skip →
   `ManifestError` matching `image hash verification is required by default`.
2. With a nonexistent `images_dir` →
   `ManifestError` matching `images directory not found`.

This proves the metadata-only skips did **not** neuter default-on hash
verification (VLM6-R2-05) for image-byte consumers.

## Explicit non-claims

- CLI call sites are **out of scope** for this reconstruction (see lb1 report).
- No claim that lb2 closed any handoff finding ID — no original `.s2a` report
  existed; this table is an audit surface for mis-skips on pixel paths.

## What the commit message claimed vs HEAD

Commit subject: "Classified 6 load_manifest sites". At HEAD the owned modules
expose the seven rows above (two bakeoff branches + fusion main + four test
helpers). The live bakeoff branch was already an `images_dir` path; lb2's
material change is the **explicit skip** on metadata-only sites plus the
TEST-15 control that keeps the pixel path honest.
