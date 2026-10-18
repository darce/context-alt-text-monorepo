# GPUUX-1 fix1 — close the GPU-state deployment seam

## Context

`feature/gpuux-1` merged three lanes (B env-freshness, C api-reader, F lifecycle-writer)
adding a GPU tier snapshot: a host systemd unit writes `/run/acx/gpu-state.json`, the api
container reads it and reports a tier.

Adversarial review of the merged tree found **the feature is inert in production** for two
independent reasons. Every existing test passes because they all use `tmp_path` and never
touch the real deployment artifacts.

## Required work

### H-01 — the units cannot write (`scripts/deploy/gpu-lifecycle-install.sh`)

`/run/acx` is provisioned `root:10001` mode `0775` at ~L166-167, mirrored into
`/etc/tmpfiles.d/acx-gpu.conf` at ~L171. Both lifecycle units declare `User=ubuntu`
(`[Service]` at L111/113 and L141/143). There is no `usermod`, no `Group=`, no
`SupplementaryGroups=` anywhere in the script.

Result: the snapshot writer takes `PermissionError`, `write_gpu_state_snapshot()` warns and
returns `False` (`infra/oci/gpu_lifecycle/state_snapshot.py:130-145`), and the tier reports
`unknown` forever.

The comment at ~L163-165 documents the **original** data direction ("written by the api
container (uid 10001) and read by these units as ubuntu"). GPUUX-1 reversed that — the units
are now **writers**. Fix the ownership/group model to match the new direction and update that
comment so it stops describing the old one. Grant the units group write
(`SupplementaryGroups=`/`Group=` on both units, or re-own the directory) — pick one and make
the `tmpfiles.d` line agree with it. Do not widen the mode to `0777`.

### H-02 — the fix landed in the wrong file (`docker-compose.env.yml`)

`apps/prototype-description-service/docker-compose.env.yml` is what production actually
deploys (`scripts/deploy/recognition-service.sh:818-819`). Lane B added the
`ACX_GPU_STATE_PATH` env and the `/run/acx` mount to `docker-compose.prod.yml` instead, whose
own header (L3-10) states it is **not** the deploy path.

Two consequences in the deployed file:

1. `ACX_GPU_STATE_PATH` is absent from its environment block, so the reader has no configured path.
2. Its mount is `${ACX_DESCRIBE_LOAD_DIR:-/run/acx}:/run/acx` — **read-write**. For gpu-state
   the container must be a reader only; the host unit is the single writer. A read-write mount
   means two writers to one file, violating single-writer (DATA-14) — the exact class of bug
   the snapshot atomicity work was meant to prevent.

Add `ACX_GPU_STATE_PATH` (and `ACX_GPU_STATE_STALE_SECONDS` if the reader consumes it) to
`docker-compose.env.yml`, and make the gpu-state read path read-only.

**Careful:** the same `/run/acx` directory also carries `describe-load.json`, which the
container *does* write. If one directory must serve both directions, keep the load-dump write
working and expose gpu-state read-only (separate mount, or a separate dir) — do not silently
break the container's own write. State in your handoff which shape you chose and why.

### H-03 — the contract test cannot fail

`infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py` carries a module-scope
`pytest.importorskip`. If the import target is missing the whole contract file silently skips,
so a broken contract reports green. Remove the module-scope skip and let the import fail
loudly. If a genuinely optional dependency is involved, scope the skip to the single test that
needs it — never the module.

### H-04 — staleness has no lower bound

The freshness gate only rejects a `written_at` that is too **old**. A future-dated or
clock-skewed `written_at` passes and fabricates a `ready` tier from a snapshot that was never
actually written recently. Add a lower bound so a `written_at` meaningfully in the future is
treated as invalid. Pick a small tolerance for benign clock skew, name it, and test both edges.

### M-06 / M-07 — `scripts/deploy/check-gpu-snapshots.sh`

- **M-06**: it accepts *either* `"${snapshot_dir}:${snapshot_dir}:ro"` *or* the literal
  un-expanded template `'${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro'`. The second branch means the
  check passes on a compose file where the variable was never substituted. Close that hole.
- **M-07**: the script is invoked by no automated path. Wire it into an existing make target or
  deploy step so it runs without a human remembering it.
- While you are in there: it defaults to the wrong compose file. Point it at
  `docker-compose.env.yml`, the artifact that ships.

## Tests — this is the part previous lanes got wrong

Every writer test in this area uses `tmp_path`, which is why a directory the units cannot write
still looked green. Add tests that read the **real** artifacts as data:

- Parse `gpu-lifecycle-install.sh` (and the `tmpfiles.d` content it emits) and assert the unit's
  effective user can write the provisioned directory — assert the **relationship** between the
  ownership/group grant and the `User=` line, which are two independent declarations. A test
  that only re-states a constant you just typed is worthless.
- Parse `docker-compose.env.yml` and assert `ACX_GPU_STATE_PATH` is present and the gpu-state
  path is read-only to the container.
- Both edges of the H-04 staleness bound.

Write them as pytest under `infra/oci/gpu_lifecycle/tests/`.

**RED FIRST.** Run each new test against the unfixed tree and confirm it fails for the intended
reason *before* you fix anything. Report the red output in your handoff. A test you never saw
fail is not evidence.

## Test command

The remote gate accepts this exact form (`uv run`, `npx`, `composer` are refused before dispatch):

```
python3 -m pytest infra/oci/gpu_lifecycle/tests -q --tb=short
```

## Constraints

- **Never** add `Co-Authored-By` or any AI/model attribution to commit messages. Mandatory and permanent.
- Do not touch PHP or JS/TS — the UI half of GPUUX-1 is deferred.
- Do not relax or skip a lint/compliance gate to reach green (sr-001).
- Do not invent config values you cannot verify; if a path or uid is unknowable from the repo,
  say so in the handoff rather than guessing.
- Commit on `feature/gpuux-1` in this worktree.

## Done means

Four highs fixed, two mediums fixed, new tests observed RED before the fix and GREEN after, and
a handoff naming the compose mount shape chosen for H-02.
