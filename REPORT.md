# W3F-01 lane F — pin gpu-cloud-init SHA256SUMS to hub LFS digests

## Change
`infra/oci/gpu-cloud-init.yaml` SHA256SUMS write_files now pins two real sha256sum lines from hub revision `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639`, plus a provenance comment. Operator note updated: bake must match or runtime-check fails closed.

Local map:
- `qwen3-vl-30b-a3b-instruct-q4.gguf` ← hub `Qwen3-VL-30B-A3B-Instruct-Q4_K_M.gguf` `7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44`
- `qwen3-vl-30b-a3b-instruct-mmproj.gguf` ← hub `mmproj-F16.gguf` `9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819`

HF API re-verify (`curl -sS 'https://huggingface.co/api/models/unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF/tree/0af19e7479857aa7f3246466a4ad16c7e7299639?recursive=true'`, `.lfs.oid`) matched both constants. `test_gpu_cloud_init_bakes_qwen_measurement_candidate` does not assert placeholder text; left unchanged.

Guard: `test_gpu_cloud_init_pins_gguf_digests_from_hub_revision` in `scripts/test_vlm3_oci_gpu_infra.py`. Cross-checks `profiles.py` hub_repo + model_revision.

## RED (pre-pin)
Command: `python3 -m pytest scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision -q`

```
E       assert 0 == 2
E        +  where 0 = len([])
scripts/test_vlm3_oci_gpu_infra.py:107: AssertionError
FAILED scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision - assert 0 == 2
1 failed in 0.08s
```

## Mutant (TEST-15)
Flipped last hex digit of q4 digest (`…ab44` → `…ab45`). Same command:

```
Differing items:
{'qwen3-vl-30b-a3b-instruct-q4.gguf': '7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab45'} != {'qwen3-vl-30b-a3b-instruct-q4.gguf': '7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44'}
FAILED scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision - AssertionError: assert {'qwen3-vl-30...cb339bd20819'} == {'qwen3-vl-30...cb339bd20819'}
1 failed in 0.05s
```

Restored `…ab44`. Same command: `1 passed in 0.04s`.

## Full check
Briefed command `uv run --extra dev pytest scripts/test_vlm3_oci_gpu_infra.py -q` failed: `error: Extra 'dev' is not defined in the project's optional-dependencies table`.

Used: `python3 -m pytest scripts/test_vlm3_oci_gpu_infra.py -q`

```
......s.                                                                 [100%]
7 passed, 1 skipped in 0.05s
```

Skipped: `test_terraform_configuration_validates` (terraform init/providers unavailable).

## W3-F-01 micro-fix

Pair-wise `hub_repo`/`model_revision` check in `test_gpu_cloud_init_pins_gguf_digests_from_hub_revision`. Substring asserts missed a lone GPU_QWEN30B drift because GPU_QWEN30B_ENSEMBLE still held the pin.

Command: `python3 -m pytest scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision -q`

### Pre-fix lone mutant (bug)

GPU_QWEN30B `model_revision` → 40×`a`. Old substring asserts stayed GREEN:

```
.                                                                        [100%]
1 passed in 0.04s
```

Reverted.

### Post-fix lone mutant

Same GPU_QWEN30B 40×`a` mutant. Pair-wise check RED:

```
E       AssertionError: every unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF profile must pin revision 0af19e7479857aa7f3246466a4ad16c7e7299639, got ['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '0af19e7479857aa7f3246466a4ad16c7e7299639']
FAILED scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision - AssertionError: every unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF profile must pin revision 0af19e7479857aa7f3246466a4ad16c7e7299639, got ['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '0af19e7479857aa7f3246466a4ad16c7e7299639']
1 failed in 0.08s
```

Reverted. Same command: `1 passed in 0.04s`.

### Both-occurrence drift

Both GPU_QWEN30B and GPU_QWEN30B_ENSEMBLE `model_revision` → 40×`a`. RED:

```
E       AssertionError: every unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF profile must pin revision 0af19e7479857aa7f3246466a4ad16c7e7299639, got ['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa']
FAILED scripts/test_vlm3_oci_gpu_infra.py::test_gpu_cloud_init_pins_gguf_digests_from_hub_revision - AssertionError: every unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF profile must pin revision 0af19e7479857aa7f3246466a4ad16c7e7299639, got ['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa']
1 failed in 0.05s
```

Reverted.

### Full check

`python3 -m pytest scripts/test_vlm3_oci_gpu_infra.py -q`

```
......s.                                                                 [100%]
7 passed, 1 skipped in 0.05s
```
