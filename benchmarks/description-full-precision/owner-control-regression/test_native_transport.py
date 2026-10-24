"""Independent R5 transport controls. No application import or module main runs.

Baseline selection verifies the *known failure*. Unfiltered selection requires a
candidate (OWNER_CONTROL_CANDIDATE, otherwise ../owner-control/owner-custody.py).
Every behavioral probe runs in a disposable stdlib subprocess/process group.
"""

import ast
import __future__
import copy
import hashlib
import importlib
import json
import os
import operator
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
ORIGINAL = FIXTURES / "baseline/owner-custody.py"
MANIFEST_SHA = "80f7267a090a69fbe05e8a55ce6dce4f9c958290db3a9c97f1efc67cda95e7fc"
ORIGINAL_SHA = "cba8527bf94603778e78910b60b04ad9c5bad38eafa0691bb21b3435990a158f"
VIEW_SHA = "e388f8be6741710f0399176368b633ef0894f9f123e13afb8f7bdad2aa5e9939"
PATCH_SHA = "30e4e8db654a6f5af7e8291056a00640875ef0d67753d66ae93f9a0ee3a804ce"
SMALL = {
    "authority": {"highest_sequence": 261},
    "publications": {}, "loads": [], "deferred": None,
}
# Budgets are fixed independently of the candidate. The real caller gives 5s;
# the outer watchdog allows its documented 2s reap grace plus runner overhead.
NATIVE_SECONDS = 5
WATCHDOG_SECONDS = 12


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_seals():
    assert digest(FIXTURES / "manifest.json") == MANIFEST_SHA
    manifest = json.loads((FIXTURES / "manifest.json").read_bytes())
    for row in manifest["files"]:
        path = FIXTURES / row["path"]
        assert path.stat().st_size == row["bytes"], row["path"]
        assert digest(path) == row["sha256"], row["path"]
    assert digest(ORIGINAL) == ORIGINAL_SHA
    assert digest(FIXTURES / "actual-view.json") == VIEW_SHA
    assert digest(FIXTURES / "prior-r4/accepted/caller.patch") == PATCH_SHA
    assert manifest["source_family_dispatch"] == 5
    assert manifest["accepted_r4_patch"] == "prior-r4/accepted/caller.patch"
    return manifest


def candidate_path():
    path = Path(os.environ.get(
        "OWNER_CONTROL_CANDIDATE", str(HERE.parent / "owner-control/owner-custody.py")
    )).resolve()
    assert path.is_file(), "candidate missing: supply owner-control/owner-custody.py or OWNER_CONTROL_CANDIDATE"
    return path


