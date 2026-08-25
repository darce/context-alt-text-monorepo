# W3G-01 lane G — guarded VM lane-clone reaper

## What
`scripts/vm/reap-lane.sh`: dry-run by default; `--yes` `rm -rf`s a clone only if all 7 guards pass (git dir, `$HOME` + `*/w3|uxw2|l1/*` allowlist, `git fetch origin main` or `REAP_UPSTREAM=<url>#<ref>`, every local branch + detached HEAD is ancestor of FETCH_HEAD, porcelain dirty only in ignorable set, stash empty-or-ignorable). SKIPs are exit 0.

`scripts/vm/install-reap-cron.sh`: copies script to `$HOME/bin/reap-lane.sh`, idempotent crontab `# acx-reap-lane` / `17 6 * * 1 $HOME/bin/reap-lane.sh --yes --all $HOME/w3 >> $HOME/reap-lane.log 2>&1`.

## RED
Command: `bash scripts/vm/tests/test_reap_lane.sh`

```
FAIL: missing /home/ubuntu/w3/integration/scripts/vm/reap-lane.sh
```

Exit 1. Commit `029513ae` `test(vm): W3G-01 RED reap-lane guard suite`.

## GREEN
Command: `bash scripts/vm/tests/test_reap_lane.sh`

```
PASS: d ignorable stash --yes deleted
PASS: e allowlist exit 0
PASS: e allowlist contains SKIP
PASS: e allowlist contains not under allowlisted lane root
PASS: e allowlist --yes still exists
PASS: g1 not-git exit 0
PASS: g1 not-git contains SKIP
PASS: g1 not-git contains not a git directory
PASS: g1 not-git --yes still exists
PASS: g3 no-origin exit 0
PASS: g3 no-origin contains SKIP
PASS: g3 no-origin contains no origin remote and REAP_UPSTREAM unset
PASS: g3 no-origin --yes still exists
PASS: g5 ignorable dirty exit 0
PASS: g5 ignorable dirty contains WOULD REAP
PASS: g5 ignorable dirty dry-run still exists
PASS: g2 uxw2 exit 0
PASS: g2 uxw2 contains WOULD REAP
PASS: g2 l1 exit 0
PASS: g2 l1 contains WOULD REAP
PASS: --all exit 0
PASS: --all merged deleted
PASS: --all unmerged still exists
all cases passed
```

`bash -n scripts/vm/reap-lane.sh scripts/vm/install-reap-cron.sh` OK.

## shellcheck
`shellcheck` not installed (`command -v shellcheck` empty). Not run.
