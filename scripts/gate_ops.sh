#!/usr/bin/env bash
# Remote test-gate operations that scripts/remote_gate.sh does not cover:
# inspect the clone lock, decide hung-vs-slow, clear a wedged run, and reclaim
# the VM's /tmp. See docs/runbooks/remote-test-gate.md.
#
#   scripts/gate_ops.sh status              # read-only probe
#   scripts/gate_ops.sh reap                # dry run; CONFIRM=REAP to send SIGTERM
#   scripts/gate_ops.sh gc-tmp              # dry run; DAYS=<n> CONFIRM=GC to delete
#
# Why this exists: remote_gate.sh does `exec 9>.gate.lock`, so every descendant
# of the remote run inherits that open file description. flock is held by the
# description, not by the calling PID, so aborting the LOCAL `make check-remote`
# releases nothing -- it orphans the remote tree, which keeps holding the lock
# and makes every later run exit 75 "gate busy". The VM side must be killed
# first, by individual PID; the local tree then unwinds on its own.
set -euo pipefail

die() { echo "gate_ops: $*" >&2; exit 2; }

# Everything below is spliced into a single-quoted string that the remote shell
# evaluates, so each value is charset-checked first. Keep this exhaustive: a
# value that reaches the remote unvalidated can close the quote and inject.
safe() { case "$2" in ""|*[!A-Za-z0-9._/-]*) die "refusing $1 with unsafe or empty value" ;; esac; }

git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
repo_root="$(dirname "$git_common_dir")"
repo_slug="$(basename "$repo_root")"

_env_host="${WORKBAY_REMOTE_GATE_HOST:-}"
_env_dir="${WORKBAY_REMOTE_GATE_DIR:-}"
REMOTE_GATE_HOST="" REMOTE_GATE_DIR=""
config_file="$repo_root/.workbay/remote-gate.env"
# shellcheck disable=SC1090
[ -f "$config_file" ] && . "$config_file"

