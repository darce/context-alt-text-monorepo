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
| An archive located inside the candidate is rejected and the candidate remains, including a percent-encoded `file://localhost` destination; non-local file URL authorities fail loudly. | `archive destination inside lane`; `localhost archive destination inside lane`; `non-local file URL authority` |
| Fresh sandbox markers, live leases, and held lane locks prevent both archival and removal. Destructive eligibility is evaluated while holding the lane lock, so work created at its acquisition boundary survives. | `grok-sandbox fresh marker`; `grok-sandbox live lease`; `grok-sandbox lane lock`; `grok-sandbox lock-before-eligibility race`; `grok-sandbox lock-before-eligibility writer work` |
| An unmarked dirty sandbox remains unmarked and is retained for operator review. | `grok-sandbox unmarked dirty did not create marker` |
| Markerless sandboxes are retained for operator review in dry-run and destructive modes; destructive pressured sweeps count them as unknown-freshness candidates and exit 4 when none can be reaped. | `grok-sandbox unmarked dry-run`; `grok-sandbox unmarked destructive`; `unmarked sandbox freshness alert exit 4` |
| An unmarked sandbox retains its materializer-owned lock, lease, venv, and sync-stamp siblings. For marked stale sandboxes, a replacement lock is detected before checkout removal and again before sibling cleanup. | `grok-sandbox unmarked lane lock inode retained`; `grok-sandbox unmarked lease`; `grok-sandbox unmarked venv`; `grok-sandbox unmarked sync stamp`; `grok-sandbox late lane lock`; `grok-sandbox recreated lane lock inode retained`; `grok-sandbox recreated lane lease`; `grok-sandbox recreated lane venv`; `grok-sandbox recreated lane sync stamp` |
| A non-sandbox archive candidate is retained until its newest checkout/git timestamp reaches the minimum age. | `archive recent lane`; `archive aged lane` |
| Without an archive, commits reachable only through a tag or reflog are treated as unmerged local work and retained. | `no-archive tag-only work`; `no-archive reflog-only work` |
| Branches, tag-only commits, and detached HEAD commits survive archival. | `archive reap`; `archive tag-only commit`; `detached HEAD` |
| Equal lane basenames in different roots use distinct archive namespaces. | `collision` |
| Re-materializing one path with an unrelated root commit creates a separate archive generation. | `rearchive first generation`; `rearchive second generation` |
| A reset commit reachable only from the reflog is preserved under `refs/reaped/<path>/<generation>/reflog/<sha>`, and its tree remains readable. | `archive reflog-only commit`; `archive reflog-only commit tree is readable` |
| A successful push is not trusted without archive read-back. | `archive that drops refs`; `archive that drops refs keeps the lane` |
| A failed `rm` is reported as an internal error, is not counted as a reap, and leaves the lane. | `rm failure exits 1`; `rm failure summary`; `rm failure still exists` |
| A change to refs, HEAD, reflogs, stash state, or worktree status after the decision snapshot prevents removal with `lane changed after snapshot; skipped`, including a commit followed by reset to the original HEAD. | `lane changed after snapshot`; `lane changed after snapshot fixture committed`; `lane reflog changed after snapshot`; `lane reflog changed after snapshot fixture committed and reset` |
| Successful linked-worktree removal prunes stale parent metadata in archive and non-archive modes, while a parent with a detached linked worktree is retained in either mode. | `parent worktree metadata pruned`; `non-archive parent worktree metadata pruned`; `non-archive parent of detached worktree`; `non-archive detached child survives` |
| Stale mkdir-lock recovery preserves the old owner inode, and two recoverers admit exactly one sweep. | `mkdir fallback atomically preserved stale owner`; `mkdir fallback stale recovery admits exactly one reaper` |
| Missing `df` output fails safe with a numeric 100% usage value. | `df unavailable`; `df unavailable contains df_used_pct=100` |

The second safety snapshot is the final state gate before the external intent
record and `rm`. There is still a residual race window between that snapshot
and `rm`; the implementation comment records the same limit. The test case
`lane changed after snapshot` demonstrates detection before that window and
does not claim the window is zero.

## Installer contracts

