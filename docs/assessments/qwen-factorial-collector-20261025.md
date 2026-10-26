# Missing-only Qwen factorial collector — 2026-10-25

The standalone collector is `benchmarks/tools/qwen_factorial_collect.py`. It
executes sealed extraction requests and clones a caller-qualified writer payload,
replacing only `model` and genuine `_weave_messages` output. It never starts a
model, creates a tunnel, renews a native lease itself, resets a deadline, retries
a stage, repairs generated JSON, scores facts, or selects a winner. Outputs remain
human-unreviewed. Real collection has not been run by this lane.

## Invocation and config

From the lane root, an operator can invoke:

```sh
.venv/bin/python benchmarks/tools/qwen_factorial_collect.py \
  --config /operator/collector-config.json \
  --evidence /operator/new-or-resumable-evidence \
  --deadline-unix 1793000000
```

This is an example only; the operator must supply actual absolute deadlines and
bindings. No credentials appear in the configuration, command output or command
arguments: `header_file` is an absolute FILE locator passed to curl as `--header
@FILE`. The collector does not read that file. The operator owns native cleanup,
epoch verification, endpoint/tunnel setup and model/profile attestation.

Configuration structure (all SHA256s are lowercase hexadecimal file digests):

```json
{
  "resources": {"path": "/operator/resources.json", "sha256": "<digest>"},
  "header_file": "/operator/request-headers",
  "writer_template": {"path": "/operator/qualified-writer.json", "sha256": "<digest>"},
  "timeout_s": 300,
  "cleanup_margin_s": 5,
  "max_parallel_models": 2,
  "models": [{
    "id": "qwen38-bf16",
    "precision": "bf16",
    "endpoint": "http://127.0.0.1:18001",
    "request_model": "<request model alias>",
    "expected_response_model": "<actual response.model identity>",
    "profile": {"path": "/operator/profile.json", "sha256": "<digest>"},
    "native_epoch": "<caller attested native epoch>",
    "deadline_unix": 1793000000,
    "extractions": [{
      "image_id": "synthetic-example",
      "input_sha256": "<actual decoded data URL image digest>",
      "E": 0,
      "request": {"path": "/operator/sealed-extraction.json", "sha256": "<digest>"}
    }]
  }]
}
```

`resources.json` names `service_dir`, `loader_override`, `canon_root`, and
`original_producer`. The public frozen resources listed in the assignment are
supported directly. Code pins Bakeoff SHA256 `87c58a41…3ca66`, original producer
`5c897549…b1838`, loader `4ac52b4f…79f68`, and depiction `765a46f1…a4fb8`.
The actual loader additionally checks depiction version `canon v0.26.2` and 17
rules. No rule text is copied into committed code or documentation. The supplied
private resource-config was permission-denied, so its schema and actual artifacts
were not inspected; adapt its public path metadata to this explicit contract.

The profile is pinned as opaque operator attestation, not inferred from a build
fingerprint or fetched from a metadata endpoint. Actual `response.model` is
required on every accepted response. Missing/wrong identity quarantines the stage
and stops that model stream, including on resume. Aliased duplicate model or
endpoint streams are rejected. Other model streams operate independently.

The extraction payload must match the original producer's genuine builder,
including its E treatment, original image part, seed zero, greedy temperature,
top-p one, no-thinking prompt, and 1536-token limit. The writer template requires
512 tokens, the same decoder controls, and native `response_format` with
`type=json_object` and a schema requiring exactly nonempty title/alt/caption
strings. Additional qualification fields survive unchanged. `_timed_chat` does
not carry this constraint and is deliberately not the execution path.

Both writer arms consume the same **verbatim** extraction text and image part,
including an accepted extraction's JSON fence and whitespace. The original
producer's image-hash final-nibble parity counterbalances writer order. Only W1
receives the genuine depiction lexicon. No context or roster is supplied.

## Native boundaries, deadlines and supervision

