# W2 · Inventory (grunt lane)

- **Wave:** W2 · **Model:** gpt-6-luna max, fast tier (`speed=fast` everywhere) · **Depends on:** plan v3
- **Owned paths:** `docs/tasks/firdv/firbench-1/inventory.md` (one file, tables only, ≤ 250 lines)
- **Read-only everywhere else.** No code edits, no model inference beyond the version probes listed, and no copying of private files.

## Goal

Pin every fact the implementation lanes would otherwise guess. Each row gives the value, the command that produced it, and the path or sha. A fact you cannot establish is written as "not found: <command tried>", never guessed.

## Sections to fill

1. **Leg pins (VM)**
   - SFace, AuraFace and buffalo_l model file paths, sizes and sha256
   - the `opencv-python` and `onnxruntime` versions inside `uv run --directory apps/prototype-description-service --locked python -c ...`
   - the outputs of `sface_embedding_model_manifest()` and `auraface_embedding_model_manifest()` (print the dataclass)
   - where AuraFace weights live on the VM
2. **Corpus on the VM**
   - the directory holding the 646-image corpus and the Golden-150 images
   - the count of files whose sha256 matches `corpus-manifest-v3r-20260814.json` (find the manifest path with `git ls-files | grep corpus-manifest`)
   - the missing ids
3. **Frame sources**
   - the field names (keys only, no values) of the Golden-150 manifest, corpus manifest v3r and the gate contract `benchmarks/manifests/fir-gate-contract-v1.json`
   - the fir-occ population draft lives only on the laptop under `benchmarks/private/`. Write "laptop-only: coordinator supplies a pseudonymized frame file" and stop there.
4. **PSU structure** from corpus manifest v3r:
   - the number of image–identity connected components
   - the size distribution (min, median, max)
   - size-weighted mean M̃, and deff at ICC 0.05, 0.10 and 0.20
   - check M̃ against report §0f (12.925 on v3; v3r may differ, so report both if both manifests exist). The tracked v3r manifest was measured at 231 image–identity components (largest 79), M̃ ≈ 18.19, deff ≈ 2.72 at ICC 0.10, n_eff ≈ 238; this inventory re-runs that count and records the result, and the 12.925 figure is not reproduced from the tracked file
5. **Non-mated frame count**:
   - faces with zero identity on exhaustively annotated images, and identities with ≥ 2 appearances
   - the implied FPIR resolvability (3/n)
   - the current 207-probe non-mated set's provenance file
6. **Reused API signatures**: `def` lines, with file:line, for every symbol named under "Read first" in the S0–S7 briefs. Flag any symbol that does not exist.
7. **Historical artifacts for AE-6 legacy parity**: the path and sha256 of the artifact that holds `face_unknown_rejection` 204/207, and of the Golden-150 FIR-8 bench output, if present on the VM.
8. **Dependencies**: whether `umap-learn`, `scipy` and `hdbscan` import in the service env (`python -c 'import umap'` and so on).
9. **Renderer**: whether `UX_MAPS_DIR=<tmpdir with a copy of febt-1-job-error-states.uxmap.json> python3 apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check` works from an external directory. Use a temp dir and delete it after.

## Rules

- Bounded reads only (`grep -n`, `sed -n`, `head`). Never `cat` large files.
- Print keys and counts, never identity values or names.
- Commit `inventory.md` on the lane branch.

## Done when

All nine sections are filled or marked "not found" with the command tried.