def extract_namespace(path):
    """Compile actual function ASTs and inert globals; never execute module body.

    Helpers are retained, not replaced by a test serializer. Imports are stdlib
    allowlisted. Defaults/decorators cannot execute arbitrary module setup.
    Unsupported dependencies fail loudly instead of falling back to toy code.
    """
    tree = ast.parse(Path(path).read_bytes(), filename=str(path))
    allowed = {
        "ast", "errno", "fcntl", "hashlib", "importlib.util", "json", "os",
        "pathlib", "select", "selectors", "signal", "stat", "subprocess",
        "sys", "time", "uuid", "datetime", "tempfile", "struct", "io",
        "math", "types", "collections", "contextlib", "typing", "zlib",
    }
    ns = {"__name__": "extracted_test_subject", "__file__": str(path)}
    functions = []

    def constant(node):
        # Common inert module constants such as 4 * MAX must be read from the
        # actual source too. No calls or arbitrary expression eval is allowed.
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            pass
        if isinstance(node, ast.Name) and node.id in ns:
            value = ns[node.id]
            if type(value) in (str, bytes, int, float, bool, tuple, list, dict, set, type(None)):
                return value
        if isinstance(node, ast.BinOp):
            operations = {ast.Add: operator.add, ast.Sub: operator.sub,
                          ast.Mult: operator.mul, ast.FloorDiv: operator.floordiv,
                          ast.LShift: operator.lshift, ast.RShift: operator.rshift,
                          ast.BitOr: operator.or_, ast.BitAnd: operator.and_}
            operation = operations.get(type(node.op))
            if operation is not None:
                return operation(constant(node.left), constant(node.right))
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "pathlib" and node.attr == "Path"):
            return Path
        raise ValueError("non-inert global/default")

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name in allowed, "non-allowlisted subject import"
                module = importlib.import_module(alias.name)
                ns[alias.asname or alias.name.split(".")[0]] = (
                    module if alias.asname else importlib.import_module(alias.name.split(".")[0])
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module == "__future__":
                assert all(a.name == "annotations" for a in node.names)
                continue
            assert node.level == 0 and node.module in allowed, "non-allowlisted subject import"
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert alias.name != "*"
                ns[alias.asname or alias.name] = getattr(module, alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            try:
                literal = constant(value)
            except (ValueError, TypeError):
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    ns[target.id] = literal
        elif isinstance(node, ast.FunctionDef):
            assert not node.decorator_list, "effectful decorators are not loadable"
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                constant(default)
            functions.append(node)
    assert any(n.name == "native_job" for n in functions), "actual native_job absent"
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec",
                 flags=__future__.annotations.compiler_flag, dont_inherit=True), ns)
    return ns


def probe(path, case):
    """No inherited pytest/conftest behavior inside the worker; no fixture output."""
    verify_seals()
    with tempfile.TemporaryDirectory(prefix="owner-ipc-control-") as scratch:
        argv = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                "--worker", str(Path(path).resolve()), case, scratch]
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, cwd=scratch,
                                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        try:
            stdout, stderr = proc.communicate(timeout=WATCHDOG_SECONDS)
            assert proc.returncode == 0, (
                "isolated probe failed (subject may need safe-loader review): "
                + stderr.decode(errors="replace")[-2000:]
            )
            report = json.loads(stdout)
            assert report["source_sha256"] == digest(path)
            assert report["case"] == case
            return report
        finally:
            # Includes descendants if a broken transport returns without reaping.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()


def _assert_reaped(pids):
    assert pids, "native before(pid) identity was never retained"
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            continue
        raise AssertionError("native worker not reaped by native_job")


