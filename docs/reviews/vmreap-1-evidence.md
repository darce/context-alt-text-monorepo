# VMREAP-1 — offload lane sandboxes were invisible to the reaper

HEAD (pre-edit): `746c3227c84a8fd624c3e80448afaf621a88e07d`

## DEFECT

Two independent gaps, both confirmed on the live VM before any edit.

**(1) Wrong roots.** `scripts/vm/reap-lane.sh` defaulted to
`REAP_LANE_ROOTS="w3 uxw2 l1 w lanes"` and `scripts/vm/install-reap-cron.sh` swept
`'$HOME/w3 $HOME/uxw2 $HOME/l1 $HOME/w $HOME/lanes'`. Neither named `grok-sandbox`:

```
$ grep -rn "grok-sandbox" scripts/vm/ Makefile.d/
(no matches)
```

Every offload lane the orchestrator creates lands at
`/home/gate/grok-sandbox/feature-<branch>-<hash>`.

**(2) Wrong user.** `install-reap-cron.sh` installs the crontab of the invoking user and
`process_one` refuses any path outside `$HOME`, so a cron installed as `ubuntu` can
never reach lanes owned by `gate`.

## RECON (operator-run, verbatim)

```
$ ssh gate@acx-backend 'du -sh ~/grok-sandbox; ls -d ~/grok-sandbox/*/ | wc -l; ls -l ~/bin/reap-lane.sh; ls -d ~/lane-archive.git; df -h /'
60G     /home/gate/grok-sandbox
197
ls: cannot access '/home/gate/bin/reap-lane.sh': No such file or directory
ls: cannot access '/home/gate/lane-archive.git': No such file or directory
/dev/sda1       193G  177G   17G  92% /
```

60G across 197 lane dirs, and `gate` has neither the reaper nor the archive repo.
This is the RES-07 failure VMDISK-1 was built to fix, recurring one root later — the
five listed roots had stopped growing while the unlisted one absorbed everything.

## RED

```
$ bash scripts/vm/tests/test_reap_lane.sh
FAIL: g2 grok-sandbox missing 'WOULD REAP'; out=SKIP \
  /private/var/.../reap-lane-test.cbrQXn/grok-sandbox/feature-vmreap-1-abc1234: \
  not under allowlisted lane root

$ bash scripts/vm/tests/test_install_reap_cron.sh
FAIL: fresh crontab missing '--all $HOME/grok-sandbox '
```

The second reap-lane case (`grok-sandbox-old/lane-x` → still SKIPPED) passed while RED and
must stay passing: it pins the segment-exact matcher, so widening the roots may not come from
loosening `is_under_lane_root` into a prefix match.

## FIX

- `scripts/vm/reap-lane.sh`: `REAP_LANE_ROOTS` default gains `grok-sandbox`; the [RES-07]
  comment now records the recurrence.
- `scripts/vm/install-reap-cron.sh`: `roots` gains `$HOME/grok-sandbox`, plus a comment
  stating the per-user boundary — run the installer as **each** user that owns lane roots.
- `scripts/vm/tests/test_install_reap_cron.sh`: `grok-sandbox` added to the asserted loop.

No change to `is_under_lane_root`, no relaxation of the `$HOME` guard. Reaching `gate`'s
sandboxes is an operator act (run as `gate`), not a widened blast radius.

## GREEN

```
$ make test-vm-scripts
119 PASS assertions across 2 suites
all cases passed

$ shellcheck scripts/vm/reap-lane.sh scripts/vm/install-reap-cron.sh \
    scripts/vm/tests/test_reap_lane.sh scripts/vm/tests/test_install_reap_cron.sh
(clean)
```

`make test-vm-scripts` is reached from `make test-scripts` (root Makefile) and is
run locally before merge. `make check-remote` does NOT run it by default: the
remote gate's default lane is the description-service `test` target
(`scripts/remote_gate.sh` DEFAULT_TARGETS); pass
`make check-remote TARGETS="test-vm-scripts"` to exercise it on the gate host.
The guards are deliberately pytest-free (Makefile `test-vm-scripts` comment)
because the gate host's root venv carries no pytest; the pytest bridge
`scripts/vm/tests/test_vm_script_suites.py` is additive for remote lanes only.

## STILL OPERATOR-HELD

The code fix does not reclaim a byte on its own. As `gate`:

```
mkdir -p ~/bin
git init --bare ~/lane-archive.git
# copy the FIXED scripts/vm/reap-lane.sh to ~/bin/reap-lane.sh, chmod +x
~/bin/reap-lane.sh --archive-to ~/lane-archive.git --all ~/grok-sandbox     # dry run first
~/bin/reap-lane.sh --yes --archive-to ~/lane-archive.git --all ~/grok-sandbox
bash scripts/vm/install-reap-cron.sh                                        # durable cron, as gate
```

`--archive-to` is **non-negotiable**. VMDISK-1 decision 6441: widening the roots alone
reclaimed nothing — 0 of 74 lanes were reapable, because squash/rebase merges mean lane
commits are never ancestors of `main` and most lanes' `origin` points at a sibling lane.
`--archive-to` pushes all refs to the keep-repo and verifies via `git ls-remote` read-back
before removing the checkout. VMDISK-1 decision 6443 is the precedent: the operator-run
`--yes` sweep took 182G→151G, 95%→79%.

## VERDICT

`GREEN — both roots widened, per-user boundary documented, 119 assertions passing; sweep operator-held`
