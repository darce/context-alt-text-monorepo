# GPUUX-1 H-03 lane report

## Change summary

- Split production snapshot ownership: `/run/acx` remains the host-owned,
  read-only GPU-state mount, while `${ACX_DESCRIBE_LOAD_DIR}` is mounted
  read-write at `/run/acx-write/prod` for the API's atomic load publication.
- Passed the load path, state staleness, and load refresh settings through the
  production API service.
- Made the production environment example declare `ACX_ENV=prod`, the writable
  load directory, and its namespaced `describe-load.json` path.
- Updated the OCI runbook's ownership table, aggregation paths, and fenced
  snapshot-check command. The command's explicit `ACX_*` vocabulary is
  contract-tested against the checker script.
- Added a PyYAML-backed regression test covering compose mounts/environment,
  the production env example, and documented-command parity.

## RED evidence

Command:

```bash
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/deploy/tests/test_prod_compose_load_mount.py -q
```

Tail before implementation:

```text
FAILED scripts/deploy/tests/test_prod_compose_load_mount.py::test_prod_compose_splits_read_only_state_from_writable_load
FAILED scripts/deploy/tests/test_prod_compose_load_mount.py::test_prod_env_uses_namespaced_writable_load_directory
FAILED scripts/deploy/tests/test_prod_compose_load_mount.py::test_readme_snapshot_check_command_tracks_checker_environment
3 failed in 0.42s
```

## tests_run

Final command:

```bash
lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/deploy/tests/test_prod_compose_load_mount.py -q; git diff --check
```

Tail:

```text
...                                                                      [100%]
3 passed in 0.20s
```

## Mutants

### Writable production load mount changed to read-only — KILLED

```diff
-      - ${ACX_DESCRIBE_LOAD_DIR}:/run/acx-write/prod
+      - ${ACX_DESCRIBE_LOAD_DIR}:/run/acx-write/prod:ro
```

Test tail:

```text
FAILED scripts/deploy/tests/test_prod_compose_load_mount.py::test_prod_compose_splits_read_only_state_from_writable_load
1 failed, 2 passed in 0.32s
```

### Production env load path reverted to host state directory — KILLED

```diff
-ACX_DESCRIBE_LOAD_PATH=/run/acx-write/prod/describe-load.json
+ACX_DESCRIBE_LOAD_PATH=/run/acx/describe-load.json
```

Test tail:

```text
FAILED scripts/deploy/tests/test_prod_compose_load_mount.py::test_prod_env_uses_namespaced_writable_load_directory
1 failed, 2 passed in 0.25s
```

Both mutants were restored before final verification.

## Blockers

None.

## Findings outside ownership (do not fix)

- The current sibling-lane files `docker-compose.env.yml`,
  `gpu-lifecycle-install.sh`, and `check-gpu-snapshots.sh` still contain the
  pre-namespacing `/run/acx-write/describe-load.json` topology in this isolated
  base. Lane H-04 owns their required namespacing and lifecycle aggregation;
  this lane did not edit them.
