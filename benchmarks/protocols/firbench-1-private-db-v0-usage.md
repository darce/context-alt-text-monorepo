# FIRBENCH-1 private evidence DB v0 — first use

v0 imports a local frozen corpus manifest into a private SQLite file and reads it through `show` and `check`. The workflow uses the tracked `benchmarks/manifests/corpus-catalog-v1.json`, a local copy of the pinned manifest, and the separate original images for `check`. These commands are usage examples, not a record of a local private run.

## Paths and prerequisites

Run the three commands below from `apps/prototype-description-service`. Replace the placeholders with your own values; quote paths containing spaces.

| Placeholder | Meaning |
|---|---|
| `REPO` | Repository root containing `benchmarks/`; `../..` from the command directory. |
| `CORPUS_ID` | A key under `corpora` in the tracked catalog. |
| `PRIVATE_DB` | Private DB outside every Git checkout and worktree, for example `/srv/firbench-private/evidence.db`. |
| `LOCAL_MANIFEST` | Local frozen source manifest JSON, for example `/srv/firbench-private/input/manifest.json`. |
| `ROOT` | Optional corpus parent directory containing the catalog's `images_subdir` (normally `originals/`). |

The DB path is checked after symlink resolution. Keep its immediate directory private (`0700`) and the DB file `0600`; import uses those modes for newly created directories and files, without changing existing permissions. Use a separate file from `handoff.db`. Supply `--evidence-db` on every command; the DB is never discovered automatically.

Images stay separate: the DB stores manifest bytes, never image bytes, and these commands do not copy images. By default, image lookup uses the primary checkout's physical root plus the catalog's `root_relative` and `images_subdir`. A normal checkout or linked worktree supports this default.

For images elsewhere, or when the default cannot be resolved, append `--corpus-root ROOT` to either `show` or `check`. Pass the directory **containing** `originals/`, not `originals/` itself: if images are in `/srv/corpus/originals/`, use `/srv/corpus`. The resolver appends the catalog's `images_subdir` to `ROOT`.

## 1. Import

```bash
python -m scripts.eval_harness.corpus_catalog db-import CORPUS_ID \
  --repo-root REPO \
  --evidence-db PRIVATE_DB \
  --manifest LOCAL_MANIFEST
```

Import requires the exact source bytes: their SHA-256 must equal the catalog's `manifest_sha256`. It stores those bytes unchanged, preserving all fields and qualification provenance. Repeating the import with identical bytes is a no-op; changed bytes or a changed pin are refused. There is no update or overwrite command. The DB copy is authoritative for the import; editing either manifest file does not update it.

## 2. Show

```bash
python -m scripts.eval_harness.corpus_catalog show CORPUS_ID \
  --repo-root REPO \
  --evidence-db PRIVATE_DB
```

`show` opens the DB read-only, verifies the stored manifest against the catalog pin, and reports the private DB as the manifest source. It never creates a missing DB. Exit codes are `0` for success and `2` for error.

## 3. Check

```bash
python -m scripts.eval_harness.corpus_catalog check CORPUS_ID \
  --repo-root REPO \
  --evidence-db PRIVATE_DB
```

`check` verifies the DB manifest pin, then hashes the declared originals using `sha256_source`; both DB and images are read-only. It reports aggregate `entries`, `present`, `matched`, `missing`, `mismatched`, and `unsafe_paths` counts. Exit codes are `0` complete (every entry matched), `1` incomplete, and `2` invalid.

Without `--evidence-db`, legacy `show` and `check` behavior is unchanged. DB settings remain rollback journal `DELETE`, `synchronous=FULL`, and a bounded 5 s busy timeout.

Availability is not ground truth: importing a manifest or matching images creates no qualified labels, changes no qualification, and does not fix or re-score the frozen failed v6 result. Historical context remains unqualified.

Keep the DB, local manifest, image paths, and real command output out of Git, commits, prompts, logs, and MCP. Share only safe summary fields: corpus ID, hash, entry count, aggregate counts, and status.

Schema and annotation expansion, WAL, sync, backup, and broader performance or recovery work remain backlog items.
