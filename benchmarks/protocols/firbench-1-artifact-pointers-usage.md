# FIRBENCH-1 artifact pointers — first use

This page shows the first-use path for artifact pointers: register an existing evidence file, check it, and resolve it locally. A pointer records where a file is, the file's hash, and any declared provenance, in the same private evidence DB that the v0 corpus commands use. It locates evidence. It does not qualify anything: a pointer is not independent ground truth, annotation QC, capture occasion, human observation, or numerical acceptance. The frozen failed v6 result stays failed, and registering or checking a pointer does not re-score or re-qualify anything.

These commands are usage examples, not a record of a local private run.

## Paths and prerequisites

Run commands from `apps/prototype-description-service`. Replace the quoted placeholders with your own values; quote paths that contain spaces.

| Placeholder | Meaning |
|---|---|
| `"EVIDENCE_DB"` | The existing private DB, the same file the v0 corpus commands use. Keep it outside every Git checkout and worktree. |
| `"ARTIFACT_ID"` | Your public ID: ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. |
| `"RUN_DIR"` | An existing run directory produced by `run`. |
| `"FILE"` | The local evidence file to point at. |
| `"SHA40"`, `"SHA64"` | Declared hex digests, 40 and 64 characters. |

The DB must already exist and pass the v0 schema check. `register` never creates a DB. To create one, use the v0 `db-import` step in [the v0 guide](firbench-1-private-db-v0-usage.md). `show`, `check`, `resolve`, and `list` open the DB read-only and never create or change anything.

Keep the DB's immediate directory at `0700` and the DB file at `0600`. Registration never changes permissions on, or unlinks, existing files.

## One DB, two uses

- The corpus data (the stored manifest bytes, the pin, and `user_version` 1) is unchanged.
- The optional `artifact_pointer_v1` table is created only by an explicit `register`, inside a `BEGIN IMMEDIATE` transaction, after the existing v0 DB has been validated. No other command creates it.
- The v0 check allows extra tables, so the v0 `corpus_catalog` commands keep working on the same file.
- Every pointer command requires `--evidence-db`. Nothing is discovered automatically.
- The DB keeps rollback journal `DELETE`, `synchronous=FULL`, and a 5 s busy timeout.

## 1. Register

```bash
python -m scripts.eval_harness.firbench_cli evidence register "ARTIFACT_ID" \
  --evidence-db "EVIDENCE_DB" \
  --kind report-html \
  --path "FILE"
```

`--path` must resolve to a regular file, and it is stored as its absolute resolved path. The command streams the file through SHA-256, bounded to 256 MiB. The DB stores the path, the file hash, the kind, and the provenance fields below. It never stores file contents, image pixels, note blobs, identity maps, or embedded raw reports.

| `--kind` | `--path` must end in | Where the normal producer writes it |
|---|---|---|
| `report-html` | `.html` | `RUN_DIR/report/index.html` |
| `report-json` | `.json` | `RUN_DIR/report/report.json` |
| `scores-json` | `.json` | `RUN_DIR/scores.json` |
| `run-manifest` | `.json` | `RUN_DIR/manifest.json` |

Refused inputs: non-regular files (including FIFOs), image files, DB files, a kind/extension mismatch, and any file that changes while it is being hashed.

Re-registering the same file, ID, and metadata returns `already_registered`. A changed path, hash, or metadata under an existing ID is refused, and nothing is overwritten. For a changed artifact, register a new ID.

### Provenance flags

All of these are optional. Anything unknown is stored as `null`.

- `--source-sha SHA40`: the source SHA, when known. It is a declared value, not verified lineage.
- `--manifest-sha SHA64` with `--manifest-hash-kind`: a declared manifest pin. Pass the two flags together.
  - `raw-sha256`: SHA-256 of the manifest file's bytes.
  - `legacy-model-dump-sha256`: the legacy report's value, which is SHA-256 of `json.dumps(manifest.model_dump(), sort_keys=True)`. It is not a file hash.
- `--qualification {unqualified,partial}`: defaults to `unqualified`. Registration never qualifies evidence.