REMOTE_HOST="${_env_host:-${REMOTE_GATE_HOST:-}}"
[ -n "$REMOTE_HOST" ] || die "host not configured - set WORKBAY_REMOTE_GATE_HOST or REMOTE_GATE_HOST in .workbay/remote-gate.env"
REMOTE_DIR="${_env_dir:-${REMOTE_GATE_DIR:-src/${repo_slug}}}"
case "$REMOTE_DIR" in ""|.|/*|*..*) die "invalid REMOTE_DIR '${REMOTE_DIR}'" ;; esac
safe REMOTE_DIR "$REMOTE_DIR"

# Two CPU samples SAMPLE_GAP apart is the hung-vs-slow discriminator, read from
# /proc/<pid>/schedstat (nanoseconds on CPU). Do not replace it with a
# /proc/<pid>/stat utime+stime sum: that returned a frozen triple across three
# samples of a demonstrably healthy run, and it fails toward "deadlock" -- the
# direction that gets a live gate killed.
SAMPLE_GAP="${SAMPLE_GAP:-10}"
safe SAMPLE_GAP "$SAMPLE_GAP"
case "$SAMPLE_GAP" in *[!0-9]*) die "SAMPLE_GAP must be a positive integer" ;; esac

mode="${1:-status}"
confirm="${CONFIRM:-none}"; safe CONFIRM "$confirm"
days="${DAYS:-7}"
case "$days" in *[!0-9]*) die "DAYS must be a positive integer" ;; esac
[ "$days" -ge 1 ] || die "DAYS must be >= 1"

case "$mode" in
  status|reap|gc-tmp) ;;
  *) sed -n '2,16p' "$0" >&2; exit 2 ;;
esac

ssh -o BatchMode=yes -o ConnectTimeout=10 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=4 "$REMOTE_HOST" \
    "bash -s -- '$mode' '$REMOTE_DIR' '$SAMPLE_GAP' '$confirm' '$days'" <<'REMOTE_EOF'
set -u
mode="$1"; dir="$2"; gap="$3"; confirm="$4"; days="$5"

holders_of() { fuser .gate.lock 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true; }
cpu_ns() { cut -d' ' -f1 "/proc/$1/schedstat" 2>/dev/null || echo 0; }

# fuser names only the processes still holding fd 9: the parent chain
# (bash -> make -> sh -> uv -> pytest master). pytest-xdist workers are spawned
# WITHOUT that fd, so they never appear -- yet they are the only processes doing
# work, while every holder sits in do_wait/futex_do_wait waiting on them.
# Sampling holders alone reads ~0 CPU on a demonstrably healthy run (measured:
# master 0.43ms in 10s while a worker had burned 226 CPU-seconds) and votes
# WEDGED. Always expand to the full descendant tree before measuring.
descendants_of() {
  ps -eo pid=,ppid= | awk -v roots="$1" '
    { ppid[$1] = $2; pid[n++] = $1 }
    END {
      split(roots, r, /[ \n]+/)
      for (i in r) if (r[i] != "") keep[r[i]] = 1
      do {
        changed = 0
        for (j = 0; j < n; j++) {
          p = pid[j]
          if (!(p in keep) && (ppid[p] in keep)) { keep[p] = 1; changed = 1 }
        }
      } while (changed)
      for (p in keep) print p
    }'
}

case "$mode" in
status)
    cd "$HOME/$dir" 2>/dev/null || { echo 'gate_ops: clone dir missing'; exit 1; }
    echo "host: $(hostname)  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "head: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
    echo
    holders="$(holders_of)"
    if [ -z "$holders" ]; then
        echo 'lock: FREE - no process holds .gate.lock'
    else
        tree="$(descendants_of "$holders" | sort -n)"
        echo "lock: HELD - $(echo $holders | wc -w) holder(s) of fd 9, $(echo $tree | wc -w) process(es) in the run tree"
        ps -o pid,ppid,stat,etimes,cputimes,args -p $(echo $tree | tr ' ' ',') 2>/dev/null | cut -c1-150
        echo
        for p in $tree; do echo "$p $(cpu_ns $p)"; done > "/tmp/.gate-ops-s1.$$"
        sleep "$gap"
        echo "--- CPU delta over ${gap}s (whole tree, not just fd-9 holders) ---"
        moved=0
        for p in $tree; do
            a=$(awk -v P="$p" '$1==P{print $2}' "/tmp/.gate-ops-s1.$$"); a=${a:-0}
            d=$(( ( $(cpu_ns "$p") - a ) / 1000000 ))
            if [ "$d" -gt 0 ]; then moved=1; printf '  %s %sms\n' "$p" "$d"; fi
        done
        [ "$moved" -eq 0 ] && echo '  (no process in the tree advanced)'
        rm -f "/tmp/.gate-ops-s1.$$"
        echo
        echo '--- thread wchan (0=on CPU, poll_schedule_timeout*=timed wait, ep_poll/futex_do_wait=blocked) ---'
        # Collected first, then printed: piping the loop into head would run it
        # in a subshell and throw away timed/blocked.
        wch=$(for p in $tree; do
                  for t in /proc/$p/task/*/wchan; do
                      echo "  $p $(basename $(dirname $t)) $(cat "$t" 2>/dev/null || echo '?')"
                  done
              done)
        echo "$wch" | head -40
        timed=0
        case "$wch" in *poll_schedule_timeout*|*hrtimer*|*do_nanosleep*) timed=1 ;; esac
        echo "$wch" | grep -qE ' 0$' && timed=1
        blocked=$(echo "$wch" | grep -cE 'ep_poll|futex_do_wait|futex_wait' || true)
        echo
        # .gate.lock is excluded on purpose: the gate machinery touches it
        # itself, so leaving it in makes this tiebreak report "progress" for a
        # run that has made none.
        newest=$(find . -newermt '-10 minutes' -type f -not -path './.git/*' -not -name '.gate.lock' 2>/dev/null | head -1)
        if [ "$moved" -eq 1 ]; then
            echo 'VERDICT: RUNNING - CPU advanced between samples. Do not reap; wait.'
        elif [ "$timed" -eq 1 ]; then
            echo 'VERDICT: RUNNING (sleep-bound) - zero CPU delta but a timed wait is present. Zero delta alone is not deadlock.'
        elif [ -n "$newest" ]; then
            echo "VERDICT: RUNNING - no CPU delta, but a file changed in the last 10 min ($newest)."
        else
            echo "VERDICT: WEDGED - no CPU delta anywhere in the tree, $blocked blocked thread(s), no timed wait, no file touched in 10 min. Clear it with: make gate-reap CONFIRM=REAP"
        fi
    fi
    echo
    echo "disk: $(df -h / | tail -1 | tr -s ' ')"
    echo "/tmp: $(du -sh /tmp 2>/dev/null | cut -f1) across $(find /tmp -maxdepth 1 -user $(id -un) 2>/dev/null | wc -l) gate-owned entries"
    echo "  stale >7d: $(find /tmp -maxdepth 1 -user $(id -un) -mtime +7 2>/dev/null | wc -l) entries"
    ;;
