# VLM-3 GPU Detailed-Tier Decision Memo

Date: 2026-07-08
Task: VLM-3
Status: provisional implementation decision, pending live OCI bake-off

## Decision

Decision: Qwen3-VL-30B-A3B-Instruct

Use Qwen3-VL-30B-A3B-Instruct Q4 GGUF as the provisional GPU detailed-tier implementation target for the adapter and golden-image work. It is the only candidate in the current slate that combines the existing Qwen family fit from VLM-2B, 30B-class total capacity, MoE active-parameter serving cost, and an estimated 18 GB Q4 footprint inside the `VM.GPU.A10.1` 24 GB target.

Do not promote the provisional decision to final until the live OCI bake-off replaces the pending report stubs with measured `acx-eval/v1` REPORTs and updates the Slice 1 spike artifact with real warm-start and s/img values.

## Evidence

- Spike artifact: `VLM-3-gpu-spike-2026-07-08.json`
- Candidate slate: `VLM-3-gpu-bakeoff-candidates-2026-07-08.json`
- Selected candidate report placeholder: `VLM-3-bakeoff-Qwen3-VL-30B-A3B-Instruct-report.json`
- Current evidence status: pending live OCI bake-off

## Must-Right

- Fits the A10 24 GB target with enough context/KV headroom for alt-text generation.
- Preserves the VLM-2B family continuity so adapter behavior starts from the known Qwen detailed-tier winner.
- Supports the existing endpoint bake-off harness without forking `scripts.eval_harness.bakeoff`.
- Produces a final adapter result through the unchanged `DescriptionAdapter` protocol.

## Easy-Wrong

- Treating pending placeholder REPORTs as measured quality evidence.
- Choosing a dense model only because it is simpler to serve while losing the expected quality lift.
- Selecting a larger Qwen3-VL-32B or GLM-class model that leaves no A10 headroom.
- Ignoring license review when moving from private tenancy spike to public demo use.

## Latency, RSS, and Speedup

Measured GPU latency/RSS: pending live OCI bake-off.

CPU baseline: VLM-2B recorded Qwen3-VL-4B-Instruct at roughly 207 s/img on A1 CPU.

CPU to GPU speedup: provisional target is 207 s/img divided by measured GPU s/img; the denominator remains pending in `VLM-3-gpu-spike-2026-07-08.json`.

## License verdict

Provisional pass for private in-tenancy evaluation. Final license verdict is blocked on the exact downloaded artifact license for Qwen3-VL-30B-A3B-Instruct Q4 GGUF and must be rechecked before public demo distribution.
