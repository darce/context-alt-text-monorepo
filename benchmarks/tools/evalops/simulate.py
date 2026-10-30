"""Bounded offline CLI prototype: fictional cases and scripted simulated users.

Run separately from the P1 gate; this module neither imports run.py nor calls a
provider, network, shell, model, workflow engine, or production adapter. Example:
  python3 benchmarks/tools/evalops/simulate.py --demo --output /tmp/demo.json
  python3 benchmarks/tools/evalops/simulate.py --input request.json --output result.json

Request schema evalops.simulate-request.v1 requires exactly these keys:
  {"schema":"evalops.simulate-request.v1", "seed":7,
   "tuples":[["operator","update","multi_turn","recover"]],
   "budgets":{"steps":24,"retries":2,"turns":12},
   "failures":[{"tuple_id":"operator/update/multi_turn/recover",
                "action":"update","count":1}], "candidate_ids":[]}
Tuple axes are persona (novice/operator), intent (create/update/cancel),
complexity (simple/multi_turn), edge case (none/ambiguous/recover). Supported
intent/complexity/edge triples are listed in PROFILES; other known combinations
are reported as constraint rejections, separately from feasible requested IDs.
Only explicit tuples are generated, never an axis Cartesian product. Limits:
64 unique tuples, 8 candidate refs, 16 KiB request, seed uint32, 1..32 operation
steps, 0..3 retries, 1..16 visible turns per case. Failures are external fixture
inputs (1..3 failed attempts per named normal action), not user/model knowledge.

Output schema evalops.offline-simulation.v1 contains dataset pins, request and
producer hashes, cases, coverage, candidate_references, runs, and acceptance.
Cases keep private_goal separate from the bounded visible script. run_case reads
only that script; check_goal separately checks final state, visible actions and
causal transitions against the fixture goal and externally supplied failures.
The pure in-memory adapter exercises create/update/retry/recover/complete/cancel
on a fictional item. It is NOT real application behavior or external acceptance.
Fixture satisfaction is not independent gold, human evidence, a user quality
rate, production pass@k, or a citation/faithfulness evaluation. Usage/cost are null.
Actual production adapter and independent checker are unavailable. Future bounded
LLM users are deferred and not executed; no pretend provider is installed.

dataset-v1 at immutable source 0151411349e23b154fe4a6ec25777d70a6800ee4 is
input contract only. All 240 real operational candidates stay quarantined with
null ground truth; optional selected records are copied as unexecuted references,
never turned into scripts, expected behavior, human data or independent gold.
No answer files, journals, gold corpus, DB, or upstream canon are read or written.
JSON is strict (duplicate keys/nonfinite numbers rejected), output is bounded,
created exclusively, and never overwrites inputs. Invalid requests/custody/I/O
exit nonzero without echoing input contents. Unsatisfied fixture goals are valid
experiment results and are reported explicitly, not CLI validation errors.

Canon v0.26.2 (53 release digests verified during implementation):
[GRPH-01] Model the work as a DAG, then topological-sort (The Algorithm Design
Manual, ch. 7); [GRPH-32] An edge exists only where data moves (bootstrap,
practice label): manifest contract hashes -> protocol.version/candidate pins ->
dataset fields in report; requested tuple IDs -> cases -> traces -> fixture check.
[GRPH-31] Critical-path schedule the task DAG (The Algorithm Design Manual,
ch. 17 + Scheduling: Theory, Algorithms, and Systems, ch. 5 and section D.4):
logical independence does not grant resource admission; this prototype is serial,
launches zero inference clients and makes no timing/capacity estimate.
[GRPH-14] Record provenance as a walkable lineage graph (Building Knowledge
Graphs, ch. 8 + Mental Models, ch. 8); [DATA-14] No dual writes (Designing
Data-Intensive Applications, ch. 11): preserve refs/pins, derive outputs only.
[TEST-06] Watch it fail once / predict the failure (Modern Software Engineering,
ch. 8); [TEST-15] Prove the green can go red (The Pragmatic Programmer, ch. 9):
red API-absence test followed by state-check and retry-bound mutation checks.
[MEAS-09] Factor must be defined, observable, and decision-linked (How to Measure
Anything in Cybersecurity Risk, ch. 6 + Measuring the User Experience, section
10.6): coverage counts explicit tuples; unavailable gold never becomes zero.
[EVAL-12] Validate the judge against humans / [EVAL-13] Pin the judging protocol
(AI Engineering): no judge/gate claims; pins are custody, not calibration.
Measurement-integrity, evidence-before-commitment and falsification-disconfirmers
cards motivate the independent-of-script assertions and mutation checks. The
context-obedience card is read but inert: no generation/context scoring here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import stat
from pathlib import Path

DATASET = Path(__file__).resolve().parents[2] / "experiments/evalops/dataset-v1"
DATASET_MANIFEST_SHA256 = "0bd6c56798aec9f2637e2b2dad020f6ce09f13598673ca1401c3051b24ce5850"
SOURCE_REVISION = "0151411349e23b154fe4a6ec25777d70a6800ee4"
MAX_REQUEST_BYTES = 16_384
MAX_FILE_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 2_097_152
AXES = (
    ("novice", "operator"),
    ("create", "update", "cancel"),
    ("simple", "multi_turn"),
    ("none", "ambiguous", "recover"),
)
PROFILES = {
    ("create", "simple", "none"),
    ("create", "multi_turn", "ambiguous"),
    ("create", "multi_turn", "recover"),
    ("update", "multi_turn", "none"),
    ("update", "multi_turn", "ambiguous"),
    ("update", "multi_turn", "recover"),
    ("cancel", "multi_turn", "none"),
    ("cancel", "multi_turn", "ambiguous"),
}
NORMAL_ACTIONS = ("create", "update", "complete", "cancel")
INITIAL = {"status": "absent", "title": None, "pending": None, "resume": None}
CLARIFY = "Which fictional item should the fixture use?"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected), "invalid object keys")


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, "invalid bounded integer")


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite JSON number")

    def finite(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON number")
        return result

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


def read_bounded(path, limit):
    # Nonblocking open + descriptor check rejects FIFOs/devices without waiting
    # for a writer, and avoids a path-stat/open race. Only regular files enter.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "regular input file required")
        data = stream.read(limit + 1)
    require(len(data) <= limit, "input size limit")
    return data


def load_request(data):
    require(len(data) <= MAX_REQUEST_BYTES, "input size limit")
    value = strict_json(data)
    validate_request(value)
    return value


def validate_budgets(value):
    keys(value, ("steps", "retries", "turns"))
    for field, low, high in (("steps", 1, 32), ("retries", 0, 3), ("turns", 1, 16)):
        integer(value[field], low, high)


def validate_failures(failures):
    require(type(failures) is dict and set(failures) <= set(NORMAL_ACTIONS), "invalid failure actions")
    for count in failures.values():
        integer(count, 1, 3)


def validate_request(value):
    keys(value, ("schema", "seed", "tuples", "budgets", "failures", "candidate_ids"))
    require(value["schema"] == "evalops.simulate-request.v1", "unsupported request schema")
    integer(value["seed"], 0, 2**32 - 1)
    validate_budgets(value["budgets"])
    tuples = value["tuples"]
    require(type(tuples) is list and 1 <= len(tuples) <= 64, "invalid tuple count")
    seen, feasible = set(), set()
    for axes in tuples:
        require(type(axes) is list and len(axes) == 4, "invalid tuple axes")
        require(all(type(v) is str and v in domain for v, domain in zip(axes, AXES, strict=True)), "unknown axis value")
        identifier = "/".join(axes)
        require(identifier not in seen, "duplicate tuple")
        seen.add(identifier)
        if tuple(axes[1:]) in PROFILES:
            feasible.add(identifier)
    failures = value["failures"]
    require(type(failures) is list and len(failures) <= 64, "invalid failure count")
    seen_failures = set()
    for failure in failures:
        keys(failure, ("tuple_id", "action", "count"))
        require(
            type(failure["tuple_id"]) is str and failure["tuple_id"] in feasible,
            "failure must reference feasible requested tuple",
        )
        require(type(failure["action"]) is str and failure["action"] in NORMAL_ACTIONS, "invalid failure action")
        integer(failure["count"], 1, 3)
        pair = (failure["tuple_id"], failure["action"])
        require(pair not in seen_failures, "duplicate failure input")
        seen_failures.add(pair)
        intent = failure["tuple_id"].split("/")[1]
        planned = {"create", "cancel" if intent == "cancel" else "complete"}
        if intent == "update":
            planned.add("update")
        require(failure["action"] in planned, "failure action not in scenario")
    ids = value["candidate_ids"]
    require(type(ids) is list and len(ids) <= 8, "invalid candidate count")
    require(all(type(v) is str and 1 <= len(v) <= 96 for v in ids), "invalid candidate ID")
    require(len(set(ids)) == len(ids), "duplicate candidate ID")
    require(len(canonical(value)) <= MAX_REQUEST_BYTES, "input size limit")


def generate_cases(request):
    validate_request(request)
    cases, rejected = [], []
    for axes in sorted(request["tuples"]):
        persona, intent, complexity, edge = axes
        identifier = "/".join(axes)
        if (intent, complexity, edge) not in PROFILES:
            rejected.append({"tuple_id": identifier, "reason": "unsupported_lifecycle_combination"})
            continue
        prefix = ("Please", "Could you")[request["seed"] % 2]
        if persona == "operator":
            prefix = ("Fixture request:", "Fixture operation:")[request["seed"] % 2]
        script = []
        if edge == "ambiguous":
            script.extend(
                [
                    {"role": "user", "text": "Please change it.", "action": None, "value": None},
                    {"role": "assistant", "text": CLARIFY, "action": None, "value": None},
                ]
            )
        script.append(
            {
                "role": "user",
                "text": f"{prefix} create the fictional item Lantern.",
                "action": "create",
                "value": "Lantern",
            }
        )
        expected = ["create"]
        if intent == "update":
            script.append(
                {
                    "role": "user",
                    "text": "Rename the fictional item to Lantern revised.",
                    "action": "update",
                    "value": "Lantern revised",
                }
            )
            expected.append("update")
        final_action = "cancel" if intent == "cancel" else "complete"
        script.append(
            {
                "role": "user",
                "text": (
                    "Cancel this fixture; do not complete it."
                    if intent == "cancel"
                    else "Complete this fictional fixture item."
                ),
                "action": final_action,
                "value": None,
            }
        )
        expected.append(final_action)
        cases.append(
            {
                "case_id": f"synthetic:scripted-v1:{request['seed']}:{identifier}",
                "tuple_id": identifier,
                "dimensions": dict(zip(("persona", "intent", "complexity", "edge_case"), axes, strict=True)),
                "provenance": {
                    "kind": "synthetic_scripted_fixture",
                    "template_version": "1.0.0",
                    "seed": request["seed"],
                    "human": False,
                    "independent_gold": False,
                },
                "ground_truth": None,
                "script": script,
                "allow_recovery": edge == "recover",
                "private_goal": {
                    "status": "cancelled" if intent == "cancel" else "completed",
                    "title": "Lantern revised" if intent == "update" else "Lantern",
                    "required_actions": expected,
                    "requires_clarification": edge == "ambiguous",
                },
            }
        )
    ids = [c["tuple_id"] for c in cases]
    return {
        "cases": cases,
        "coverage": {
            "feasible_requested_tuple_ids": ids,
            "generated_tuple_ids": ids.copy(),
            "rejected_combinations": rejected,
        },
    }


def transition(state, action, value, fail):
    """Pure fixture operation; failures are supplied by the external fixture table."""
    keys(state, INITIAL)
    require(type(action) is str and action in (*NORMAL_ACTIONS, "retry", "recover"), "unknown fixture action")
    require(type(fail) is bool, "invalid failure flag")
    status = state["status"]
    allowed = {
        "create": ("absent",),
        "update": ("active",),
        "complete": ("active",),
        "cancel": ("active",),
        "retry": ("failed",),
        "recover": ("retrying",),
    }
    require(status in allowed[action], "invalid lifecycle transition")
    if action in ("create", "update"):
        require(type(value) is str and 1 <= len(value) <= 80, "invalid fixture title")
    else:
        require(value is None, "unexpected operation value")
    result = state.copy()
    if action in ("retry", "recover"):
        require(
            not fail and state["pending"] in NORMAL_ACTIONS and state["resume"] in ("absent", "active"),
            "invalid recovery state",
        )
        if action == "retry":
            result["status"] = "retrying"
        else:
            result.update(status=state["resume"], pending=None, resume=None)
    elif fail:
        result.update(status="failed", pending=action, resume=status)
    elif action in ("create", "update"):
        result.update(status="active", title=value)
    else:
        result["status"] = "cancelled" if action == "cancel" else "completed"
    return result


def run_case(case, budgets, failures):
    """Execute a bounded fixed script, without reading private_goal or scoring it."""
    validate_budgets(budgets)
    validate_failures(failures)
    remaining = failures.copy()
    state, trace = INITIAL.copy(), []
    turns = steps = retries = 0
    stop_reason = None

    def append(kind, **fields):
        trace.append({"seq": len(trace) + 1, "cause": len(trace) or None, "kind": kind, **fields})

    def turn(role, text):
        nonlocal turns, stop_reason
        if turns >= budgets["turns"]:
            stop_reason = "turn_budget"
            return None
        turns += 1
        append("turn", role=role, text=text)
        return len(trace)

    def operate(action, value, parent):
        nonlocal steps, state, stop_reason
        if steps >= budgets["steps"]:
            stop_reason = "step_budget"
            return False
        steps += 1
        failed = remaining.get(action, 0) > 0
        if failed:
            remaining[action] -= 1
        before = state.copy()
        state = transition(state, action, value, failed)
        append("action", turn=parent, action=action, value=value, success=not failed, before=before, after=state.copy())
        return not failed

    for step in case["script"]:
        parent = turn(step["role"], step["text"])
        if parent is None:
            break
        if step["action"] is None:
            continue
        success = operate(step["action"], step["value"], parent)
        while not success and stop_reason is None:
            if not case["allow_recovery"]:
                stop_reason = "action_failed"
                break
            if retries >= budgets["retries"]:
                stop_reason = "retry_budget"
                break
            retries += 1
            for action, text in (
                ("retry", "Retry the failed fixture operation."),
                ("recover", "Recover the fixture before trying again."),
            ):
                parent = turn("user", text)
                if parent is None or not operate(action, None, parent):
                    break
            if stop_reason:
                break
            parent = turn("user", "Try the same fictional operation again.")
            if parent is None:
                break
            success = operate(step["action"], step["value"], parent)
        if stop_reason:
            break
    if stop_reason is None:
        stop_reason = "cancelled" if state["status"] == "cancelled" else "script_finished"
    claim = "success" if stop_reason in ("cancelled", "script_finished") else "stopped"
    append("outcome", reason=stop_reason, script_claim=claim)
    return {
        "case_id": case["case_id"],
        "trace": trace,
        "final_state": state,
        "stop_reason": stop_reason,
        "script_claim": claim,
        "usage": None,
        "cost": None,
    }


def check_goal(goal, final_state, trace, failures):
    """Fixture oracle independent of script claims; never independent acceptance."""
    result = {
        "status": "unknown" if goal is None else "unsatisfied",
        "scope": "in_memory_fixture_only",
        "external_acceptance": None,
    }
    if goal is None:
        return result
    try:
        keys(goal, ("status", "title", "required_actions", "requires_clarification"))
        validate_failures(failures)
        require(type(trace) is list and 1 <= len(trace) <= 49, "invalid trace bound")
        state, remaining, successful = INITIAL.copy(), failures.copy(), []
        latest_user = None
        clarified = False
        for index, event in enumerate(trace, 1):
            integer(event["seq"], index, index)
            require(event["cause"] == (index - 1 or None) and type(event["cause"]) is not bool, "broken trace cause")
            kind = event["kind"]
            if kind == "turn":
                keys(event, ("seq", "cause", "kind", "role", "text"))
                require(event["role"] in ("user", "assistant") and type(event["text"]) is str, "invalid visible turn")
                if event["role"] == "user":
                    latest_user = index
                elif event["text"] == CLARIFY and not successful:
                    clarified = True
            elif kind == "action":
                keys(event, ("seq", "cause", "kind", "turn", "action", "value", "success", "before", "after"))
                require(
                    type(event["turn"]) is int and event["turn"] == latest_user == index - 1,
                    "action without preceding user turn",
                )
                action = event["action"]
                failed = remaining.get(action, 0) > 0
                if failed:
                    remaining[action] -= 1
                after = transition(state, action, event["value"], failed)
                require(
                    event["before"] == state
                    and event["after"] == after
                    and type(event["success"]) is bool
                    and event["success"] == (not failed),
                    "action contradicts fixture state or failure input",
                )
                state = after
                if not failed and action in NORMAL_ACTIONS:
                    successful.append(action)
            else:
                keys(event, ("seq", "cause", "kind", "reason", "script_claim"))
                require(kind == "outcome" and index == len(trace), "invalid outcome position")
        require(trace[-1]["kind"] == "outcome", "missing outcome")
        require(
            state == final_state
            and state["status"] == goal["status"]
            and state["title"] == goal["title"]
            and state["pending"] is None
            and state["resume"] is None,
            "fixture final state differs from goal",
        )
        require(successful == goal["required_actions"], "visible actions differ from goal")
        require(not goal["requires_clarification"] or clarified, "clarification missing")
    except (ValueError, KeyError, TypeError):
        return result
    return dict(result, status="satisfied")


def dataset_contract(base):
    """Read exact pinned contract/artifacts only; never run the candidate importer."""
    from jsonschema import Draft202012Validator

    manifest_bytes = read_bounded(base / "artifacts/manifest.json", MAX_FILE_BYTES)
    require(digest(manifest_bytes) == DATASET_MANIFEST_SHA256, "dataset manifest pin mismatch")
    manifest = strict_json(manifest_bytes)
    contracts = {}
    for name, expected in manifest["contract_files"].items():
        data = read_bounded(base / name, MAX_FILE_BYTES)
        require(digest(data) == expected, "dataset contract hash mismatch")
        if name.endswith(".json"):
            contracts[name] = strict_json(data)
    artifacts = {}
    for name, metadata in manifest["files"].items():
        data = read_bounded(base / "artifacts" / name, MAX_FILE_BYTES)
        require(len(data) == metadata["bytes"] and digest(data) == metadata["sha256"], "dataset artifact hash mismatch")
        artifacts[name] = data
    protocol, lock = contracts["protocol.json"], contracts["input-lock.json"]
    require(
        protocol["schema"] == "evalops.grouped-real-case-protocol.v1"
        and protocol["version"] == "1.0.0"
        and manifest["record_count"] == 240,
        "unsupported dataset contract",
    )
    validator = Draft202012Validator(contracts["schema.json"])
    rows = [strict_json(line) for line in artifacts["candidates.jsonl"].splitlines()]
    require(len(rows) == manifest["record_count"], "dataset row count mismatch")
    for row in rows:
        require(validator.is_valid(row), "dataset candidate schema violation")
        require(
            row["content_sha256"] == digest(canonical({k: v for k, v in row.items() if k != "content_sha256"})),
            "candidate content hash mismatch",
        )
        require(
            row["protocol_sha256"] == manifest["contract_files"]["protocol.json"]
            and row["input_lock_sha256"] == manifest["contract_files"]["input-lock.json"],
            "candidate contract pin mismatch",
        )
        require(
            row["status"] == "quarantine"
            and row["independent_label"] is None
            and row["expected_output_or_rubric"] is None,
            "candidate must remain quarantined and unlabelled",
        )
    return (
        {
            "source_revision": SOURCE_REVISION,
            "ref": "benchmarks/experiments/evalops/dataset-v1",
            "manifest_sha256": DATASET_MANIFEST_SHA256,
            "dataset_version": manifest["version"],
            "protocol_version": protocol["version"],
            "protocol_sha256": manifest["contract_files"]["protocol.json"],
            "input_lock_sha256": manifest["contract_files"]["input-lock.json"],
            "contract_files": manifest["contract_files"],
            "artifact_files": manifest["files"],
            "snapshot": lock["snapshot"],
            "canon": lock["canon"],
            "candidate_records": len(rows),
            "independent_gold_status": manifest["independent_gold"],
        },
        {row["candidate_id"]: row for row in rows},
    )


def build(request, dataset_dir=DATASET):
    generated = generate_cases(request)
    dataset, rows = dataset_contract(dataset_dir)
    require(all(identifier in rows for identifier in request["candidate_ids"]), "unknown candidate ID")
    runs = []
    for case in generated["cases"]:
        failures = {f["action"]: f["count"] for f in request["failures"] if f["tuple_id"] == case["tuple_id"]}
        result = run_case(case, request["budgets"], failures)
        result["fixture_check"] = check_goal(case["private_goal"], result["final_state"], result["trace"], failures)
        runs.append(result)
    return {
        "schema": "evalops.offline-simulation.v1",
        "dataset": dataset,
        "request": copy.deepcopy(request),
        "request_sha256": digest(canonical(request)),
        "producer": {
            "ref": "benchmarks/tools/evalops/simulate.py",
            "sha256": digest(Path(__file__).read_bytes()),
            "version": "1.0.0",
        },
        **generated,
        "runs": runs,
        "candidate_references": [
            {"candidate": rows[identifier], "ground_truth": None, "oracle": "unknown", "execution": "not_executed"}
            for identifier in sorted(request["candidate_ids"])
        ],
        "acceptance": {
            "production": None,
            "production_adapter": "unavailable",
            "independent_checker": "unavailable",
            "independent_gold": None,
        },
        "llm_users": "deferred_not_executed",
        "usage": None,
        "cost": None,
    }


def demo_request():
    return {
        "schema": "evalops.simulate-request.v1",
        "seed": 7,
        "tuples": [
            ["novice", "create", "simple", "none"],
            ["operator", "update", "multi_turn", "recover"],
            ["novice", "cancel", "multi_turn", "ambiguous"],
            ["novice", "update", "simple", "ambiguous"],
        ],
        "budgets": {"steps": 24, "retries": 2, "turns": 12},
        "failures": [{"tuple_id": "operator/update/multi_turn/recover", "action": "update", "count": 1}],
        "candidate_ids": [],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="strict bounded request JSON (schema above)")
    source.add_argument(
        "--demo", action="store_true", help="fictional scripted fixtures, including recovery/cancellation"
    )
    parser.add_argument("--output", required=True, type=Path, help="new JSON file, exclusive creation; no overwrite")
    args = parser.parse_args(argv)
    try:
        request = demo_request() if args.demo else load_request(read_bounded(args.input, MAX_REQUEST_BYTES))
        report = build(request)
        data = canonical(report) + b"\n"
        require(len(data) <= MAX_OUTPUT_BYTES, "output size limit")
        with args.output.open("xb") as stream:
            stream.write(data)
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        parser.exit(1, "Offline prototype failed: check strict request, pinned dataset, and new output path.\n")
    print("Wrote offline scripted fixture results; real deployment acceptance unavailable.")


if __name__ == "__main__":
    main()