def _worker(path, case, scratch):
    verify_seals()
    ns = extract_namespace(path)
    native = ns["native_job"]
    full = json.loads((FIXTURES / "actual-view.json").read_bytes())
    scratch = Path(scratch)
    pids = []
    report = {"case": case, "source_sha256": digest(path)}

    class ObservedOS:
        """Observe actual fork identities without adding a before gate to reads."""

        def __getattr__(self, name):
            return getattr(os, name)

        def fork(self):
            pid = os.fork()
            if pid > 0:
                pids.append(pid)
            return pid

    ns["os"] = ObservedOS()

    def before(pid):
        assert pid != os.getpid()
        pids.append(pid)

    def outcome(status, value, expected):
        _assert_reaped(pids)
        report.update(wait_status=status, exit_code=os.waitstatus_to_exitcode(status),
                      native_reaped=True, equal=value == expected,
                      value_is_none=value is None)

    started = time.monotonic()
    if case in ("full", "small"):
        expected = full if case == "full" else SMALL
        status, value = native(lambda: expected, NATIVE_SECONDS)
        outcome(status, value, expected)
        report["encoded_input_bytes"] = len(json.dumps(expected).encode())
        for field in ("authority", "publications", "loads", "deferred"):
            report[field + "_equal"] = isinstance(value, dict) and value.get(field) == expected[field]
    elif case in ("timeout", "after_timeout", "callbacks", "before_failure",
                  "fn_failure", "serialization_failure", "after_failure", "abrupt_exit"):
        event = scratch / "events"
        admitted = scratch / "admitted"

        def effect():
            assert admitted.exists(), "fn ran before before(pid) completed"
            with event.open("a") as f:
                f.write("fn\n")
            return {"native_publish_completed": True}

        def admission(pid):
            before(pid)
            time.sleep(.03)
            assert not event.exists(), "effect preceded native identity custody"
            if case == "before_failure":
                raise RuntimeError("test admission refused")
            admitted.write_text("retained")

        def after():
            if case == "after_timeout":
                time.sleep(2)
            with event.open("a") as f:
                f.write("after\n")
            if case == "after_failure":
                raise RuntimeError("test after failed")

        def fn():
            if case == "timeout":
                time.sleep(2)
            if case == "fn_failure":
                raise RuntimeError("test function failed")
            if case == "serialization_failure":
                return object()
            if case == "abrupt_exit":
                os._exit(23)
            return effect()

        try:
            status, value = native(fn, .1 if case in ("timeout", "after_timeout") else NATIVE_SECONDS,
                                   before=admission, after=after)
        except RuntimeError as exc:
            assert case == "before_failure" and str(exc) == "test admission refused"
            _assert_reaped(pids)
            report.update(exception="admission refused", native_reaped=True)
        else:
            assert case != "before_failure", "before failure was swallowed"
            outcome(status, value, {"native_publish_completed": True})
        report["events"] = event.read_text().splitlines() if event.exists() else []
    elif case == "reconcile":
        # Real reconcile, real immutable operation format, real native transport.
        # Only view's live data access and guard's ownership decision are stubbed.
        op = "687078d8-53b6-42b5-80ed-73e470e325b0"
        root = scratch / "window"
        directory = root / "ops" / op
        directory.mkdir(parents=True, mode=0o700)
        (root / "ops").chmod(0o700)
        candidate = copy.deepcopy(next(iter(full["publications"].values())))
        records = {
            "candidate.json": candidate,
            "publication.json": candidate,
            "result.json": {"outcome": "published"},
            "writer-stopped.json": {"native_reaped": True, "native_publish_completed": True},
        }
        for name, value in records.items():
            dest = directory / name
            dest.write_text(json.dumps(value))
            dest.chmod(0o400)
        native_calls, guarded = [], []
        paths = object()

        def view(actual_paths, mode):
            assert actual_paths is paths
            # Child-local assertions execute before any payload is returned.
            assert mode == "auto"
            return full

        def delegating(fn, seconds, after=None, before=None):
            native_calls.append(seconds)
            assert after is None and before is None
            return native(fn, seconds)

        def guard(v, previous, known, actor, mode):
            guarded.append(v)
            assert previous == candidate and known == {op: candidate}
            assert actor == candidate["requested_by"] and mode == "auto"

        ns.update(view=view, native_job=delegating, guard=guard)
        wfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try:
                selected = ns["reconcile"](wfd, paths)
                report.update(selected_expected=selected == op, guard_full=guarded == [full])
            except RuntimeError as exc:
                assert str(exc) == "reconciliation read unknown"
                report["exception"] = str(exc)
        finally:
            os.close(wfd)
        _assert_reaped(pids)
        report.update(native_reaped=True, native_seconds=native_calls,
                      guard_called=bool(guarded))
    elif case in ("foreign_publication", "authority_conflict"):
        # A valid owned previous publication plus a precise hostile change.
        # This tests guard semantics after transport, not a new serializer.
        previous = copy.deepcopy(next(iter(full["publications"].values())))
        v = copy.deepcopy(full)
        v["authority"].update(highest_sequence=previous["sequence"], intents={}, rejected_sequences=[])
        v.update(publications={"/test-only/owned.json": previous}, loads=[], deferred=None)
        if case == "foreign_publication":
            foreign = dict(previous, nonce="e9586bdc-aeea-4e05-86bd-02c02b84b156", requested_by="foreign-test-actor")
            v["publications"]["/test-only/foreign.json"] = foreign
            expected_error = "foreign publication"
        else:
            publication = {k: previous[k] for k in (
                "action", "requested_at", "expires_at", "ttl_seconds", "requested_by", "sequence")}
            publication["requested_by"] = "foreign-test-actor"
            v["authority"]["intents"][previous["nonce"]] = {
                "sequence": previous["sequence"], "publication": publication}
            expected_error = "conflicting authority"
        status, value = native(lambda: v, NATIVE_SECONDS, before=before)
        outcome(status, value, v)
        assert status == 0 and value == v, "guard input changed during native transport"
        try:
            ns["guard"](value, previous, {"owned": previous}, previous["requested_by"], "auto")
        except RuntimeError as exc:
            assert str(exc) == expected_error
            report["rejected"] = expected_error
        else:
            raise AssertionError("foreign ownership change accepted")
    else:
        raise AssertionError("unknown probe case")
    report["elapsed_seconds"] = time.monotonic() - started
    print(json.dumps(report, sort_keys=True))


