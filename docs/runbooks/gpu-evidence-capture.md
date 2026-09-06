# Runbook: capture GPU burst evidence

Use this runbook after a WordPress administrator has triggered one or more
descriptions through the demo or service UI. The exporter is read-only: it
fetches the OCI instance receipt and Audit events, then copies already-written
reaper and WordPress receipts into one bundle. It does not change instance
state, run Terraform, or connect to a live host.

## What the bundle proves

The checker requires the evidence to show this sequence in the selected UTC
window:

```text
STOPPED → RUNNING → STOPPED
```

It also requires exactly one `StartInstance` Audit event and at least one
`StopInstance` event from the expected reaper principal. If supplied, the
reaper snapshot must be written during the window and report `STOPPED`; WP
describe receipts must have non-empty descriptions whose timestamps fall in
the observed RUNNING interval. Audit events must identify the selected
instance and have a successful response status.

The exporter derives `state_history.json` only from successful Audit
transitions and an explicit Audit `stateChange.previous` state when present.
It does not invent a `STOPPED` observation at the window start or label the
point-in-time instance read as the window end. If the receipts do not contain
an independently observed `STOPPED → RUNNING → STOPPED` history, the checker
fails closed and the window must be recaptured with the required Audit state
change fields.
Any state-history observation marked `inferred`, `synthetic`, or `synthesized`
is ignored by the checker and cannot satisfy the lifecycle proof.

The distinction between lifecycle state and billing matters: a stopped
instance stops OCPU/GPU compute charges, while its boot volume still costs
money. See [OCI instance state & cost verification](oci-instance-state-and-cost.md)
for the state and cost semantics, current-state commands, and tenancy-wide
sweep guidance.

## Capture

1. Record the trigger time and choose an inclusive UTC window that begins
   before the WordPress action and ends after the reaper has stopped the
   instance. Use RFC 3339 values such as
   `2026-09-01T00:00:00Z`.
2. Collect the reaper `gpu-state.json` and WP describe receipt JSON through
   the approved read-only operator path, if those files are available locally.
   Keep the files unchanged; their bytes are hashed into the manifest.
3. Export the bundle. The OCI executable can be selected with `OCI_BIN` (or
   `GPU_EVIDENCE_OCI_BIN` through Make):

   ```sh
   make gpu-evidence-export \
     GPU_EVIDENCE_INSTANCE_ID=<instance-ocid> \
     GPU_EVIDENCE_COMPARTMENT_ID=<compartment-ocid> \
     GPU_EVIDENCE_SINCE=2026-09-01T00:00:00Z \
     GPU_EVIDENCE_UNTIL=2026-09-01T01:00:00Z \
     GPU_EVIDENCE_BUNDLE=docs/evidence/gpu-burst-20260901 \
     GPU_EVIDENCE_STATE_SNAPSHOT=/path/to/gpu-state.json \
     GPU_EVIDENCE_WP_RECEIPTS=/path/to/wp-describe-receipts.json
   ```

   The last two variables are optional. Without them the bundle still proves
   the OCI transition and Audit events, but the corresponding optional checks
   are recorded as not supplied.

   Snapshot URLs are used only for retrieval; their query tokens are replaced
   with `<redacted-url>` in the manifest command receipt.

4. Check the bundle. The normal reaper principal is `gpu-reaper`; confirm the
   deployment's configured principal before accepting a result. Set the
   minimum to the number of WP descriptions the trigger was expected to
   produce:

   ```sh
   make gpu-evidence-check \
     GPU_EVIDENCE_BUNDLE=docs/evidence/gpu-burst-20260901 \
     GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL=gpu-reaper \
     GPU_EVIDENCE_MIN_DESCRIPTIONS=1
   ```

   A non-zero result is a failed proof, not evidence that the burst was
   partially successful. Inspect the table's failed rows and capture a new
   window if Audit indexing lag left the event outside the first window.

## Attach to the handoff

The manifest intentionally excludes its own self-referential hash. Compute
the manifest digest after export and attach the bundle directory plus that
digest to the task handoff:

```sh
manifest_sha256="$(sha256sum docs/evidence/gpu-burst-20260901/manifest.json | awk '{print $1}')"
printf '%s\n' "$manifest_sha256"
```

On macOS without `sha256sum`, use:

```sh
manifest_sha256="$(shasum -a 256 docs/evidence/gpu-burst-20260901/manifest.json | awk '{print $1}')"
```

Record a `test_result` event with the bundle path and digest in its result
payload. The exact MCP wrapper depends on the active task session; the event
payload should contain at least:

```json
{
  "event_kind": "test_result",
  "result": "PASS: gpu-evidence-check",
  "bundle_path": "docs/evidence/gpu-burst-20260901",
  "manifest_sha256": "<64-hex-digest>",
  "test_command": "make gpu-evidence-check GPU_EVIDENCE_BUNDLE=..."
}
```

Keep the bundle directory and the recorded manifest digest together when
handing off so a reviewer can rerun the checker and verify every listed file.
