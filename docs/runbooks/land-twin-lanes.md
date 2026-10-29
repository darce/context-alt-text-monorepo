# Land synthetic twin lanes

Owner: task integration coordinator. Implementation and behavioral contract:
`scripts/workstate/land_twin_lanes.py` and `scripts/tests/test_land_twin_lanes.py`.
Requires Git, Python 3.12+ and Unix `fcntl`; no third-party runtime imports.

Use this helper to compose reviewed lanes whose old branches include copied main
history. It compares **each declared base to its declared tip**. A diff from
`merge-base(main, tip)` can import unrelated copied history and is never used.
The ERRFIX historical shorthand bases/tips (`db9651a064` → `88439ae3c2`,
`dbeb8a0eed` → `601bc83009`, `18fec744c2` → `ca443d6923`) describe prior art,
not executable defaults. Resolve and independently verify full SHAs and ownership
in the actual repository before making a spec. The old ignored
`.task-state/errfix-1/integrate.py` is not required or imported.

## Spec and command contract

Write an operator-owned JSON spec outside tracked source. All keys below except
`expected_tree` and `cleanup` are required. Unknown keys are rejected. This is a
template: replace every placeholder before use.

```json
{
  "task": "EXAMPLE-1",
  "integration": {
    "checkout": "/absolute/path/to/integration-checkout",
    "branch": "integration/example-1",
    "base": "<full integration base commit SHA>"
  },
  "expected_tree": "<full independently checked composed tree SHA>",
  "receipt": ".task-state/EXAMPLE-1/land-twin-receipt.json",
  "lanes": [
    {
      "id": "lane-a",
      "branch": "reviewed/example-1-a",
      "base": "<full lane base commit SHA>",
      "tip": "<full reviewed lane tip commit SHA>",
      "owned_paths": ["scripts/example.py", "docs/example"]
    }
  ],
  "cleanup": {"branches": ["reviewed/example-1-a"]}
}
```

`base` and `tip` are immutable full commit SHAs, never moving branch aliases or
abbreviations. Each local lane branch must still point to its declared tip, and
its declared base must be an ancestor of that tip. The integration branch must
be checked out at the exact declared base, or at the last verified receipted
landing on resume. Lane list order determines landing order. Ownership entries
are exact relative files or directory prefixes, without glob expansion, trailing
slashes, `..`, `.git`, or symlinks. Only regular file additions/edits/deletions
and executable-bit changes are supported; changed symlinks and submodules fail
closed. An overlapping lane can proceed only when the current blob **and mode**
equal its base or already equal its desired tip. No fuzzy application occurs.

`receipt` must be an ignored, untracked path below `.task-state/<task>/` in the
integration checkout. Keep it outside all lane ownership. Specs, checkouts,
receipt paths and owned paths must have no symlink components. Do not put
arbitrary commands, process IDs, remote jobs, worktree paths or sandbox paths in
the spec. There is no shell execution interface.

```sh
python scripts/workstate/land_twin_lanes.py --spec /absolute/path/spec.json --task EXAMPLE-1 --check
python scripts/workstate/land_twin_lanes.py --spec /absolute/path/spec.json --task EXAMPLE-1 --apply
python scripts/workstate/land_twin_lanes.py --spec /absolute/path/spec.json --task EXAMPLE-1 --cleanup
```

`--task` is an independent operator assertion and must match the spec. Successful
commands print one JSON receipt to stdout and exit 0. Refusals and Git/I/O/import
failures print `land_twin_lanes: ...` to stderr and exit 1; argument errors use
argparse's exit 2. Every Git subprocess has a 30-second deadline. Run without
concurrent Git writers; the helper serializes its own invocations per checkout
and receipt but cannot lock out unrelated Git tools or editors.

## Check and land

1. Complete the coordinator's declared review and integration gates. This helper
   does not implement reviews, grading, task plan ticks, deployment or lifecycle
   state. It does not emit a review-pipeline MERGE artifact or assert merge
   readiness. Obtain that artifact through the owning pipeline.
2. Make tracked files and the index clean. Hidden assume-unchanged/skip-worktree
   flags, untracked or ignored collisions, and in-progress Git operations refuse.
   Unrelated ignored operator state can remain; the helper never discards it.
3. Run `--check`. It reads the integration base into a temporary
   `GIT_INDEX_FILE`, updates only declared base→tip deltas and writes exact tree
   objects. It records each lane's changed paths and resulting tree in the
   receipt. The real index (including cache metadata), worktree and HEAD remain
   unchanged. Git objects and the ignored receipt/lock files are durable effects.
4. Review `composed_tree`, `steps`, and `spec_sha256`. If the tree was unknown,
   omit `expected_tree` initially. To pin the reported tree, preserve that spec
   and receipt as evidence and create a new spec with a **new receipt path**
   before checking again. Editing a spec behind its receipt is refused.
