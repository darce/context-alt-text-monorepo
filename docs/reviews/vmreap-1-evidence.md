# VMREAP-1 evidence

HEAD (pre-edit): `746c3227c84a8fd624c3e80448afaf621a88e07d`

## DEFECT

Two independent gaps were confirmed on the live VM before any edit.

**(1) Wrong roots.** `scripts/vm/reap-lane.sh` defaulted to
`REAP_LANE_ROOTS="w3 uxw2 l1 w lanes"` and `scripts/vm/install-reap-cron.sh`
swept `'$HOME/w3 $HOME/uxw2 $HOME/l1 $HOME/w $HOME/lanes'`. Neither named
`grok-sandbox`:

```text
$ grep -rn "grok-sandbox" scripts/vm/ Makefile.d/
(no matches)
```

Every offload lane the orchestrator creates lands at
`/home/gate/grok-sandbox/feature-<branch>-<hash>`.

**(2) Wrong user.** `install-reap-cron.sh` installs the crontab of the invoking
user and `process_one` refuses any path outside `$HOME`, so a cron installed as
`ubuntu` can never reach lanes owned by `gate`.

## RECON (operator-run, verbatim)

```text
$ ssh gate@acx-backend 'du -sh ~/grok-sandbox; ls -d ~/grok-sandbox/*/ | wc -l; ls -l ~/bin/reap-lane.sh; ls -d ~/lane-archive.git; df -h /'
60G     /home/gate/grok-sandbox
197
ls: cannot access '/home/gate/bin/reap-lane.sh': No such file or directory
ls: cannot access '/home/gate/lane-archive.git': No such file or directory
/dev/sda1       193G  177G   17G  92% /
```

60G across 197 lane dirs, and `gate` has neither the reaper nor the archive
repo. This is the RES-07 failure VMDISK-1 was built to fix, recurring one root
later: the five listed roots had stopped growing while the unlisted one
absorbed everything.

## RED

```text
$ bash scripts/vm/tests/test_reap_lane.sh
FAIL: g2 grok-sandbox missing 'WOULD REAP'; out=SKIP \
  /private/var/.../reap-lane-test.cbrQXn/grok-sandbox/feature-vmreap-1-abc1234: \
  not under allowlisted lane root

$ bash scripts/vm/tests/test_install_reap_cron.sh
FAIL: fresh crontab missing '--all $HOME/grok-sandbox '
```

The second reap-lane case (`grok-sandbox-old/lane-x` remained skipped) passed
while RED and pins the segment-exact matcher: widening the roots must not come
from weakening `is_under_lane_root` into a prefix match.

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
| A successfully reaped legacy sandbox retains the materializer-owned lock inode while removing its lease, venv, and sync-stamp siblings; a concurrently recreated lock is also retained. | `grok-sandbox stale legacy lane lock inode retained`; `grok-sandbox stale legacy lease`; `grok-sandbox stale legacy venv`; `grok-sandbox stale legacy sync stamp`; `grok-sandbox recreated lane lock inode retained` |
| A non-sandbox archive candidate is retained until its newest checkout/git timestamp reaches the minimum age. | `archive recent lane`; `archive aged lane` |
| Branches, tag-only commits, and detached HEAD commits survive archival. | `archive reap`; `archive tag-only commit`; `detached HEAD` |
| Equal lane basenames in different roots use distinct archive namespaces. | `collision` |
| Re-materializing one path with an unrelated root commit creates a separate archive generation. | `rearchive first generation`; `rearchive second generation` |
| A reset commit reachable only from the reflog is preserved under `refs/reaped/<path>/<generation>/reflog/<sha>`, and its tree remains readable. | `archive reflog-only commit`; `archive reflog-only commit tree is readable` |
| A successful push is not trusted without archive read-back. | `archive that drops refs`; `archive that drops refs keeps the lane` |
| A failed `rm` is reported as an internal error, is not counted as a reap, and leaves the lane. | `rm failure exits 1`; `rm failure summary`; `rm failure still exists` |
| A change to refs, HEAD, reflogs, stash state, or worktree status after the decision snapshot prevents removal with `lane changed after snapshot; skipped`, including a commit followed by reset to the original HEAD. | `lane changed after snapshot`; `lane changed after snapshot fixture committed`; `lane reflog changed after snapshot`; `lane reflog changed after snapshot fixture committed and reset` |
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

## Red-first evidence for wave 4c

Before the production fixes, the bounded adversarial suite completed with five
failures:

```text
FAIL: grok-sandbox stale legacy lane lock inode was unlinked
FAIL: grok-sandbox recreated lane lock inode was unlinked
FAIL: lane reflog changed after snapshot missing 'lane changed after snapshot; skipped'
FAIL: lane reflog changed after snapshot should still exist
FAIL: lane reflog changed after snapshot fixture did not commit and reset
5 FAILED
```

The reflog-aware snapshot and stable materializer lock path make all five cases
GREEN. Both the existing ref/status writer and the new commit-reset writer now
use ten-second bounded polling and bounded child joins; the pytest bridge has a
30-second subprocess timeout.

## Current GREEN

Observed in the Linux 6.17.0 aarch64 sandbox (not macOS):

```text
bash scripts/vm/tests/test_reap_lane.sh          186 PASS assertions
bash scripts/vm/tests/test_install_reap_cron.sh   20 PASS assertions
python3 -m pytest scripts/vm/tests/test_vm_script_suites.py -q
2 passed
```

These counts replace the stale pre-wave figure of 119 assertions. Platform
conditional `flock` cases mean assertion counts may differ on macOS; the
coordinator's macOS Bash 3.2 run is authoritative for that platform.

## Verification

The required commands are:

```text
bash scripts/vm/tests/test_reap_lane.sh
bash scripts/vm/tests/test_install_reap_cron.sh
python3 -m pytest scripts/vm/tests/test_vm_script_suites.py -q
```