reap)
    cd "$HOME/$dir" 2>/dev/null || { echo 'gate_ops: clone dir missing'; exit 1; }
    holders="$(holders_of)"
    if [ -z "$holders" ]; then echo 'lock: already FREE - nothing to reap'; exit 0; fi
    tree="$(descendants_of "$holders" | sort -n)"
    echo "fd-9 holders: $(echo $holders | tr '\n' ' ')"
    ps -o pid,ppid,stat,etimes,cputimes,args -p $(echo $tree | tr ' ' ',') 2>/dev/null | cut -c1-150
    if [ "$confirm" != 'REAP' ]; then
        echo
        echo 'DRY RUN - re-run with CONFIRM=REAP to send SIGTERM to the fd-9 holders above.'
        echo 'Run make gate-status first: a RUNNING verdict means this would destroy a live suite.'
        exit 0
    fi
    # Individual PIDs only. Never kill -- -<PGID>: the tree's pgrp belongs to
    # tailscaled, so a process-group kill takes the VM off Tailscale. Only the
    # fd-9 holders are signalled; the workers exit when the master closes.
    echo "sending SIGTERM to: $(echo $holders | tr '\n' ' ')"
    for p in $holders; do kill -TERM "$p" 2>/dev/null || echo "  pid $p already gone"; done
    sleep 5
    left="$(holders_of)"
    if [ -z "$left" ]; then echo 'lock: RELEASED'; else echo "lock: STILL HELD by $(echo $left | tr '\n' ' ') (re-run; SIGKILL only if SIGTERM fails twice)"; exit 1; fi
    ;;
gc-tmp)
    me=$(id -un)
    # Top-level, gate-owned, older than DAYS, never a dotfile:
    # /tmp/.s.PGSQL.5432* is the live Postgres socket the pg suites use.
    cand=$(find /tmp -maxdepth 1 -user "$me" -mtime +"$days" -not -name '.*' -not -path /tmp 2>/dev/null)
    [ -n "$cand" ] || { echo "gc-tmp: nothing older than ${days}d"; exit 0; }
    n=$(echo "$cand" | wc -l)
    echo "gc-tmp: $n gate-owned /tmp entries older than ${days}d"
    echo "$cand" | head -10 | sed 's/^/  /'
    [ "$n" -gt 10 ] && echo "  ... and $((n - 10)) more"
    echo "reclaimable: $(echo "$cand" | tr '\n' '\0' | du -sch --files0-from=- 2>/dev/null | tail -1 | cut -f1)"
    if [ "$confirm" != 'GC' ]; then
        echo
        echo 'DRY RUN - re-run with CONFIRM=GC to delete.'
        exit 0
    fi
    echo "$cand" | while IFS= read -r d; do
        [ -n "$d" ] || continue
        if fuser -s "$d" 2>/dev/null; then echo "  skip (in use): $d"; continue; fi
        # pytest leaves garbage-* dirs it could not remove itself (a test chmods
        # a dir unreadable, so rm_rf raises ENOTEMPTY); restore the write bit
        # first or this repeats the same failure.
        chmod -R u+rwX "$d" 2>/dev/null || true
        rm -rf -- "$d" 2>/dev/null || echo "  failed: $d"
    done
    echo "gc-tmp: done - /tmp now $(du -sh /tmp 2>/dev/null | cut -f1), disk $(df -h / | tail -1 | tr -s ' ' | cut -d' ' -f5)"
    ;;
esac
REMOTE_EOF