A declared pin is not verified lineage or labels. The pointer has no model, template, or gallery pin fields, so don't fill them in from guesses.

### Partial legacy JSON record

A recovered legacy report with incomplete provenance:

```bash
python -m scripts.eval_harness.firbench_cli evidence register "LEGACY_ID" \
  --evidence-db "EVIDENCE_DB" \
  --kind report-json \
  --path "FILE" \
  --manifest-sha "SHA64" \
  --manifest-hash-kind legacy-model-dump-sha256 \
  --qualification partial
```

If the source SHA is unknown, leave out `--source-sha`. If no manifest pin can be recovered, leave out both manifest flags. Either way the field is stored as `null`. `partial` marks incomplete provenance. It is not a qualification, and it never happens automatically.

## 2. Check

```bash
python -m scripts.eval_harness.firbench_cli evidence check "ARTIFACT_ID" --evidence-db "EVIDENCE_DB"
```

`check` rehashes the pointed file and reports `matched`, `missing`, or `changed`. It only reads.

## 3. Resolve

```bash
python -m scripts.eval_harness.firbench_cli evidence resolve "ARTIFACT_ID" --evidence-db "EVIDENCE_DB"
```

`resolve` verifies the hash and file type first. On success it prints only the local absolute path, for operator use, and exits `0`. If the file is missing or stale, it refuses with a fixed error and prints no path. It never reports a stale file as a success.

The printed path is private. Don't copy it into Git, MCP, prompts, logs, or shared notes.

## Show and list

```bash
python -m scripts.eval_harness.firbench_cli evidence show "ARTIFACT_ID" --evidence-db "EVIDENCE_DB"
python -m scripts.eval_harness.firbench_cli evidence list --evidence-db "EVIDENCE_DB" --limit 20
```

`show` and `list` print safe metadata only: ID, kind, hashes, nullable declared provenance, and qualification. They never print the stored path or file contents. `list` defaults to 100 rows and accepts at most 1000.

## Optional: register a report at render time

```bash
python -m scripts.eval_harness.firbench_cli report "RUN_DIR" \
  --evidence-db "EVIDENCE_DB" \
  --artifact-id "ARTIFACT_ID"
```

This is the only new auto-registration. Both flags are required together. Without both, `report` is unchanged.

- The DB and ID are validated before the producer writes, where possible.
- The producer returns `RUN_DIR/report/index.html`. That path is registered as `report-html` with qualification `unqualified`.
- If registration fails after rendering, the command returns an error, and the rendered report stays in place. Retry with the explicit `register` command above. The command never reports DB success it did not write.

The benchmark has no built-in server or web API. `report` writes a self-contained, interactive `RUN_DIR/report/index.html` and starts no server. To view it, open `"RUN_DIR/report/index.html"` directly in a local browser. Or, optionally, run a loopback static server yourself that serves only the report directory:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory "RUN_DIR/report"
```

Then open `http://127.0.0.1:8765/` in a browser, and stop the server with `Ctrl+C` when done. Port 8765 is only an example. Nothing starts this server automatically. Keep the DB and manifests outside the report directory. This page adds no server or UI.

`run` and `score` are unchanged. They do not read or write the registry, so don't assume they register anything.

## Errors and exit codes

- `check`: `0` matched, `1` missing or changed, `2` invalid.
- `resolve`: `0` only after the hash and type verify.
- An ID conflict is reported as invalid and exits `2`.
- Error messages are fixed text. They never include SQL values or private paths.

## What this guide does not claim

- Pointers locate and hash evidence. They are not independent ground truth, annotation QC, capture occasion, human observation, or numerical acceptance.
- The default qualification is `unqualified`. `partial` is not a qualification.
- Registering or checking pointers does not re-score or re-qualify the frozen v6 result.

Keep the DB, its paths, file contents, images, manifests, and real command output out of Git, commits, prompts, logs, and MCP. Share only the artifact ID, kind, hash, status, and aggregate counts.

Schema expansion, WAL, sync and backup policy, and broader performance and recovery work remain backlog items.