| Behavior | Existing test case name(s) |
| --- | --- |
| A fresh install deploys an executable reaper, creates a bare keep-repo, and schedules every supported root with `--archive-to`. | `fresh installs the script`; `fresh creates the keep-repo`; `fresh crontab contains --archive-to $HOME/lane-archive.git`; `fresh crontab contains --all $HOME/w3`; `fresh crontab contains --all $HOME/uxw2`; `fresh crontab contains --all $HOME/l1`; `fresh crontab contains --all $HOME/w`; `fresh crontab contains --all $HOME/lanes`; `fresh crontab contains --all $HOME/grok-sandbox` |
| Reinstalling preserves existing archive refs and replaces stale managed cron text without duplicating the marker or touching an unrelated job, including older managed blocks containing blank/comment lines. | `reinstall preserves archived refs`; `roll-forward`; `roll-forward keeps exactly one marker`; `roll-forward crontab contains /usr/bin/some-other-job`; `roll-forward with blank`; `roll-forward with blank keeps exactly one managed entry` |
| Reinstalling replaces the deployed script inode instead of overwriting it in place. | `reinstall atomically replaces the installed inode` |
| An unexpected `crontab -l` failure is reported and aborts without replacing existing jobs; only the platform no-crontab diagnostic is treated as an empty table. | `crontab read failure exits nonzero`; `crontab read failure reports diagnostic`; `crontab read failure preserves existing jobs` |

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
use ten-second bounded polling and bounded child joins. The pytest bridge uses
a 180-second subprocess timeout; the coordinator measured 23.1 seconds of
macOS wall time, so the former 30-second ceiling did not provide a reliable
stall margin.

## Red-first evidence for wave 4d

Before the production changes, the new adversarial cases failed as follows:

```text
FAIL: grok-sandbox stale legacy dry-run missing 'WOULD REAP ... (legacy, marker backfill)'
FAIL: grok-sandbox late lane lock missing 'lane lock replaced; skipped'
FAIL: grok-sandbox late lane lock lane should still exist
FAIL: grok-sandbox late lane lock lease should still exist
FAIL: grok-sandbox late lane lock venv should still exist
FAIL: grok-sandbox recreated lane lock missing 'lane lock replaced; skipped'
FAIL: grok-sandbox recreated lane lease should still exist
FAIL: grok-sandbox recreated lane venv should still exist
FAIL: grok-sandbox recreated lane sync stamp should still exist
FAIL: non-archive parent still lists the reaped worktree
FAIL: roll-forward with blank duplicated managed entry
```

The lock cases begin with no lock path and replace a locked inode at each final
deletion boundary. The fixed reaper create-opens and locks the stable path, then
checks that the path still names fd 8 both before `rm` and before sibling
cleanup.

## Red-first evidence for wave 4e

Before the production changes, the adversarial fixtures for all five findings
completed with twelve failures:

```text
FAIL: localhost archive destination inside lane missing 'archive destination is inside lane'
FAIL: localhost archive destination inside lane should still exist
FAIL: grok-sandbox lock-before-eligibility race missing 'dirty working tree'
FAIL: grok-sandbox lock-before-eligibility race should still exist
FAIL: grok-sandbox lock-before-eligibility writer work should still exist
FAIL: no-archive tag-only work missing 'unmerged local work'
FAIL: no-archive tag-only work should still exist
FAIL: no-archive reflog-only work missing 'unmerged local work'
FAIL: no-archive reflog-only work should still exist
FAIL: non-archive parent of detached worktree missing 'repo has linked worktrees'
FAIL: non-archive parent of detached worktree should still exist
FAIL: crontab read failure replaced existing jobs
```

The sandbox writer is injected exactly as fd 8 is locked; the corrected order
then observes its untracked file in the dirty-tree guard before taking the
snapshot. The non-archive cases reset HEAD to upstream while leaving the only
local commit reachable through an annotated tag or a reflog. The localhost
archive case combines authority parsing and percent decoding in the containment
boundary. The crontab fixture returns an unrelated listing error and verifies
the existing table byte-for-byte.

## Red-first evidence for wave 4f