One request runs at a time per model, with a bounded model thread pool. Native
execution is `/usr/bin/curl -q`, header `@FILE`, connect timeout 5 seconds, maximum
time at most 300 seconds, zero retries, no redirects, no proxy, and only HTTP(S).
Each native attempt receives exclusive request, intent, response, metrics, header,
and result files. Curl writes through collector-owned exclusive file descriptors.
Curl reopens the response and header descriptors by `/proc/self/fd/N` path, and
Linux rechecks inode permissions on that open. The three boundary files are
therefore created `0600` and sealed `0400` (flush, `fchmod`, fsync, close) after
every outcome, including failed, timed-out or killed curl. A sealing failure
raises. All other evidence files are created `0400`. Response reads/downloads are bounded. Failed or interrupted curl processes and
non-200 responses cannot be accepted.

Admission requires more than a full timeout plus cleanup margin before the
earliest collector/model/heartbeat deadline, and is checked again after intent
fsync immediately before the boundary. Caller deadlines and native epoch are
sealed into `run.json`; a different deadline or config cannot resume that run.
No completion, lease extension or refund is inferred from elapsed time. SIGINT
and SIGTERM stop admission and kill only the collector's own process groups.
Filesystem/kernel stalls remain outside Python's hard timing guarantees; callers
must retain independent native cleanup as required by the assignment.

Optional heartbeat configuration:

```json
{
  "heartbeat": {
    "argv": ["/operator/caller-owned-heartbeat", "--caller-owned-argument"],
    "deadline_unix": 1793000000,
    "timeout_s": 5,
    "interval_s": 30,
    "max_count": 20
  }
}
```

The argv is executed without a shell in a dedicated thread. Commands and
intervals are capped at 300 seconds, counts at 10000; absolute deadlines still
apply. The first successful heartbeat gates collection. A command failure,
deadline failure or count exhaustion stops supervision and is reported as a
failure. Heartbeat receipts are separate from native inference counts. Tests use
only synthetic stub commands; this lane has not called a GPU API.

## Immutable resume and explicit legacy adoption

Files use `O_EXCL`/`O_NOFOLLOW`, fsync of files and parent directories, and no
replacement. Evidence directory ancestors cannot be symlinks. A collector-wide
nonblocking flock on `.collector.lock` serializes **this collector's invocations**.
No sibling or historical producer is known to take that fence; the operator must
keep other writers away from this evidence tree. The lock itself is the one
mutable coordination file. Each invocation has its own immutable summary and
heartbeat receipts.

Resume checks the complete run binding, stage request bytes, intent hash, file
hashes, model/profile/image/E/W/facts/parent-response lineage and genuine parser
acceptance again. An accepted extraction alone feeds missing writers. A failed
extraction yields terminal dependency skips. Failed, skipped, quarantined or
uncertain stages are never retried. An incomplete directory is an operator-review
stop, including a crash after intent but before response/result publication. This
chooses no duplicate POST over automatic crash recovery. Only absent stages are
newly submitted.

Previously completed directories are adopted **only** through an explicit config
entry; the tool never scans old directories or relies on a status label:

```json
{
  "adopt": [{
    "model_id": "qwen38-bf16", "image_id": "synthetic-example", "E": 0,
    "directory": "/operator/accepted-stage",
    "sha256": {
      "request.json": "<digest>", "intent.json": "<digest>",
      "response.json": "<digest>", "metrics.json": "<digest>",
      "result.json": "<digest>"
    }
  }]
}
```

Add `W: 0` or `W: 1` to adopt a writer. All five source files must be pinned;
request payloads must equal the genuine rebuilt payload in their entirety, while
their original serialization and raw hash are retained. The legacy intent and
result must both evidence every `binding` field used by this collector:
`model_id`, `precision`, `expected_response_model`, `request_model`, `endpoint`,
`profile_sha256`, `native_epoch`, `image_id`, `image_sha256`, `E`, `W`,
`request_sha256`, `facts_sha256`, `parent_response_sha256`. Extraction parent
fields and W are null. Writer parent fields bind the accepted extraction's
verbatim text hash and raw response hash.

