#!/usr/bin/env python3
"""Run the APP-1 portal evaluation groups and record bounded evidence.

The APP-1 manifest is deliberately local data rather than a WorkBay registry
entry.  This runner keeps the execution contract small and explicit:

* validate the whole manifest before starting a child process;
* run each selected group in its own bounded pytest subprocess;
* remove the selected group's old artifacts before pytest starts; and
* append one JSONL record that is sufficient to identify the exact run.

The child output is redirected to a per-group log file.  Only a fixed-size
tail is read back into the evidence record, so a noisy or hostile test cannot
grow the runner's memory without bound.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parent.parent

GROUP_TIMEOUT_SECONDS = 30 * 60
GIT_TIMEOUT_SECONDS = 10
CAPTURED_TAIL_BYTES = 64 * 1024
TIMEOUT_EXIT_STATUS = 124
COMMAND_NOT_FOUND_EXIT_STATUS = 127

_GROUP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "version",
        "suite_id",
        "owner",
        "description",
        "command",
        "threshold",
        "evidence_sink",
        "tags",
        "cases",
        "release_gates",
    }
)
_REQUIRED_THRESHOLD_KEYS = frozenset({"kind", "max_failures", "max_skipped"})
_REQUIRED_CASE_KEYS = frozenset({"id", "group", "criterion", "status"})
_REQUIRED_RELEASE_GATES = ("beta", "expansion", "paid")
_GATE_ENV_KEYS = frozenset({"CI", "GITHUB_ACTIONS", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"})
_PYTEST_FILTER_ENV_KEYS = frozenset({"PYTEST_ADDOPTS", "PYTEST_PLUGINS"})
_SENSITIVE_ENV_PARTS = ("SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", "API_KEY")


class ManifestValidationError(ValueError):
    """The manifest is not structurally valid for this runner."""


class EvalRunnerError(RuntimeError):
    """The runner could not prepare or record an evaluation run."""


@dataclass(frozen=True, slots=True)
class ManifestCase:
    """One executable or evidence-only case declared by the manifest."""

    case_id: str
    group: str
    criterion: str
    status: str
    test: str | None
    artifact: str | None
    additional_evidence_required: bool


@dataclass(frozen=True, slots=True)
class EvalManifest:
    """Validated execution fields from an APP-1 manifest."""

    path: Path
    version: int
    suite_id: str
    owner: str
    description: str
    command: str
    threshold: dict[str, Any]
    evidence_sink: str
    tags: tuple[str, ...]
    cases: tuple[ManifestCase, ...]
    release_gates: dict[str, Any]

    @property
    def groups(self) -> dict[str, tuple[ManifestCase, ...]]:
        grouped: dict[str, list[ManifestCase]] = {}
        for case in self.cases:
            grouped.setdefault(case.group, []).append(case)
        return {name: tuple(cases) for name, cases in grouped.items()}


@dataclass(frozen=True, slots=True)
class JunitCounts:
    """Counts derived from testcase elements in one JUnit report."""

    report_found: bool
    case_count: int
    pass_count: int
    fail_count: int
    skip_count: int
    error_count: int
    failure_element_count: int
    passed_testcases: frozenset[tuple[str, str]] = frozenset()
    report_error: str | None = None


CommandRunner = Callable[..., Any]


def _manifest_error(path: str, message: str) -> ManifestValidationError:
    return ManifestValidationError(f"manifest {path}: {message}")


def _require_mapping(value: object, *, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _manifest_error(path, "must be an object")
    return dict(value)


def _require_nonempty_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _manifest_error(path, "must be a non-empty string")
    return value


def _require_nonnegative_int(value: object, *, path: str) -> int:
    if type(value) is not int or value < 0:  # bool is intentionally not an int here.
        raise _manifest_error(path, "must be a non-negative integer")
    return value


def _validate_release_gates(
    value: object,
    *,
    manifest_path: str,
    known_case_ids: set[str],
) -> dict[str, Any]:
    gates = _require_mapping(value, path=f"{manifest_path}.release_gates")
    for gate_name in _REQUIRED_RELEASE_GATES:
        gate_path = f"{manifest_path}.release_gates.{gate_name}"
        if gate_name not in gates:
            raise _manifest_error(gate_path, "missing required key")
        gate = _require_mapping(gates[gate_name], path=gate_path)
        required_cases = gate.get("required_cases")
        if not isinstance(required_cases, list):
            raise _manifest_error(f"{gate_path}.required_cases", "must be an array")
        if not required_cases:
            raise _manifest_error(f"{gate_path}.required_cases", "must not be empty")
        for index, case_id in enumerate(required_cases):
            case_id = _require_nonempty_string(
                case_id,
                path=f"{gate_path}.required_cases[{index}]",
            )
            if case_id not in known_case_ids:
                raise _manifest_error(
                    f"{gate_path}.required_cases[{index}]",
                    f"references unknown case {case_id!r}",
                )
        for boolean_key in (
            "live_payments_enabled",
            "require_nonempty_fresh_results",
            "require_sandbox_and_operational_evidence",
            "requires_explicit_live_charge_authorization",
        ):
            if boolean_key in gate and type(gate[boolean_key]) is not bool:
                raise _manifest_error(
                    f"{gate_path}.{boolean_key}",
                    "must be a boolean",
                )
        for integer_key in (
            "proposed_minimum_attempts",
            "proposed_unassisted_activations",
            "proposed_repeat_day_users",
            "observation_window_days",
            "observed_sessions",
        ):
            if integer_key in gate:
                _require_nonnegative_int(gate[integer_key], path=f"{gate_path}.{integer_key}")
    return gates


def load_manifest(path: str | Path) -> EvalManifest:
    """Read and structurally validate an APP-1 manifest.

    Validation intentionally happens before group selection or any subprocess
    invocation.  A missing or malformed key therefore cannot turn into an
    empty, apparently successful run.
    """

    manifest_path = Path(path).expanduser().resolve()
    try:
        raw_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _manifest_error(str(manifest_path), f"cannot read JSON: {exc}") from exc

    raw = _require_mapping(raw_value, path=str(manifest_path))
    missing = sorted(_REQUIRED_MANIFEST_KEYS - set(raw))
    if missing:
        raise _manifest_error(str(manifest_path), f"missing required keys: {missing}")

    version = raw["version"]
    if type(version) is not int or version < 1:
        raise _manifest_error(f"{manifest_path}.version", "must be a positive integer")
    suite_id = _require_nonempty_string(raw["suite_id"], path=f"{manifest_path}.suite_id")
    owner = _require_nonempty_string(raw["owner"], path=f"{manifest_path}.owner")
    description = _require_nonempty_string(raw["description"], path=f"{manifest_path}.description")
    command = _require_nonempty_string(raw["command"], path=f"{manifest_path}.command")
    try:
        command_parts = shlex.split(command)
    except ValueError as exc:
        raise _manifest_error(f"{manifest_path}.command", f"cannot parse command: {exc}") from exc
    if not command_parts:
        raise _manifest_error(f"{manifest_path}.command", "must contain an executable")
    evidence_sink = _require_nonempty_string(
        raw["evidence_sink"],
        path=f"{manifest_path}.evidence_sink",
    )

    threshold = _require_mapping(raw["threshold"], path=f"{manifest_path}.threshold")
    missing_threshold = sorted(_REQUIRED_THRESHOLD_KEYS - set(threshold))
    if missing_threshold:
        raise _manifest_error(
            f"{manifest_path}.threshold",
            f"missing required keys: {missing_threshold}",
        )
    if threshold["kind"] != "junit_counts":
        raise _manifest_error(
            f"{manifest_path}.threshold.kind",
            "must be 'junit_counts'",
        )
    _require_nonnegative_int(threshold["max_failures"], path=f"{manifest_path}.threshold.max_failures")
    _require_nonnegative_int(threshold["max_skipped"], path=f"{manifest_path}.threshold.max_skipped")

    tags_value = raw["tags"]
    if not isinstance(tags_value, list) or not tags_value:
        raise _manifest_error(f"{manifest_path}.tags", "must be a non-empty array")
    tags = tuple(
        _require_nonempty_string(tag, path=f"{manifest_path}.tags[{index}]")
        for index, tag in enumerate(tags_value)
    )

    cases_value = raw["cases"]
    if not isinstance(cases_value, list) or not cases_value:
        raise _manifest_error(f"{manifest_path}.cases", "must be a non-empty array")
    cases: list[ManifestCase] = []
    case_ids: set[str] = set()
    for index, case_value in enumerate(cases_value):
        case_path = f"{manifest_path}.cases[{index}]"
        case = _require_mapping(case_value, path=case_path)
        missing_case = sorted(_REQUIRED_CASE_KEYS - set(case))
        if missing_case:
            raise _manifest_error(case_path, f"missing required keys: {missing_case}")
        if "test" not in case and "artifact" not in case:
            raise _manifest_error(
                case_path,
                "must define an executable 'test' or an evidence-only 'artifact'",
            )
        case_id = _require_nonempty_string(case["id"], path=f"{case_path}.id")
        if case_id in case_ids:
            raise _manifest_error(f"{case_path}.id", f"duplicate case id {case_id!r}")
        case_ids.add(case_id)
        group = _require_nonempty_string(case["group"], path=f"{case_path}.group")
        if not _GROUP_NAME_RE.fullmatch(group):
            raise _manifest_error(
                f"{case_path}.group",
                "must contain only letters, numbers, '.', '_' or '-'",
            )
        criterion = _require_nonempty_string(case["criterion"], path=f"{case_path}.criterion")
        status = _require_nonempty_string(case["status"], path=f"{case_path}.status")
        test = (
            _require_nonempty_string(case["test"], path=f"{case_path}.test")
            if "test" in case
            else None
        )
        additional_evidence_required = case.get("additional_evidence_required", False)
        if type(additional_evidence_required) is not bool:
            raise _manifest_error(
                f"{case_path}.additional_evidence_required",
                "must be a boolean",
            )
        artifact = None
        if "artifact" in case:
            artifact = _require_nonempty_string(case["artifact"], path=f"{case_path}.artifact")
        cases.append(
            ManifestCase(
                case_id=case_id,
                group=group,
                criterion=criterion,
                status=status,
                test=test,
                artifact=artifact,
                additional_evidence_required=additional_evidence_required,
            )
        )

    release_gates = _validate_release_gates(
        raw["release_gates"],
        manifest_path=str(manifest_path),
        known_case_ids=case_ids,
    )
    return EvalManifest(
        path=manifest_path,
        version=version,
        suite_id=suite_id,
        owner=owner,
        description=description,
        command=command,
        threshold=threshold,
        evidence_sink=evidence_sink,
        tags=tags,
        cases=tuple(cases),
        release_gates=release_gates,
    )


def _selected_groups(manifest: EvalManifest, requested: Sequence[str] | None) -> list[str]:
    available = manifest.groups
    if not requested:
        return list(available)
    selected: list[str] = []
    for group in requested:
        if group not in available:
            raise ManifestValidationError(
                f"manifest {manifest.path}: unknown group {group!r}; "
                f"known groups: {sorted(available)}"
            )
        if group not in selected:
            selected.append(group)
    return selected


def _selected_gates(manifest: EvalManifest, requested: Sequence[str] | None) -> list[str]:
    if not requested:
        return []
    selected: list[str] = []
    for gate_name in requested:
        if gate_name not in manifest.release_gates:
            raise ManifestValidationError(
                f"manifest {manifest.path}: unknown release gate {gate_name!r}; "
                f"known gates: {sorted(manifest.release_gates)}"
            )
        if gate_name not in selected:
            selected.append(gate_name)
    return selected


def _safe_filename_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _artifact_paths(manifest: EvalManifest, out_dir: Path, group: str) -> tuple[Path, Path]:
    stem = f"{_safe_filename_component(manifest.suite_id)}--{_safe_filename_component(group)}"
    return out_dir / f"{stem}.xml", out_dir / f"{stem}.log"


def _head_sha(command_runner: CommandRunner, *, repository_root: Path) -> str:
    try:
        completed = command_runner(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvalRunnerError(f"cannot read git HEAD SHA: {exc}") from exc
    if getattr(completed, "returncode", 1) != 0:
        stderr = getattr(completed, "stderr", "") or ""
        raise EvalRunnerError(f"git rev-parse HEAD failed: {str(stderr).strip()}")
    sha = getattr(completed, "stdout", "") or ""
    if isinstance(sha, bytes):
        sha = sha.decode("utf-8", errors="replace")
    sha = str(sha).strip()
    if not _SHA_RE.fullmatch(sha):
        raise EvalRunnerError(f"git rev-parse HEAD returned an invalid SHA: {sha!r}")
    return sha


def _git_dirty_state(
    command_runner: CommandRunner,
    *,
    repository_root: Path,
) -> tuple[bool | None, list[str]]:
    try:
        completed = command_runner(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=repository_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None, []
    if getattr(completed, "returncode", None) != 0:
        return None, []
    output = getattr(completed, "stdout", None)
    if isinstance(output, bytes):
        try:
            output = output.decode("utf-8")
        except UnicodeDecodeError:
            return None, []
    if not isinstance(output, str):
        return None, []

    paths: list[str] = []
    for line in output.splitlines():
        status = line[:2]
        if (
            len(line) < 4
            or line[2] != " "
            or status == "  "
            or any(character not in " MADRCTU?" for character in status)
            or not line[3:]
        ):
            return None, []
        paths.append(line[3:])
    return bool(paths), paths[:20]


def _local_tag(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _junit_testcase_identity(node_id: str) -> tuple[str, str] | None:
    parts = node_id.split("::")
    if len(parts) < 2 or not parts[0] or not parts[-1]:
        return None
    module = parts[0].replace("/", ".")
    if module.endswith(".py"):
        module = module[:-3]
    classname = ".".join([module, *parts[1:-1]])
    return classname, parts[-1]


def _read_junit(path: Path) -> JunitCounts:
    if not path.is_file():
        return JunitCounts(
            report_found=False,
            case_count=0,
            pass_count=0,
            fail_count=0,
            skip_count=0,
            error_count=0,
            failure_element_count=0,
            report_error=f"missing JUnit report: {path}",
        )
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError, UnicodeError) as exc:
        return JunitCounts(
            report_found=True,
            case_count=0,
            pass_count=0,
            fail_count=0,
            skip_count=0,
            error_count=0,
            failure_element_count=0,
            report_error=f"cannot parse JUnit report {path}: {exc}",
        )

    testcases = [element for element in root.iter() if _local_tag(element.tag) == "testcase"]
    skip_count = 0
    error_count = 0
    failure_element_count = 0
    fail_count = 0
    passed_testcases: set[tuple[str, str]] = set()
    for testcase in testcases:
        child_tags = {_local_tag(child.tag) for child in testcase}
        if "skipped" in child_tags:
            skip_count += 1
        has_failure = "failure" in child_tags
        has_error = "error" in child_tags
        if has_failure:
            failure_element_count += 1
        if has_error:
            error_count += 1
        if has_failure or has_error:
            fail_count += 1
        if not child_tags.intersection({"failure", "error", "skipped"}):
            classname = testcase.attrib.get("classname")
            name = testcase.attrib.get("name")
            if classname and name:
                passed_testcases.add((classname, name))
    pass_count = max(0, len(testcases) - skip_count - fail_count)
    return JunitCounts(
        report_found=True,
        case_count=len(testcases),
        pass_count=pass_count,
        fail_count=fail_count,
        skip_count=skip_count,
        error_count=error_count,
        failure_element_count=failure_element_count,
        passed_testcases=frozenset(passed_testcases),
    )


def _read_capped_tail(path: Path, *, limit: int = CAPTURED_TAIL_BYTES) -> tuple[str, int, bool, str | None]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            payload = handle.read(limit)
    except OSError as exc:
        return "", 0, False, f"cannot read child log {path}: {exc}"
    return (
        payload.decode("utf-8", errors="replace"),
        len(payload),
        size > limit,
        None,
    )


def _gate_environment(environment: Mapping[str, str]) -> dict[str, str]:
    captured: dict[str, str] = {}
    for key, value in sorted(environment.items()):
        if not (key.startswith("ACX_") or key in _GATE_ENV_KEYS):
            continue
        if any(part in key.upper() for part in _SENSITIVE_ENV_PARTS):
            captured[key] = "<redacted>"
        else:
            captured[key] = value
    return captured


def _normalise_status(value: object, *, fallback: int = 1) -> int:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return fallback
    return 128 + abs(status) if status < 0 else status


def _manifest_command(command: str) -> tuple[list[str], Path, dict[str, str]]:
    """Build a safe argv from a manifest command, retaining its execution envelope."""

    parts = shlex.split(command)
    working_directory = SERVICE_ROOT
    command_environment: dict[str, str] = {}
    if len(parts) >= 4 and parts[0] == "cd" and parts[2] == "&&":
        working_directory = (REPOSITORY_ROOT / parts[1]).resolve()
        parts = parts[3:]

    while parts and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[0]):
        key, value = parts.pop(0).split("=", 1)
        command_environment[key] = value

    if len(parts) >= 2 and parts[:2] == ["uv", "run"]:
        uv_arguments = parts[:2]
        parts = parts[2:]
        options_with_values = {"--directory", "--extra", "--with", "--python", "--project"}
        while parts and parts[0].startswith("-"):
            option = parts.pop(0)
            uv_arguments.append(option)
            if option in options_with_values and parts:
                uv_arguments.append(parts.pop(0))
        if parts:
            executable = Path(parts[0]).name
            if executable in {"python", "python3"} and (
                "scripts/run_app_portal_evals.py" in parts[1:]
                or parts[1:3] == ["-m", "scripts.run_app_portal_evals"]
            ):
                parts = ["pytest"]
        parts = [*uv_arguments, *parts]
    elif parts == ["pytest"]:
        parts = [sys.executable, "-m", "pytest"]

    return parts, working_directory, command_environment


def _case_artifact_path(case: ManifestCase) -> Path | None:
    if case.artifact is None:
        return None
    artifact = Path(case.artifact).expanduser()
    if not artifact.is_absolute():
        artifact = REPOSITORY_ROOT / artifact
    return artifact.resolve()


def _artifact_is_present(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        metadata = path.stat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0


def _run_group(
    manifest: EvalManifest,
    *,
    group: str,
    cases: Sequence[ManifestCase],
    xml_path: Path,
    log_path: Path,
    environment: Mapping[str, str],
    command_runner: CommandRunner,
) -> dict[str, Any]:
    test_nodes = [case.test for case in cases if case.test is not None]
    evidence_only_group = not test_nodes and all(
        _artifact_is_present(_case_artifact_path(case))
        for case in cases
    )
    command, working_directory, command_environment = _manifest_command(manifest.command)
    command.extend(
        [
            "-q",
            *test_nodes,
            f"--junitxml={xml_path}",
        ]
    )
    subprocess_environment = {**environment, **command_environment}
    stripped_env_keys = (
        sorted(_PYTEST_FILTER_ENV_KEYS.intersection(subprocess_environment))
        if test_nodes
        else []
    )
    for key in stripped_env_keys:
        subprocess_environment.pop(key, None)
    raw_exit_status = 1
    timed_out = False
    execution_error: str | None = None
    with log_path.open("w", encoding="utf-8") as log_file:
        if not test_nodes:
            if evidence_only_group:
                raw_exit_status = 0
            else:
                raw_exit_status = 1
                execution_error = "group has no executable test cases"
        else:
            try:
                completed = command_runner(
                    command,
                    cwd=working_directory,
                    env=subprocess_environment,
                    check=False,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=GROUP_TIMEOUT_SECONDS,
                )
                raw_exit_status = int(getattr(completed, "returncode", 1))
            except subprocess.TimeoutExpired as exc:
                raw_exit_status = TIMEOUT_EXIT_STATUS
                timed_out = True
                execution_error = f"subprocess timed out after {GROUP_TIMEOUT_SECONDS}s: {exc}"
            except FileNotFoundError as exc:
                raw_exit_status = COMMAND_NOT_FOUND_EXIT_STATUS
                execution_error = f"cannot start pytest subprocess: {exc}"
            except OSError as exc:
                raw_exit_status = COMMAND_NOT_FOUND_EXIT_STATUS
                execution_error = f"cannot run pytest subprocess: {exc}"

    junit = _read_junit(xml_path)
    output_tail, output_tail_bytes, output_tail_truncated, tail_error = _read_capped_tail(log_path)
    threshold_failures = int(manifest.threshold["max_failures"])
    threshold_skipped = int(manifest.threshold["max_skipped"])
    reasons: list[str] = []
    status = _normalise_status(raw_exit_status)
    if raw_exit_status != 0:
        reasons.append(f"pytest exited with status {raw_exit_status}")
    if not junit.report_found and not evidence_only_group:
        reasons.append("JUnit report is missing")
    if junit.case_count == 0 and not evidence_only_group:
        reasons.append("group produced zero test cases")
    if junit.fail_count > threshold_failures:
        reasons.append(
            f"failure/error count {junit.fail_count} exceeds max_failures {threshold_failures}"
        )
    if junit.skip_count > threshold_skipped:
        reasons.append(f"skip count {junit.skip_count} exceeds max_skipped {threshold_skipped}")
    if junit.report_error and not evidence_only_group:
        reasons.append(junit.report_error)
    if execution_error:
        reasons.append(execution_error)
    if tail_error:
        reasons.append(tail_error)
    if reasons:
        status = max(status, 1)

    return {
        "group": group,
        "declared_case_count": len(cases),
        "case_count": junit.case_count,
        "pass_count": junit.pass_count,
        "fail_count": junit.fail_count,
        "skip_count": junit.skip_count,
        "error_count": junit.error_count,
        "failure_element_count": junit.failure_element_count,
        "subprocess_exit_status": raw_exit_status,
        "exit_status": status,
        "timed_out": timed_out,
        "junit_report_found": junit.report_found,
        "evidence_only_group": evidence_only_group,
        "passed_testcases": [
            {"classname": classname, "name": name}
            for classname, name in sorted(junit.passed_testcases)
        ],
        "stripped_env_keys": stripped_env_keys,
        "artifact_paths": [str(xml_path.resolve()), str(log_path.resolve())],
        "output_capture": {
            "path": str(log_path.resolve()),
            "tail": output_tail,
            "tail_bytes": output_tail_bytes,
            "tail_limit_bytes": CAPTURED_TAIL_BYTES,
            "tail_truncated": output_tail_truncated,
        },
        "failure_reasons": reasons,
    }


def _evidence_path(manifest: EvalManifest, *, repository_root: Path) -> Path:
    sink = Path(manifest.evidence_sink).expanduser()
    if not sink.is_absolute():
        sink = repository_root / sink
    return sink.resolve()


def _append_evidence(path: Path, record: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
    except OSError as exc:
        raise EvalRunnerError(f"cannot append evidence to {path}: {exc}") from exc


def run_evals(
    manifest_path: str | Path,
    *,
    groups: Sequence[str] | None = None,
    gates: Sequence[str] | None = None,
    out_dir: str | Path | None = None,
    live_charge_authorized_by: str | None = None,
    environment: Mapping[str, str] | None = None,
    command_runner: CommandRunner | None = None,
) -> int:
    """Run selected manifest groups and return their worst exit status."""

    manifest = load_manifest(manifest_path)
    selected = _selected_groups(manifest, groups)
    selected_gates = _selected_gates(manifest, gates)
    effective_environment = dict(os.environ if environment is None else environment)
    _, _, command_environment = _manifest_command(manifest.command)
    effective_environment.update(command_environment)
    runner = subprocess.run if command_runner is None else command_runner
    authorization = (
        live_charge_authorized_by.strip()
        if isinstance(live_charge_authorized_by, str)
        else ""
    ) or None
    artifact_dir = (
        REPOSITORY_ROOT / ".task-state" / "evals"
        if out_dir is None
        else Path(out_dir).expanduser()
    ).resolve()
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvalRunnerError(f"cannot create output directory {artifact_dir}: {exc}") from exc

    group_artifacts = {group: _artifact_paths(manifest, artifact_dir, group) for group in selected}
    for xml_path, log_path in group_artifacts.values():
        for artifact in (xml_path, log_path):
            try:
                artifact.unlink(missing_ok=True)
            except OSError as exc:
                raise EvalRunnerError(f"cannot remove prior output {artifact}: {exc}") from exc

    started_at = datetime.now(UTC)
    head_sha = _head_sha(runner, repository_root=REPOSITORY_ROOT)
    git_dirty, git_dirty_paths = _git_dirty_state(runner, repository_root=REPOSITORY_ROOT)
    group_results: list[dict[str, Any]] = []
    worst_status = 0
    available_groups = manifest.groups
    for group in selected:
        xml_path, log_path = group_artifacts[group]
        result = _run_group(
            manifest,
            group=group,
            cases=available_groups[group],
            xml_path=xml_path,
            log_path=log_path,
            environment=effective_environment,
            command_runner=runner,
        )
        group_results.append(result)
        worst_status = max(worst_status, int(result["exit_status"]))

    group_passed_testcases = {
        result["group"]: {
            (testcase["classname"], testcase["name"])
            for testcase in result["passed_testcases"]
        }
        for result in group_results
    }
    case_results: dict[str, dict[str, Any]] = {}
    release_gate_failures: list[str] = []
    cases_by_id = {case.case_id: case for case in manifest.cases}
    for case in manifest.cases:
        artifact_path = _case_artifact_path(case)
        artifact_present = _artifact_is_present(artifact_path)
        testcase_identity = (
            _junit_testcase_identity(case.test) if case.test is not None else None
        )
        test_passed = (
            testcase_identity is not None
            and testcase_identity in group_passed_testcases.get(case.group, set())
        )
        if case.test is not None:
            execution_status = "passed" if test_passed else "not_executed_or_failed"
        elif artifact_present:
            execution_status = "evidence_present"
        else:
            execution_status = "evidence_missing"
        case_results[case.case_id] = {
            "case_id": case.case_id,
            "declared_status": case.status,
            "execution_status": execution_status,
            "additional_evidence_required": case.additional_evidence_required,
            "artifact_path": str(artifact_path) if artifact_path is not None else None,
            "artifact_present": artifact_present if artifact_path is not None else None,
        }
    release_gate_results: dict[str, dict[str, Any]] = {}
    for gate_name, gate in manifest.release_gates.items():
        reasons: list[str] = []
        for case_id in gate["required_cases"]:
            case = cases_by_id[case_id]
            result = case_results[case_id]
            artifact_path = _case_artifact_path(case)
            if case.test is not None:
                if result["execution_status"] != "passed":
                    reasons.append(
                        f"release gate {gate_name!r} required case {case_id!r} "
                        "was not executed or did not pass"
                    )
                if gate.get("require_sandbox_and_operational_evidence") and case.additional_evidence_required:
                    if artifact_path is None:
                        reasons.append(
                            f"release gate {gate_name!r} required case {case_id!r} "
                            "requires additional evidence but has no artifact path"
                        )
                    elif not result["artifact_present"]:
                        reasons.append(
                            f"release gate {gate_name!r} required case {case_id!r} "
                            f"additional evidence artifact is missing, empty, or not a regular file: {artifact_path}"
                        )
                continue
            if artifact_path is None:
                reasons.append(
                    f"release gate {gate_name!r} required evidence-only case "
                    f"{case_id!r} has no artifact path"
                )
            elif not result["artifact_present"]:
                reasons.append(
                    f"release gate {gate_name!r} required evidence-only case "
                    f"{case_id!r} artifact is missing, empty, or not a regular file: {artifact_path}"
                )
        if gate.get("requires_explicit_live_charge_authorization") and authorization is None:
            reasons.append("explicit live-charge authorization not given")
        if gate_name in selected_gates and git_dirty is not False:
            if git_dirty:
                reasons.append("repository working tree is dirty")
            else:
                reasons.append("repository dirty state could not be determined")
        release_gate_results[gate_name] = {
            "status": "failed" if reasons else "passed",
            "reasons": reasons,
            "live_charge_authorized_by": authorization,
        }
        release_gate_failures.extend(reasons)
        if gate_name in selected_gates and reasons:
            worst_status = max(worst_status, 1)

    finished_at = datetime.now(UTC)
    artifact_paths = [
        artifact_path
        for result in group_results
        for artifact_path in result["artifact_paths"]
    ]
    artifact_paths.extend(
        result["artifact_path"]
        for result in case_results.values()
        if result["artifact_present"]
    )
    evidence = {
        "schema_version": 1,
        "suite_id": manifest.suite_id,
        "owner": manifest.owner,
        "manifest_path": str(manifest.path),
        "git_sha": head_sha,
        "git_dirty": git_dirty,
        "git_dirty_paths": git_dirty_paths,
        "environment": _gate_environment(effective_environment),
        "gate_environment": _gate_environment(effective_environment),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "groups": group_results,
        "case_results": list(case_results.values()),
        "release_gate_results": release_gate_results,
        "release_gate_failures": release_gate_failures,
        "artifact_paths": artifact_paths,
        "captured_output_tail_limit_bytes": CAPTURED_TAIL_BYTES,
        "runner_exit_status": worst_status,
    }
    evidence_path = _evidence_path(manifest, repository_root=REPOSITORY_ROOT)
    _append_evidence(evidence_path, evidence)
    return worst_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="APP-1 eval manifest JSON")
    parser.add_argument(
        "--group",
        action="append",
        default=None,
        help="run only this group; repeat for multiple groups (default: all)",
    )
    parser.add_argument(
        "--gate",
        action="append",
        choices=_REQUIRED_RELEASE_GATES,
        default=None,
        help="enforce only this release gate; repeat for multiple gates (default: report all)",
    )
    parser.add_argument(
        "--live-charge-authorized-by",
        default=None,
        help="operator explicitly authorizing a live charge for a paid release gate",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="directory for fresh per-group JUnit and bounded log artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    args = _build_parser().parse_args(argv)
    try:
        status = run_evals(
            args.manifest,
            groups=args.group,
            gates=args.gate,
            out_dir=args.out,
            live_charge_authorized_by=args.live_charge_authorized_by,
        )
    except (ManifestValidationError, EvalRunnerError) as exc:
        print(f"run_app_portal_evals: {exc}", file=sys.stderr)
        return 2
    if status:
        print(f"run_app_portal_evals: FAIL (exit status {status})", file=sys.stderr)
    else:
        print("run_app_portal_evals: PASS")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