Before the production changes, the portable no-flock and contention cases
completed with three failures:

```text
FAIL: grok-sandbox no-flock destructive expected exit 2 got 0
FAIL: grok-sandbox no-flock destructive missing 'reap-lane: flock is required for destructive sandbox sweeps'
FAIL: grok-sandbox lane lock unexpectedly contains 'cannot be verified'
```

The no-flock fixture supplies every command needed for a full dry-run except
`flock`, proving that observational sandbox sweeps still work while destructive
ones fail once at startup. Separate POSIX flock shims make the fresh-marker,
live-lease, and contention reasons deterministic regardless of whether the host
provides flock.

## Red-first evidence for wave 4g

Before the portable inode check was implemented, the fail-closed stat fixture
completed with three failures:

```text
FAIL: grok-sandbox unverifiable lane lock missing 'sandbox lane lock is held'; out=REAP SUMMARY candidates=1 reaped=1 skipped=0 ...
FAIL: grok-sandbox unverifiable lane lock should still exist
FAIL: grok-sandbox unverifiable lane lock unexpectedly created archive refs
```

The corrected lock check compares the pathname and open fd inode numbers using
the GNU/BSD `stat` fallback instead of Bash `-ef`, whose device comparison is
not valid for `/dev/fd/8` on macOS. A success-shim run of the same lane used by
the contention fixture now reaches the marker-TTL guard, proving the contention
message depends on `flock -n 8` failing. Separate fixtures verify that failed
inode lookup and pathname replacement both preserve the lane and archive no
refs.

## Red-first evidence for wave 4h

Before the production changes, the new and updated adversarial fixtures
completed with 37 failures. Representative failures covering all nine reviewer
findings were:

```text
FAIL: mixed present and missing --all roots expected exit 0 got 1
FAIL: rm failure marker should still exist
FAIL: partial rm follow-up missing 'partial reap after archive'
FAIL: grok-sandbox recreated lane lock missing summary ... reaped=1 skipped=0
FAIL: grok-sandbox recreated lane lock missing removal log
FAIL: grok-sandbox lane lock missing 'lane lock contended'
FAIL: grok-sandbox unverifiable lane lock missing 'lane lock unverifiable: could not stat open lock fd'
FAIL: non-force archive conflict missing 'archive ref exists with different tip (non-force)'
FAIL: unwritable archive missing 'archive push failed:'
FAIL: git status failure missing 'could not read git status'
FAIL: git stash failure missing 'could not read git status'
FAIL: grok-sandbox unmarked destructive should still exist
FAIL: custom remote-agent root missing 'sandbox marker has not reached TTL'
FAIL: custom remote-agent root no-flock expected exit 2 got 0
FAIL: contended sandbox freshness alert expected exit 4 got 0
```

The corrected sweep treats an absent `--all` root as a counted per-root skip
and continues through every present root, returning nonzero only when all
requested roots are absent. Before removal, the reaper records the successful
generation-scoped archive HEAD outside the candidate under
`${REAP_STATE_DIR:-$HOME/.workbay-reap}/partial`; a failed partial removal is
therefore identifiable even when `.git` and write access are gone. A lock-path
replacement after checkout removal is now a warning, does not double-count the
lane as skipped, preserves the success log, and avoids deleting siblings that
may belong to a replacement materialization.

Lock acquisition now distinguishes contention, an unverifiable open/flock/stat,
and pathname replacement. Lock refusals participate in the pressured-sweep
freshness count. Git status and stash-read failures fail closed. Marker-less
sandbox directories are always operator-owned skips, independent of mtime, and
the realpath-resolved `WORKBAY_REMOTE_AGENT_ROOT` receives the same marker,
lease, TTL, lock, and no-flock protections as the default root. On hosts without
`flock`, each gated race case prints an explicit `SKIP:` line and the suite
reports the skip count; shim-driven lock cases remain unconditional.

Archive failures retain a bounded stderr tail and separate transport and
verification failures. A same-generation divergent tip is preserved under the
immutable `refs/archive/<lane>/<generation>/superseded/<shortsha>` namespace;
the existing primary remains unchanged and reclamation proceeds only after
both tips have been read back successfully. The reaper never force-pushes over
the archive's only copy.

