# Orca on WorkBay-owned worktrees

WorkBay owns worktree creation and provisioning. Orca is a view: it adds the
Git worktree and branch, then its `orca.yaml` hooks hand the worktree to
WorkBay. Orca copies nothing into a worktree (no `worktree.sharedDirectories`,
no `.worktreeinclude`), and removing a worktree in Orca never closes the
WorkBay task.

## Files

- [`orca.yaml`](../../orca.yaml): setup and archive hooks, agent start policy.
- [`scripts/orca/setup_worktree.py`](../../scripts/orca/setup_worktree.py): setup hook; claims the task through `make task-start`.
- [`scripts/orca/archive_worktree.py`](../../scripts/orca/archive_worktree.py): archive hook; read-only dirty-worktree refusal.
- [`mk/worktree-bootstrap.mk`](../../mk/worktree-bootstrap.mk): default `LIFECYCLE_WORKTREE_BOOTSTRAP`.
- [`scripts/workstate/bootstrap_worktree.py`](../../scripts/workstate/bootstrap_worktree.py): WorkBay bootstrap.
- [`scripts/workstate/provision_lane_worktree.py`](../../scripts/workstate/provision_lane_worktree.py): overlay and dependency-tree provisioner.

Gitignored overlay files in the primary checkout, not linked here:
`Makefile.d/lifecycle.mk` (`task-start`, `task-finish`) and
`docs/workbay/contracts/harness-protocol.yaml` (overlay prefixes).

## Prerequisites

- Orca has the **primary** checkout (`main`) open. Hooks get
  `ORCA_ROOT_PATH` (primary), `ORCA_WORKTREE_PATH` (new worktree) and
  `ORCA_WORKSPACE_NAME`.
- The primary `.venv/` has WorkBay installed. Hooks run
  `$ORCA_ROOT_PATH/.venv/bin/python`; setup imports
  `workbay_protocol.branch_naming`; the bootstrap needs `pyyaml`.
- The primary has its gitignored overlay, including `Makefile.d/` and
  `docs/workbay/contracts/harness-protocol.yaml`.

## Orca settings (one-time, by hand)

No repository file sets these. Change them in Orca:

- **Branch prefix:** Custom, `feature`.
- **Branch auto-rename:** off. The branch must keep the task name WorkBay
  registered.
- **Repository hooks:** trust this repository's `orca.yaml` and allow its
  setup script to run. The exact Orca labels for the trust prompt and the
  setup run policy are unverified.

`orca.yaml` sets `setupAgentStartupPolicy: wait-for-setup`. Orca's default,
`start-immediately`, would start the agent in an unprovisioned worktree.

## Branch names

Setup accepts only `feature/<task-ref>`, checked with
`workbay_protocol.branch_naming.TASK_REF_RE`:

- Lowercase letters, digits and hyphens; starts with a letter; at least one
  hyphen; at least one digit.
- Accepted: `feature/orca-1`, `feature/e21-5`.
- Refused: `feature/orca` (no digit), `feature/orca1` (no hyphen),
  `feature/ORCA-1` (uppercase), `orca-1` (no prefix).

The claimed task ref is the suffix upper-cased: `feature/orca-1` claims
`ORCA-1`.

## Create flow

1. In Orca, create a worktree named with the lowercase task ref, e.g.
   `orca-1`. Orca adds it on branch `feature/orca-1`.
2. Orca runs `scripts.setup`, i.e. `scripts/orca/setup_worktree.py`.
3. Setup checks the hook environment and the branch, then runs
   `make --no-print-directory -C <primary> task-start TASK=ORCA-1 MODE=claim LIFECYCLE_ARGS=--json`.
   It passes no `OBJECTIVE`, so an existing objective is kept.
4. `task-start` runs `LIFECYCLE_WORKTREE_BOOTSTRAP` in the new worktree
   (default: `bootstrap_worktree.py --worktree .`), streams its output to
   stderr, and records `worktree_bootstrap` (`ran`, `ok`, `skipped`, `exit`)
   in its JSON receipt.
5. Setup exits `0` only when `make` exits `0`, a JSON receipt is printed, and
   both `ok` and `worktree_bootstrap.ok` are `true`.
6. Orca starts the agent after setup finishes (`wait-for-setup`).

Whether Orca still starts the agent when setup exits non-zero is unverified.
Do not work in a worktree whose setup failed until the refusal is fixed.

## What the bootstrap does

`bootstrap_worktree.py`, in order:

1. Refuses the primary checkout.
2. Links `<worktree>/.venv` to `<primary>/.venv` when the worktree has none.
   This happens before provisioning: copied `Makefile.d/` does not parse
   without it.
3. Reads overlay prefixes from the primary's `harness-protocol.yaml`, key
   `bootstrap_overlay.tracked_vs_overlay_boundary.overlay_managed_prefixes`.
4. Runs `provision_lane_worktree.py` with one `--overlay-path` per prefix, on
   top of its built-in paths. Only gitignored entries are copied; tracked
   files are never overwritten.
5. Excludes `literature/` with a sparse checkout when sparse checkout is off
   and `literature/` is clean. `--no-sparse` skips this step.
6. Checks that `make -n context` and `make -n slice-commit` resolve in the
   worktree (120 s each).

Success prints one JSON line on stdout (`ok`, `worktree`, `primary`,
`overlay_paths`, `venv`, `sparse`, `postconditions`). Diagnostics go to
stderr.

## Refusals

Read stderr first: each refusal names the failed check.

### Setup hook (`setup_worktree.py`)