5. Run `--apply` with the checked spec. It recomputes and validates the complete
   composition before the first landing. It writes a pending record, runs
   `git merge -s ours --no-commit --no-ff` for each tip not already ancestral,
   then uses a protected two-tree index/worktree checkout for the exact composed
   delta. A normal `git commit` runs configured hooks; no `--no-verify`, reset,
   force checkout or gate bypass is used. Each lane gets one landing with the
   checked tree; merge parents retain its reviewed history. If already ancestral,
   an empty single-parent landing still records that lane.
6. Compare final `composed_tree` to `HEAD^{tree}` and retain the receipt. Tree
   equality includes removals and executable modes, not only changed-file text.
   Rerunning `--apply` preserves existing landing commits and appends an attempt.

Landing order, message, trees, author/committer identity and dates are fixed by
the spec and lane commits. With the same parents and normal unsigned Git
configuration, commit IDs repeat. Configured signing and hooks still run; a hook
that changes the checked tree/message causes a loud failure with evidence kept.
Do not turn off a failing gate to make the helper succeed.

## Recovery and rollback

The `land-twin-lanes/v1` receipt binds `task`, `spec_sha256`, `integration_base`,
`composed_tree` and `steps`. `landings` stores each exact commit, parent, lane tip
and tree. `pending` is written before mutation. `attempts` and `cleanup_results`
are preserved across retries; receipt replacement is atomic and fsynced.

After a failed hook or interrupted apply, inspect the receipt and Git status,
resolve the actual gate failure, and rerun `--apply` with the same spec. Resume
accepts only the recorded parent/merge tip and the old or expected index tree,
with no unstaged changes. A commit completed just before receipt persistence is
adopted only after checking its exact parents, tree and message. Dirty work,
foreign Git operations, moved refs or altered receipt contracts stop recovery.
A timed-out command may have left state; inspect it before retrying.

Rollback is **revert**, using completed landing commits from the preserved
receipt in reverse order (`git revert -m 1 <merge-landing>`; use ordinary
`git revert <commit>` for a single-parent landing). Run the usual review gates
for rollback too. If a landing is still pending, preserve its receipt and
patch/status evidence and resolve that operation first; the helper never wipes
the checkout to return it to the base. After rollback, preserve the old receipt
and use a newly reviewed spec/receipt for further work. Never erase previous
receipts, operator data, or `attempt-evidence-*` directories as recovery.

## Retire exact branches

When task-finish owns the task worktree, run the owning **task-finish workflow
before lane cleanup**, following its normal gate/close requirements. This helper
does not recreate task-finish, run close-check, install a temporary dirty
allowlist, or remove any worktree. A checked-out lane branch is retained with
Git's explicit reason so that lifecycle tooling can finish teardown first.

`--cleanup` requires complete, verified receipted landings and positive tip
ancestry in integration. All registered worktrees must be clean and free of
in-progress Git operations. Only names in `cleanup.branches` are considered,
and each must be a declared lane still at the pinned tip. Deletion uses
`git branch -d`; never `-D`. Results are `deleted` or `retained` with a reason.
A write-ahead `deleting` record permits recovery after an interrupted deletion.
A successful command can contain retained branches: inspect `cleanup_results`.
Missing branches without matching deletion evidence are refused.

Remote sandbox deletion is deliberately **not supported** by this helper.
Use the remote provider's explicit cleanup workflow only after checking exact
paths, task/provenance markers and job inactivity; preserve all attempt evidence.
No opt-in or marker here authorizes deleting files, stopping jobs, broad sweeps,
or handoff retention cleanup. Unknown cleanup keys fail closed.

## Validation and rationale

Scoped test command (stdlib fixtures and existing pytest only):

```sh
python -m pytest -q scripts/tests/test_land_twin_lanes.py
```

The fixtures produce actual Git trees, copied synthetic history, branch tips,
mode changes, deletions and hooks before asserting behavior. They cover rejected
writes, hidden index flags, dirty/untracked/ignored data, optional lock import
failure, missing Git, timeouts, receipt I/O and schema failures, interrupted
apply/cleanup recovery and branch retention. No unrelated suite is required.

Canon **v0.26.2** (relevant pinned-manifest digests verified on the implementation
VM): [OPS-75], **Improve the measured constraint** (*The DevOps Handbook*, ch. 2),
targets the observed review-pass→merge queue rather than claiming source runtime
alone solved delivery; [TEAM-42], **Make repeatable guidance executable**
(*The DevOps Handbook*, ch. 20), makes repeated integration a shared tool and
behavioral contract. [GRPH-32], **An edge exists only where data moves**, and
[GRPH-33], **A node without a contract cannot be parallelised** (practice labels),
bind composition/landing/cleanup through named spec and receipt fields.
[AGT-10], **Degrade loudly** (*The Art of UNIX Programming*, ch. 1), requires
reported refusals with preserved state instead of silent repair or disposal.