def assert_full_acceptance(report):
    assert report["encoded_input_bytes"] == 137715
    assert report["wait_status"] == 0, "137715-byte full actual view must survive native transport"
    assert report["equal"], "native result lost or changed actual view fields"
    assert all(report[f + "_equal"] for f in ("authority", "publications", "loads", "deferred"))
    assert report["native_reaped"]
    assert report["elapsed_seconds"] < NATIVE_SECONDS + 2


def assert_contract(path, case):
    r = probe(path, case)
    assert r["native_reaped"]
    if case == "callbacks":
        assert r["wait_status"] == 0 and r["equal"]
        assert r["events"] == ["fn", "after"]
    elif case == "before_failure":
        assert r["exception"] == "admission refused" and r["events"] == []
    elif case == "timeout":
        assert r["exit_code"] == -signal.SIGKILL and r["value_is_none"]
        assert r["events"] == [] and r["elapsed_seconds"] < 2
    elif case == "after_timeout":
        assert r["exit_code"] == -signal.SIGKILL and r["equal"]
        assert r["events"] == ["fn"] and r["elapsed_seconds"] < 2
    elif case == "after_failure":
        assert r["exit_code"] == 71 and r["equal"]
        assert r["events"] == ["fn", "after"]
    else:
        assert r["exit_code"] == (23 if case == "abrupt_exit" else 71)
        assert r["value_is_none"] and r["events"] == []


def test_baseline_sealed_inputs_and_native_callsite_inventory():
    verify_seals()
    tree = ast.parse(ORIGINAL.read_bytes())
    found = []
    for function in tree.body:
        if isinstance(function, ast.FunctionDef):
            found += [(function.name, call.lineno) for call in ast.walk(function)
                      if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                      and call.func.id == "native_job"]
    assert sorted(found) == [("guardian", 278), ("guardian", 300), ("guardian", 307), ("reconcile", 357)]
    client = ast.parse((FIXTURES / "baseline/owner-window.py").read_bytes())
    assert [n.lineno for n in ast.walk(client) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "native_job"] == [44]
    native = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "native_job")
    assert any(isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.Lt)
               and isinstance(n.comparators[0], ast.Constant) and n.comparators[0].value == 60000
               for n in ast.walk(native))


def test_baseline_actual_137715_rejected_child71_none():
    r = probe(ORIGINAL, "full")
    assert r["encoded_input_bytes"] == 137715
    assert r["exit_code"] == 71 and r["value_is_none"] and not r["equal"]
    assert r["native_reaped"]


def test_baseline_cause_removal_91_bytes_child0_equal():
    r = probe(ORIGINAL, "small")
    assert r["encoded_input_bytes"] == 91 and r["wait_status"] == 0 and r["equal"]
    assert r["native_reaped"]