## Red-first evidence for wave 4i

The wave-4i regression run failed before the implementation changes and the
same named cases pass in the final shell/pytest gates:

| Finding | Red-first case(s) |
| --- | --- |
| VMREAP-RB-01 | `ref enumeration failure pressured exit nonzero`; `ref enumeration failure retains lane`; `ref enumeration failure summary` |
| VMREAP-RB-02 | `remote-agent explicit root direct`; `remote-agent explicit root all`; `remote-agent root outside HOME` |
| VMREAP-RB-03 | `unmarked sandbox freshness alert exit 4` |
| VMREAP-RB-04 | `archive network timeout`; `post-timeout sweep reacquires lock` |
| VMREAP-RB-05 | `same-generation supersession archive`; `same-generation primary archive retained`; `same-generation incoming superseded` |
| VMREAP-RB-06 | `rm failure external intent records archive ref`; `partial rm follow-up` |
| VMREAP-RB-07 | `test_reap_bridge_rejects_skips_when_flock_exists` |
| VMREAP-RB-08 | This corrected contract table and wave-4i evidence section. |
| VMREAP-RB-09 | `space HOME preserves remote root`; `space HOME preserves archive path`; `space HOME preserves root path` |

Every network-capable `ls-remote`, push, and fetch is bounded by
`REAP_GIT_NET_TIMEOUT_SEC` (120 seconds by default) when `timeout` is present;
hosts without it emit an explicit reduced-safety warning. The installed cron
entry quotes every HOME-derived token and carries an install-time
`WORKBAY_REMOTE_AGENT_ROOT` into the job environment.

## Host remediation (pending operator)

No post-fix host evidence exists yet. In particular, the earlier wrong-user
defect is not closed until these commands are run as the `gate` user on the VM:

```text
cd /path/to/context-alt-text-monorepo && bash scripts/vm/install-reap-cron.sh
ls -l "$HOME/bin/reap-lane.sh"
crontab -l
"$HOME/bin/reap-lane.sh" --archive-to "$HOME/lane-archive.git" --all "$HOME/grok-sandbox"
"$HOME/bin/reap-lane.sh" --yes --archive-to "$HOME/lane-archive.git" --all "$HOME/grok-sandbox"
tail -n 1 "$HOME/reap-lane.log"
```

Acceptance requires an executable `~/bin/reap-lane.sh` owned by `gate`, exactly
one managed entry in `gate`'s crontab naming every root, an observational
dry-run that identifies eligible stale sandboxes without mutation, and a first
destructive sweep whose `REAP SUMMARY` reports a credible candidate/reaped/
skipped split and nonzero bytes freed. Archive refs for a sampled reaped lane
must resolve in `~/lane-archive.git`; guarded lanes must remain present; a
follow-up `df -h /` must record the host-space result.

## Current GREEN

Observed in the Linux 6.17.0 aarch64 sandbox (not macOS):

```text
bash scripts/vm/tests/test_reap_lane.sh          289 PASS assertions, 0 skipped
PATH=<all host tools except flock> bash scripts/vm/tests/test_reap_lane.sh
                                                  235 PASS assertions, 6 skipped
bash scripts/vm/tests/test_install_reap_cron.sh   32 PASS assertions
python3 -m pytest scripts/vm/tests/test_vm_script_suites.py -q
3 passed
```

These counts replace the stale pre-wave figure of 119 assertions. Platform
conditional `flock` race cases now report their skip count explicitly, so a
macOS run cannot silently appear to have the same coverage; the coordinator's
macOS Bash 3.2 run remains authoritative for that platform.

`shellcheck` is not installed in this Linux sandbox, so no local shellcheck
result is claimed for wave 4i; the coordinator must run the required
`shellcheck -S warning scripts/vm/*.sh scripts/vm/tests/*.sh` gate.

## Verification

The required commands are:

```text
bash scripts/vm/tests/test_reap_lane.sh
bash scripts/vm/tests/test_install_reap_cron.sh
python3 -m pytest scripts/vm/tests/test_vm_script_suites.py -q
```
