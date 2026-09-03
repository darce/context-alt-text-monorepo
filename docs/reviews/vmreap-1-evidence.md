# VMREAP-1 evidence

All behavior claims below are pinned to an existing case name in
`scripts/vm/tests/test_reap_lane.sh` or
`scripts/vm/tests/test_install_reap_cron.sh`. The shell suites are also invoked
by `scripts/vm/tests/test_vm_script_suites.py`.

## Reaper contracts

| Behavior | Existing test case name(s) |
| --- | --- |
| The default allowlist includes `grok-sandbox`, while similarly prefixed directories and a root itself remain outside the deletion boundary. | `g2 grok-sandbox`; `g2 grok-sandbox prefix-not-root`; `g2 root itself` |
| An archive located inside the candidate is rejected and the candidate remains. | `archive destination inside lane` |
| Fresh sandbox markers, live leases, and held lane locks prevent both archival and removal. | `grok-sandbox fresh marker`; `grok-sandbox live lease`; `grok-sandbox lane lock` |
| A legacy marker is not persisted when a later dirty-tree guard skips the lane. | `grok-sandbox dirty legacy did not persist marker backfill` |
| A successfully reaped legacy sandbox removes its lock, lease, venv, and sync-stamp siblings. | `grok-sandbox stale legacy lane lock`; `grok-sandbox stale legacy lease`; `grok-sandbox stale legacy venv`; `grok-sandbox stale legacy sync stamp` |
| A non-sandbox archive candidate is retained until its newest checkout/git timestamp reaches the minimum age. | `archive recent lane`; `archive aged lane` |
| Branches, tag-only commits, and detached HEAD commits survive archival. | `archive reap`; `archive tag-only commit`; `detached HEAD` |
| Equal lane basenames in different roots use distinct archive namespaces. | `collision` |
| Re-materializing one path with an unrelated root commit creates a separate archive generation. | `rearchive first generation`; `rearchive second generation` |
| A reset commit reachable only from the reflog is preserved under `refs/reaped/<path>/<generation>/reflog/<sha>`, and its tree remains readable. | `archive reflog-only commit`; `archive reflog-only commit tree is readable` |
| A successful push is not trusted without archive read-back. | `archive that drops refs`; `archive that drops refs keeps the lane` |
| A failed `rm` is reported as an internal error, is not counted as a reap, and leaves the lane. | `rm failure exits 1`; `rm failure summary`; `rm failure still exists` |
| A change to refs, HEAD, stash state, or worktree status after the decision snapshot prevents removal with `lane changed after snapshot; skipped`. | `lane changed after snapshot`; `lane changed after snapshot fixture committed` |
| Stale mkdir-lock recovery preserves the old owner inode, and two recoverers admit exactly one sweep. | `mkdir fallback atomically preserved stale owner`; `mkdir fallback stale recovery admits exactly one reaper` |
| Missing `df` output fails safe with a numeric 100% usage value. | `df unavailable`; `df unavailable contains df_used_pct=100` |

The second safety snapshot is the final state gate before marker backfill and
`rm`. There is still a residual race window between that snapshot and `rm`;
the implementation comment records the same limit. The test case `lane changed
after snapshot` demonstrates detection before that window and does not claim
the window is zero.

## Installer contracts

| Behavior | Existing test case name(s) |
| --- | --- |
| A fresh install deploys an executable reaper, creates a bare keep-repo, and schedules every supported root with `--archive-to`. | `fresh installs the script`; `fresh creates the keep-repo`; `fresh crontab contains --archive-to $HOME/lane-archive.git`; `fresh crontab contains --all $HOME/w3`; `fresh crontab contains --all $HOME/uxw2`; `fresh crontab contains --all $HOME/l1`; `fresh crontab contains --all $HOME/w`; `fresh crontab contains --all $HOME/lanes`; `fresh crontab contains --all $HOME/grok-sandbox` |
| Reinstalling preserves existing archive refs and replaces stale managed cron text without duplicating the marker or touching an unrelated job. | `reinstall preserves archived refs`; `roll-forward`; `roll-forward keeps exactly one marker`; `roll-forward crontab contains /usr/bin/some-other-job` |
| Reinstalling replaces the deployed script inode instead of overwriting it in place. | `reinstall atomically replaces the installed inode` |

## Red-first evidence for wave 4b

Before the implementation, `archive reflog-only commit` failed because the
`refs/reaped/.../reflog/<sha>` ref was absent and `archive reflog-only commit
tree is readable` failed. The concurrent-mutation fixture committed
successfully, but `lane changed after snapshot` failed because the reaper
reported the older generic archive failure instead of the required state-change
skip.

## Verification

The required commands are:

```text
bash scripts/vm/tests/test_reap_lane.sh
bash scripts/vm/tests/test_install_reap_cron.sh
python3 -m pytest scripts/vm/tests/test_vm_script_suites.py -q
```