def test_baseline_real_reconcile_delegates_fullview_and_rejects():
    r = probe(ORIGINAL, "reconcile")
    assert r["native_seconds"] == [5] and r["native_reaped"]
    assert r["exception"] == "reconciliation read unknown" and not r["guard_called"]


def test_baseline_original_fails_same_positive_acceptance_oracle():
    r = probe(ORIGINAL, "full")
    try:
        assert_full_acceptance(r)
    except AssertionError as exc:
        assert str(exc).startswith("137715-byte full actual view must survive native transport")
    else:
        raise AssertionError("regression oracle failed to detect original defect")


def test_baseline_before_identity_then_effect_then_after():
    assert_contract(ORIGINAL, "callbacks")


def test_baseline_before_refusal_prevents_effect_and_reaps():
    assert_contract(ORIGINAL, "before_failure")


def test_baseline_timeout_reaps_before_return():
    assert_contract(ORIGINAL, "timeout")


def test_baseline_after_timeout_retains_completion_and_reaps():
    assert_contract(ORIGINAL, "after_timeout")


def test_baseline_after_failure_retains_result_and_nonzero_status():
    assert_contract(ORIGINAL, "after_failure")


def test_baseline_function_failure_has_no_result_or_after():
    assert_contract(ORIGINAL, "fn_failure")


def test_baseline_unserializable_failure_has_no_result_or_after():
    assert_contract(ORIGINAL, "serialization_failure")


def test_baseline_abrupt_exit_is_reaped_and_not_success():
    assert_contract(ORIGINAL, "abrupt_exit")


def test_baseline_foreign_publication_is_retained_and_refused():
    assert probe(ORIGINAL, "foreign_publication")["rejected"] == "foreign publication"


def test_baseline_authority_conflict_is_retained_and_refused():
    assert probe(ORIGINAL, "authority_conflict")["rejected"] == "conflicting authority"


def test_candidate_full_actual_roundtrip_preserves_every_field():
    assert_full_acceptance(probe(candidate_path(), "full"))


def test_candidate_small_control():
    r = probe(candidate_path(), "small")
    assert r["encoded_input_bytes"] == 91 and r["wait_status"] == 0 and r["equal"]


def test_candidate_real_reconcile_delivers_full_guard_input():
    r = probe(candidate_path(), "reconcile")
    assert r["native_seconds"] == [5] and r["native_reaped"]
    assert r.get("selected_expected") and r.get("guard_full") and r["guard_called"]


def test_candidate_before_identity_then_effect_then_after():
    assert_contract(candidate_path(), "callbacks")


def test_candidate_before_refusal_prevents_effect_and_reaps():
    assert_contract(candidate_path(), "before_failure")


def test_candidate_timeout_reaps_before_return():
    assert_contract(candidate_path(), "timeout")


def test_candidate_after_timeout_retains_completion_and_reaps():
    assert_contract(candidate_path(), "after_timeout")


def test_candidate_after_failure_retains_result_and_nonzero_status():
    assert_contract(candidate_path(), "after_failure")


def test_candidate_function_failure_has_no_result_or_after():
    assert_contract(candidate_path(), "fn_failure")


def test_candidate_unserializable_failure_has_no_result_or_after():
    assert_contract(candidate_path(), "serialization_failure")


def test_candidate_abrupt_exit_is_reaped_and_not_success():
    assert_contract(candidate_path(), "abrupt_exit")


def test_candidate_foreign_publication_survives_transport_and_is_refused():
    assert probe(candidate_path(), "foreign_publication")["rejected"] == "foreign publication"


def test_candidate_authority_conflict_survives_transport_and_is_refused():
    assert probe(candidate_path(), "authority_conflict")["rejected"] == "conflicting authority"


if __name__ == "__main__":
    assert len(sys.argv) == 5 and sys.argv[1] == "--worker"
    _worker(sys.argv[2], sys.argv[3], sys.argv[4])
