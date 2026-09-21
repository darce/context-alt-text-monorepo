"""Guards for scripts/gate_ops.sh, focused on what other suites cannot reach.

test_shell_parses_under_system_bash.py already runs `bash -n` over every
tracked *.sh, but the half of this script that matters most is invisible to it:
the `reap` and `status` logic lives inside a SINGLE-QUOTED heredoc
(`<<'REMOTE_EOF'`), which the local shell never parses and never expands. A
syntax error in there ships and first appears as a broken run on the gate VM.
So the body is extracted and checked on its own here.

Everything in this file is hermetic -- the validator cases must refuse before
any ssh, and the parsing and reap cases shadow commands rather than reading a
real /proc or contacting a gate host.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "gate_ops.sh"
REMOTE_BODY_START = "<<'REMOTE_EOF'"
REMOTE_BODY_END = "\nREMOTE_EOF"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _remote_body() -> str:
    """The text the gate host executes, which no local `bash -n` ever sees."""
    text = _script_text()
    start = text.index(REMOTE_BODY_START) + len(REMOTE_BODY_START)
    end = text.index(REMOTE_BODY_END, start)
    return text[start:end]


def _run(args: list[str], host: str):
    env = os.environ.copy()
    # .invalid is reserved by RFC 2606, so an accidental guard bypass fails on
    # DNS instead of reaching a real gate host.
    env["WORKBAY_REMOTE_GATE_HOST"] = host
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(REPO_ROOT),
    )


def test_remote_heredoc_body_parses() -> None:
    proc = subprocess.run(
        ["bash", "-n"],
        input=_remote_body(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def test_remote_body_is_single_quoted_heredoc() -> None:
    # If the quotes ever come off REMOTE_EOF, every $var and $(cmd) in the body
    # expands on the OPERATOR's machine before being sent -- so `holders_of`
    # would read the laptop's processes and the reap would target pids that do
    # not exist on the gate host. Pin the quoting itself.
    assert REMOTE_BODY_START in _script_text()


@pytest.mark.parametrize(
    "hostile",
    [
        "gate@host.invalid;id",
        "gate@host.invalid'`id`'",
        "gate@host.invalid$(id)",
        "gate@host.invalid |id",
        "gate@host.invalid'",
    ],
)
def test_remote_host_metachars_refused(hostile: str) -> None:
    # The host is spliced into the single-quoted argument list that the remote
    # shell parses ('$mode' '$REMOTE_DIR' ... '$REMOTE_HOST'), not merely handed
    # to ssh as an argv element. A quote in it breaks out of those quotes, so it
    # needs validating even though ssh itself would be safe.
    proc = _run(["status"], hostile)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert "REMOTE_HOST" in proc.stderr


def test_ordinary_user_at_host_is_accepted_by_the_validator() -> None:
    # Guard against over-tightening: safe() rejects '@' and ':', so reusing it
    # here would refuse every real host. Reaching ssh (and failing on DNS)
    # proves the validator let a normal value through.
    proc = _run(["status"], "gate@gate-ops-guard-test.invalid")
    assert proc.returncode != 2 or "REMOTE_HOST" not in proc.stderr


def _starttime_of_definition() -> str:
    match = re.search(r"(?m)^starttime_of\(\).*$", _remote_body())
    assert match, "starttime_of() not found in the remote body"
    return match.group(0)


def _count_words_definition() -> str:
    match = re.search(r"(?m)^count_words\(\).*$", _remote_body())
    assert match, "count_words() not found in the remote body"
    return match.group(0)


def _reap_tail() -> str:
    body = _remote_body()
    start = body.index("    tree_sig=''")
    end = body.index("\n    ;;", start)
    return body[start:end]


# A real /proc/<pid>/stat line whose comm contains both spaces and parens.
# Field 22 (starttime) is the distinctive value; a naive `awk '{print $22}'`
# returns "2" here, because the 3-token comm shifts every later field by two.
FAKE_STAT = "1234 (py (evil) test) S 1 1 1 0 -1 4194560 100 0 0 0 5 3 0 0 20 0 2 0 987654321 0 0"
EXPECTED_STARTTIME = "987654321"
NAIVE_AWK_ANSWER = "2"


def _call_starttime_of(stat_line: str) -> str:
    # `cat` is shadowed by a shell function, which takes precedence over the
    # external binary -- so the real /proc is never read.
    program = "\n".join(
        [
            _starttime_of_definition(),
            'cat() { printf "%s\\n" "$FAKE_STAT"; }',
            "starttime_of 1234",
        ]
    )
    proc = subprocess.run(
        ["bash", "-c", program],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "FAKE_STAT": stat_line},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_starttime_survives_a_comm_containing_spaces_and_parens() -> None:
    # This is the whole reason the function strips through the last ')' instead
    # of indexing fields directly. It is load-bearing for the PID-reuse guard:
    # a start time misread as "2" never matches the value re-read after the
    # kill, so every surviving pid would be discarded as "recycled" and real
    # orphans would go unreported -- the exact failure this code exists to catch.
    assert _call_starttime_of(FAKE_STAT) == EXPECTED_STARTTIME


def test_the_naive_field_index_would_have_been_wrong() -> None:
    # Proves the case above discriminates rather than passing by luck.
    naive = subprocess.run(
        ["awk", "{print $22}"],
        input=FAKE_STAT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert naive.stdout.strip() == NAIVE_AWK_ANSWER
    assert naive.stdout.strip() != EXPECTED_STARTTIME


def _run_reap_case(scenario: str):
    program = "\n".join(
        [
            "set -u",
            "tree='101 202'",
            "holders='101'",
            "host='gate@gate-ops-guard-test.invalid'",
            "fake_time=0",
            "term_sent=0",
            "",
            _count_words_definition(),
            "holders_of() {",
            "    case \"$GATE_OPS_GUARD_SCENARIO\" in",
            "        lock_held) printf '%s\\n' 101 ;;",
            "        *) return 0 ;;",
            "    esac",
            "}",
            "starttime_of() {",
            "    case \"$GATE_OPS_GUARD_SCENARIO:$1\" in",
            "        recycled:202)",
            "            if [ \"$term_sent\" -eq 0 ]; then printf '%s\\n' old; else printf '%s\\n' new; fi",
            "            ;;",
            "        capture_order:202)",
            "            if [ \"$term_sent\" -eq 0 ]; then printf '%s\\n' before; else printf '%s\\n' after; fi",
            "            ;;",
            "        *) printf '%s\\n' fixed ;;",
            "    esac",
            "}",
            "kill() {",
            "    case \"$1\" in",
            "        -TERM) term_sent=1; return 0 ;;",
            "        -0)",
            "            case \"$GATE_OPS_GUARD_SCENARIO:$2\" in",
            "                true_orphan:202|recycled:202|capture_order:202) return 0 ;;",
            "                worker_grace:202) [ \"$fake_time\" -lt 12 ] ;;",
            "                *) return 1 ;;",
            "            esac",
            "            ;;",
            "        *) return 1 ;;",
            "    esac",
            "}",
            "ps() { return 0; }",
            "sleep() { fake_time=$((fake_time + $1)); }",
            _reap_tail(),
        ]
    )
    return subprocess.run(
        ["bash", "-c", program],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
        env={**os.environ, "GATE_OPS_GUARD_SCENARIO": scenario},
    )


def test_true_orphan_surviving_the_ceiling_exits_three_and_is_actionable() -> None:
    proc = _run_reap_case("true_orphan")
    assert proc.returncode == 3, (proc.returncode, proc.stdout, proc.stderr)
    elapsed = re.search(r"orphans: 1 process\(es\) still alive (\d+)s after SIGTERM", proc.stdout)
    assert elapsed, proc.stdout
    assert int(elapsed.group(1)) >= 20
    assert "ssh gate@gate-ops-guard-test.invalid kill -TERM 202" in proc.stdout


def test_recycled_pid_is_not_reported_or_remediated() -> None:
    proc = _run_reap_case("recycled")
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "orphans: none - whole run tree is gone" in proc.stdout
    assert "kill -TERM 202" not in proc.stdout


def test_no_survivors_exits_zero() -> None:
    proc = _run_reap_case("no_survivors")
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "orphans: none - whole run tree is gone" in proc.stdout


def test_lock_still_held_wins_over_orphan_reporting() -> None:
    proc = _run_reap_case("lock_held")
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert "lock: STILL HELD by 101" in proc.stdout
    assert "lock: RELEASED" not in proc.stdout
    assert "kill -TERM 202" not in proc.stdout


def test_worker_exiting_during_execnet_grace_window_is_not_an_orphan() -> None:
    # The worker is alive at fake T+5 but gone at fake T+12. The old one-shot
    # sleep reported it as an orphan; the convergence poll must wait it out.
    proc = _run_reap_case("worker_grace")
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "orphans: none - whole run tree is gone" in proc.stdout


def test_tree_signature_is_captured_before_kill() -> None:
    # starttime_of changes when SIGTERM is sent. Capturing after the kill would
    # make the later value match and incorrectly report pid 202 as an orphan.
    proc = _run_reap_case("capture_order")
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "orphans: none - whole run tree is gone" in proc.stdout
    assert "kill -TERM 202" not in proc.stdout


def test_host_is_passed_through_to_the_remote_shell() -> None:
    # The remediation line above can only interpolate a host the remote shell
    # actually received. The heredoc is single-quoted, so it cannot inherit one.
    text = _script_text()
    assert "'$REMOTE_HOST'" in text
    assert re.search(r'(?m)^mode="\$1".*host="\$6"', _remote_body())
