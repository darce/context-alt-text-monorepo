# Recorded GPU after drafts

The four demo name-choice drafts now come from actual calls through the deployed
dev GPU adapter, using the bundled Tribeca photo, the festival page context, and
editor-reviewed names for each choice. Outputs are unchanged. These are recorded
results, not a fresh GPU request per visitor and not independent name recognition.

The full inputs, raw outputs, model endpoint response and adapter provenance are
in public-guide-gpu-drafts-2026-09-09.json. The incumbent endpoint reports the
Qwen3-VL-30B-A3B-Instruct Q4 GGUF with Q4_K_M metadata; adapter profile pins
unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF at
0af19e7479857aa7f3246466a4ad16c7e7299639, prompt version 3.
Generation occurred 2026-09-10 UTC / 2026-09-09 Toronto.

The prior handwritten samples are replaced for all four choices. The output is
longer and remains an editable draft; no manual wording corrections were folded
into what is labelled model output. AltText.ai remains the independently
recorded before baseline.

## Runtime investigation

The launcher rejected missing dev-fir and malformed prod/staging load reports.
User confirmed dev-fir was removed and authorized dev or prod. Removed only the
retired dev-fir line from the repo and active lifecycle deployment registry,
keeping dev, staging and prod. The live registry was backed up alongside it.

Prod initially lacked batch_in_progress and idle heartbeat. A scoped two-file
repair image was prepared and import-tested against the existing prod base,
with 19 describe-load tests passing. Before deployment, independent live
maintenance supplied a correct reporter and heartbeat in prod; our repair image
was never installed. The launcher then reported errors=[] and started normally.

The demo-configured prod async request failed because torch was unavailable in
its CPU stage (job 37c74cde-e24d-4533-9578-c568ea34824b). It produced no draft.
The dev bulk run 1071f039-af92-42b4-bd18-280ae3ce8fac triggered normal burst START
and completed with adapter=gpu, cached=false and the same model pin. Its output
was inspected through the tenant-scoped repository because dev HTTP status
rejected a missing tenant claim. Temporary sample API keys were revoked.

The published four variants were then generated through get_gpu_description_adapter
in the running dev container against the now-ready GPU. This isolates the model
and reviewed context; it is not claimed as four complete recognition-pipeline
runs. The normal idle reaper and maximum lease remain enabled.

The idle reaper stopped the GPU normally at 00:07:54 UTC with errors=[], and
the subsequent lifecycle state was stopped. Release 0.0.14 contains these drafts.
