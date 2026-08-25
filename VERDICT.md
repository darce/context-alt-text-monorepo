# Lane F VERDICT — W3F-01 digest pin

HEAD `f65a1eeb5b2939324e2a407d9a3d13e31c06287e` on `feature/w3f-digest` (contains `037d0045` + `6f56d305`).
Guard: `scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision`.

**Overall: PARTIAL** — truth, baseline, mutants a/b/d, and runtime-check arming PASS. Mutant c SURVIVED (FAIL).

## truth — PASS

```
curl -fsSL "https://huggingface.co/api/models/unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF/tree/0af19e7479857aa7f3246466a4ad16c7e7299639?recursive=true"
```

HTTP/2 200. Hub `.lfs.oid` vs yaml SHA256SUMS (yaml.safe_load write_files content):

| hub path | lfs.oid | yaml filename | yaml digest |
|---|---|---|---|
| `Qwen3-VL-30B-A3B-Instruct-Q4_K_M.gguf` | `7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44` | `qwen3-vl-30b-a3b-instruct-q4.gguf` | same |
| `mmproj-F16.gguf` | `9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819` | `qwen3-vl-30b-a3b-instruct-mmproj.gguf` | same |

`apps/prototype-description-service/scene/config/profiles.py` GPU_QWEN30B and GPU_QWEN30B_ENSEMBLE both pin:

```
hub_repo="unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF"
model_revision="0af19e7479857aa7f3246466a4ad16c7e7299639"
```

(2 occurrences each.)

## baseline — PASS

```
python3 -m pytest scripts/test_vlm3_oci_gpu_infra.py -q
```

```
......s.                                                                 [100%]
7 passed, 1 skipped in 0.05s
```

`-rs`: `SKIPPED [1] scripts/test_vlm3_oci_gpu_infra.py:153: terraform binary not on PATH`

Guard-only: `1 passed in 0.04s`.

## mutant a (swap the two yaml digest values) — PASS (RED)

Applied: q4 line got mmproj oid, mmproj line got q4 oid. Then `git checkout -- infra/oci/gpu-cloud-init.yaml`.

```
FAILED scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision
E   AssertionError: assert {'qwen3-vl-30...5294b2b4ab44'} == {'qwen3-vl-30...cb339bd20819'}
      Differing items:
      {'qwen3-vl-30b-a3b-instruct-q4.gguf': '9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819'} != {'qwen3-vl-30b-a3b-instruct-q4.gguf': '7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44'}
      {'qwen3-vl-30b-a3b-instruct-mmproj.gguf': '7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44'} != {'qwen3-vl-30b-a3b-instruct-mmproj.gguf': '9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819'}
1 failed in 0.04s
```

## mutant b (delete yaml provenance comment citing hub pin) — PASS (RED)

Deleted `# pinned from unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639 ...`. Then `git checkout -- infra/oci/gpu-cloud-init.yaml`.

```
FAILED ... pins_gguf_digests_from_hub_revision
E   AssertionError: assert 'unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639' in '# Populate at bake time with `sha256sum qwen3-vl-30b-a3b-instruct-q4.gguf`.\n# Digests are pinned; bake must match or...uct-q4.gguf\n9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819  qwen3-vl-30b-a3b-instruct-mmproj.gguf\n'
scripts/test_vlm3_oci_gpu_infra.py:120
1 failed in 0.04s
```

## mutant c (GPU_QWEN30B `model_revision` → other 40-hex) — FAIL (SURVIVED)

Changed only `DescriptionProfile.GPU_QWEN30B` `model_revision` to `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`. Ensemble copy of the original SHA left in place. Then `git checkout -- apps/prototype-description-service/scene/config/profiles.py`.

```
.                                                                        [100%]
1 passed in 0.04s
```

Guard only asserts `model_revision="<pin>" in profiles` (substring, any occurrence). GPU_QWEN30B can drift while the test stays green.

Follow-up (not a listed dimension): replacing **both** profile revisions with `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` did go RED at line 132 (`assert f'model_revision="{model_revision}"' in profiles`). Reverted.

## mutant d (SHA256SUMS local filename `...-q4.gguf` → `...-q5.gguf`) — PASS (RED)

Then `git checkout -- infra/oci/gpu-cloud-init.yaml`.

```
FAILED ... pins_gguf_digests_from_hub_revision
  Left contains 1 more item:
  {'qwen3-vl-30b-a3b-instruct-q5.gguf': '7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44'}
  Right contains 1 more item:
  {'qwen3-vl-30b-a3b-instruct-q4.gguf': '7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44'}
1 failed in 0.04s
```

Post-revert suite again: `7 passed, 1 skipped in 0.05s`. Tree clean of mutant diffs.

## runtime-check arming — PASS

Extracted SHA256SUMS write_files content; same pattern as `acx-gpu-runtime-check.sh`:

```
grep -E '^[0-9a-f]{64} ' /tmp/SHA256SUMS.extracted
```

```
grep_rc 0
4:7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44  qwen3-vl-30b-a3b-instruct-q4.gguf
5:9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819  qwen3-vl-30b-a3b-instruct-mmproj.gguf
```

Two matches → `sha256sum -c` branch arms. Pattern present in yaml-embedded `/usr/local/bin/acx-gpu-runtime-check.sh`.