Default selectors read `/binding/<field>` from both legacy records; a differing
schema can supply `intent_fields` and `result_fields` dictionaries mapping field
names to JSON pointers. Default result selectors are `/status` (must equal
`accepted`), `/files/response.json`, `/files/metrics.json`, and `/process` (with
`spawned=true`, `returncode=0`, `interrupted=false`). They can be named explicitly
with `status_field`, `response_sha256_field`, `metrics_sha256_field`, and
`process_field`. Missing evidence is a stop requiring operator review; operators
must not manufacture absent provenance. No actual legacy private bodies were
read, so compatibility with their exact field layout remains unverified.
For an older Boolean acceptance field, set `status_field` to its JSON pointer and
`accepted_value` to `true`; allowed string equivalents are `accepted`, `success`,
`ok`, and `completed`. This historical marker never replaces revalidation.

Adoption revalidates HTTP status, response identity, completion and genuine
acceptance before writing. Request/response/metrics and original intent/result
bytes are retained in the new immutable evidence. Existing accepted extraction
text feeds missing writers directly. Failed legacy stages do not become new
submission authority. Known prior failed stages must be omitted or explicitly
represented by terminal existing evidence, never scheduled into a fresh run.

Reports distinguish spawned native HTTP attempts, received HTTP responses, and
verified inference token receipts. A verified receipt requires accepted model
identity and completion plus internally consistent positive completion usage.
An accepted response lacking usage is counted as received, without a verified
inference receipt. Adopted and reused stages add no new native boundary counts.

## Offline verification and limitations

The root project is `package=false`; this lane owns a standalone module. Import
origin is checked by loading the collector from its absolute lane path. Genuine
service origin and resource pins are checked separately; this lane does not own
that frozen service package. No shared dependencies or service code were changed.

The approved suite is:

```sh
.venv/bin/python -m pytest --noconftest --basetemp=.task-state/qwen-factorial-test-tmp -q tests/test_qwen_factorial_collect.py
```

Five groups are independently selectable by these test node IDs (the parent
orchestrator owns partition execution):

| Node ID suffix | Cases | Coverage |
| --- | --- | --- |
| `::TestBindingsAcceptance` | 11 | Genuine parsing, strict writer JSON, image/profile/template binding, wrong-model quarantine |
| `::TestBoundsNoRetry` | 12 | Full deadline admission, curl constraints, terminal failures, distinct receipts, by-path-writable then sealed boundary files |
| `::TestCausalFactsLexicon` | 2 | Three actual stub native boundaries, shared verbatim facts, lexicon arms, zero-call resume |
| `::TestImmutableResumeEvidence` | 7 | Partial extraction reuse, incomplete claims, tampering, no clobber/reset, legacy adoption, symlinks |
| `::TestConcurrencyHeartbeatCleanup` | 7 | Concurrent streams, serialized model calls, bounded heartbeat failure/success, own-child cleanup, fence |

Final approved whole-file run: **39 passed** (Linux, non-root, no skips). Earlier
runs passed 28, 32 and 33 cases. The 33-case suite missed QWENFA-G1-F1 because its stub
wrote through the inherited descriptor and never reopened it by path. No partitions or
repo-wide discovery were run by this lane.

All HTTP boundaries are stubbed at subprocess.Popen or at the `Curl` runner; genuine
builders and both acceptance parsers execute. On Linux as non-root, a real Python child
reopens curl's `/proc/self/fd/N` argv paths. With the boundary mode reverted to `0400`,
it fails with `EACCES`. Real curl, GPU/native intent, production HTTP, tenant
media, credential reads, real legacy acceptance and live deadline cleanup have
not been exercised. The pinned heuristics authority at
`/Users/daniel/Development/heuristics-canon-current` is unavailable in this sandbox;
its manifest and cards could not be verified, so no heuristic row text or release
authority is asserted. The runtime depiction version above is a separate,
digest-checked builder dependency.