| Exit | Cause | Fix |
| --- | --- | --- |
| `1` | Detached `HEAD`, or the branch is not `feature/<task-ref>` | Apply the Orca settings above; recreate the worktree with a valid name |
| `2` | `ORCA_ROOT_PATH` or `ORCA_WORKTREE_PATH` missing, relative or not a directory; worktree is the root; worktree is not a linked worktree of `ORCA_ROOT_PATH` | Open the primary checkout in Orca |
| `2` | `workbay_protocol.branch_naming` not importable | Install WorkBay into the primary `.venv` |
| `2` | `--objective` holds a single quote, newline or control character (manual runs only; `orca.yaml` passes none) | Drop those characters |
| `3` | `task-start` failed, printed no JSON receipt, or `ok` or `worktree_bootstrap.ok` is not `true`; a skipped bootstrap counts as failure | Fix the cause in the `task-start` stderr; for a bootstrap refusal, then [bootstrap the existing worktree](#bootstrap-an-existing-worktree) |

### Bootstrap (`bootstrap_worktree.py`)

| Exit | Cause | Fix |
| --- | --- | --- |
| `2` | Worktree is the primary checkout | Pass a linked worktree |
| `2` | `harness-protocol.yaml` or `pyyaml` missing, or `overlay_managed_prefixes` is not a non-empty list of non-empty strings | Restore the primary's overlay; install `pyyaml` in the primary `.venv` |
| `3` | The provisioner exited non-zero (its stderr follows), or `git sparse-checkout set` failed | Fix what the provisioner names; for a sparse failure, re-run with `--no-sparse` |
| `4` | `make -n context` or `make -n slice-commit` failed or timed out in the worktree | Compare the worktree's `Makefile.d/` with the primary's; re-run the bootstrap |

## Upstream defect: `ok: true` regardless of bootstrap

`make task-start` reports top-level `ok: true` even when the bootstrap
failed, timed out or was skipped (darce/workbay#3). Read
`worktree_bootstrap.ok`, never `ok` alone. The Orca setup hook already does;
manual `task-start` callers must check it themselves.

## Bootstrap an existing worktree

Use this for a worktree created before ORCA-1, one whose bootstrap failed, or
one started with the bootstrap disabled. It provisions only; it does not
register or claim a task. Run from the primary checkout:

```sh
.venv/bin/python scripts/workstate/bootstrap_worktree.py --worktree <path>
```

To keep `literature/` checked out:

```sh
.venv/bin/python scripts/workstate/bootstrap_worktree.py --worktree <path> --no-sparse
```

Exit codes are in the bootstrap table above.

## Disable the bootstrap

Pass an empty value on the `make` command line:

```sh
make task-start TASK=<REF> LIFECYCLE_WORKTREE_BOOTSTRAP=
```

- `task-start` skips the bootstrap; `worktree_bootstrap` reports it skipped
  and top-level `ok` stays `true` (darce/workbay#3).
- Under Orca, a disabled bootstrap makes setup exit `3`.
- Precedence, highest first: `make` command line, environment,
  `mk/worktree-bootstrap.mk`, the overlay's empty default in
  `Makefile.d/lifecycle.mk`. The `Makefile` includes `mk/*.mk` before
  `Makefile.d/*.mk`, so the tracked default wins.
- A replacement command must not contain a single quote: the overlay recipe
  single-quotes the value.
- `WORKBAY_WORKTREE_BOOTSTRAP_TIMEOUT` bounds the bootstrap (default 600 s).
  Under Orca, setup stops `task-start` after 900 s regardless.

Check the wiring from the primary:

```sh
make -n task-start TASK=<REF> MODE=claim LIFECYCLE_ARGS=--json
```

The printed `WORKBAY_WORKTREE_BOOTSTRAP_CMD=` must name
`bootstrap_worktree.py`. `''` means the bootstrap is disabled or
`mk/worktree-bootstrap.mk` is not included.

## Remove a worktree

Close the task with WorkBay, from the primary, after the branch merges:

```sh
make task-finish TASK=<REF>
```

Orca removal never closes the WorkBay task row. `scripts.archive` runs
`archive_worktree.py`, a read-only guard (rg-017: removing a dirty worktree
destroys uncommitted work). It never deletes, moves, stashes or writes.

- Exit `1`: `git status --porcelain=v1 --untracked-files=all` is non-empty.
  Stderr lists the dirty paths (first 50) and the fix: commit task-owned
  changes on the branch or move them, then run `make task-finish` from the
  primary.
- Exit `2`: `ORCA_WORKTREE_PATH` missing, not a directory or not in a Git
  worktree, or it is `ORCA_ROOT_PATH`.
- Exit `0`: clean. Stderr notes that the WorkBay task is still open.

How Orca honours the refusal:

- `orca worktree rm --run-hooks` runs the hook and stops on its refusal.
- `--force` does not waive the refusal.
- `--allow-failed-archive-hook` waives it. Never use it on a dirty worktree.
- Without `--run-hooks` the hook does not run, and nothing guards the
  worktree.
- Deleting from the Orca UI: whether the hook runs and its refusal holds is
  unverified. Treat UI deletion as unguarded.

Run the same guard by hand before any removal, from the primary:

```sh
ORCA_WORKTREE_PATH=<path> .venv/bin/python scripts/orca/archive_worktree.py
```

## Verification status

- From the ORCA-1 plan, checked against Orca's shipped
  `out/shared/orca-yaml.js` and app bundle: the `orca.yaml` keys, the
  `setupAgentStartupPolicy` values and default, and the hook environment.
- Unverified: whether deleting from the Orca UI runs the archive hook and
  honours its refusal.
- Unverified: whether Orca starts the agent after setup exits non-zero.
- Unverified: the exact Orca labels for trusting `orca.yaml` and the setup run
  policy.
- Unverified: a live Orca run of the whole create flow. None was recorded when
  this runbook was written.
