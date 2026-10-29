#!/usr/bin/env python3
"""Check requested lane declarations and local branch freshness before dispatch.

This is a read-only, local check, not dispatch authorization. Lifecycle status is
unverified: no live database is queried and no active status is inferred. Only
explicitly terminal declarations are skipped, using the existing rule contract.
No fetch, rebase, merge or dispatch is performed. Integration refs must already
be current locally. Exit 1 means a failed check; exit 2 means unavailable input.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess


GIT_TIMEOUT = 10
TASK_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class PreflightError(Exception):
    def __init__(self, rule, message):
        super().__init__(message)
        self.rule = rule


def _git(*args):
    """Bound every Git invocation and pass only argv, never shell commands."""
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise PreflightError("git-timeout", "Git timed out; restore repository access and retry before dispatch") from exc
    except OSError as exc:
        raise PreflightError("git-unavailable", f"Cannot run Git: {exc}; restore Git and retry before dispatch") from exc


def _resolve_ref(value, *, integration=False):
    kind = "integration-ref" if integration else "branch"
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise PreflightError(f"{kind}-invalid", f"Set a valid {kind} name before dispatch (got {value!r})")
    if value.startswith("refs/"):
        refs = [value]
        allowed = ("refs/heads/", "refs/remotes/") if integration else ("refs/heads/",)
        if not value.startswith(allowed):
            raise PreflightError(f"{kind}-invalid", f"Use a branch ref for {kind}: {value!r}")
    else:
        refs = [f"refs/heads/{value}"]
        if integration:
            refs.append(f"refs/remotes/{value}")
    for ref in refs:
        valid = _git("check-ref-format", ref)
        if valid.returncode == 1:
            raise PreflightError(f"{kind}-invalid", f"Correct invalid {kind} {value!r} before dispatch")
        if valid.returncode:
            raise PreflightError("git-error", f"Cannot validate {kind}: {valid.stderr.strip()}")
        resolved = _git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        if resolved.returncode == 0:
            return resolved.stdout.strip()
        if resolved.returncode not in (1, 128):
            raise PreflightError("git-error", f"Cannot resolve {kind}: {resolved.stderr.strip()}")
    raise PreflightError(
        f"{kind}-missing", f"{kind} {value!r} is missing locally; restore or correct the ref before dispatch"
    )


def _emit(payload, as_json):
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    for row in payload["lanes"]:
        print(
            f"{row['task']} {row['lane']} {row['branch']}: {row['freshness']} "
            f"(integration {row['integration_sha']}, lane {row['lane_sha']})"
        )
    for finding in payload["findings"]:
        print(
            f"{finding['level']} {finding['task']} {finding['lane']}: "
            f"{finding['rule']}: {finding['message']}"
        )
    outcome = "PASS" if payload["ok"] else "FAIL"
    print(f"lane dispatch preflight: {outcome}; live lifecycle status unverified (declared terminal lanes skipped)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=Path("config/lane-orchestration"))
    parser.add_argument("--task-ref", action="append", required=True)
    parser.add_argument("--integration-ref", default="main")
    parser.add_argument("--json", action="store_true", help="emit a single structured report")
    args = parser.parse_args(argv)
    payload = {
        "ok": False,
        "integration_ref": args.integration_ref,
        "lifecycle_status": "unverified",
        "lanes": [],
        "findings": [],
    }
    exit_code = 0

    def finding(task, lane, rule, message, level="ERROR", code=1):
        nonlocal exit_code
        payload["findings"].append({"task": task, "lane": lane, "level": level, "rule": rule, "message": message})
        if level == "ERROR":
            exit_code = max(exit_code, code)

    try:
        import check_lane_manifest_rules as rules
    except ImportError as exc:
        finding("-", "-", "rule-checker-unavailable", f"Restore the existing rule checker before dispatch: {exc}", code=2)
        _emit(payload, args.json)
        return exit_code

    integration_sha = None
    integration_error = None
    for task in dict.fromkeys(args.task_ref):
        if not TASK_REF.fullmatch(task):
            finding(task, "-", "task-ref-invalid", "Use a task ref without path separators or options", code=2)
            continue
        path = args.manifest_dir / f"{task}.json"
        try:
            if path.resolve().parent != args.manifest_dir.resolve():
                finding(task, "-", "task-ref-invalid", "Manifest must stay inside --manifest-dir", code=2)
                continue
            if not path.is_file():
                finding(task, "-", "manifest-missing", f"Restore the requested manifest {path} before dispatch", code=2)
                continue
            # Reuse actual producer tuples (level, lane_id, rule, message).
            # Keep existing rule IDs, warnings, malformed-input and terminal rules.
            rule_findings = list(rules._manifest_findings(path))
            for level, lane_id, rule, message in rule_findings:
                finding(task, lane_id, rule, message, level)
            if any(rule == "manifest-malformed" for _, _, rule, _ in rule_findings):
                continue
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("task_ref", task) != task:
                finding(task, "-", "manifest-task-mismatch", "Correct manifest task_ref to match the requested task")
                continue
            lanes = manifest["lanes"]
        except (OSError, UnicodeError, ValueError, TypeError, RuntimeError) as exc:
            finding(task, "-", "manifest-malformed", f"Cannot check manifest {path}: {exc}; repair it before dispatch")
            continue

        for lane_id, lane in lanes.items():
            if isinstance(lane.get("terminal"), dict) or lane.get("status") in rules.TERMINAL_STATUSES:
                continue
            row = {
                "task": task,
                "lane": lane_id,
                "branch": lane.get("branch"),
                "integration_sha": None,
                "lane_sha": None,
                "freshness": "unknown",
            }
            payload["lanes"].append(row)
            try:
                if integration_sha is None and integration_error is None:
                    try:
                        repository = _git("rev-parse", "--show-toplevel")
                        if repository.returncode:
                            raise PreflightError("git-error", f"Run inside the lane repository: {repository.stderr.strip()}")
                        integration_sha = _resolve_ref(args.integration_ref, integration=True)
                    except PreflightError as exc:
                        integration_error = exc
                row["integration_sha"] = integration_sha
                if integration_error:
                    raise integration_error
                row["lane_sha"] = _resolve_ref(row["branch"])
                ancestor = _git("merge-base", "--is-ancestor", integration_sha, row["lane_sha"])
                if ancestor.returncode == 0:
                    row["freshness"] = "fresh"
                elif ancestor.returncode == 1:
                    row["freshness"] = "stale"
                    finding(
                        task, lane_id, "branch-stale",
                        f"Lane branch {row['branch']!r} lacks integration {args.integration_ref!r} "
                        f"at {integration_sha}; update the lane through the coordinator before dispatch",
                    )
                else:
                    raise PreflightError("git-error", f"Cannot check ancestry: {ancestor.stderr.strip()}")
            except PreflightError as exc:
                row["freshness"] = "missing" if exc.rule.endswith("-missing") else "invalid" if exc.rule.endswith("-invalid") else "unknown"
                finding(task, lane_id, exc.rule, str(exc))

    payload["ok"] = exit_code == 0
    _emit(payload, args.json)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
