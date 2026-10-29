#!/usr/bin/env python3
"""Check, land and retire exact declared lane deltas; no lifecycle or review gates."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile


class Refusal(RuntimeError):
    """An unsafe, stale or incomplete operator contract."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def obj(value, required, optional=()):
    require(isinstance(value, dict), "expected a JSON object")
    require(set(required) <= value.keys(), f"missing fields: {set(required) - value.keys()}")
    require(not value.keys() - set(required) - set(optional), "unknown spec fields")


def text(value):
    require(isinstance(value, str) and bool(value) and "\0" not in value, "expected nonempty string")
    return value


def relative(value):
    value = text(value)
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and path.parts
        and all(part not in {"..", ".git"} for part in path.parts)
        and path.as_posix() == value
        and "\\" not in value,
        f"unsafe relative path: {value!r}",
    )
    return value


def plain_path(path):
    """Reject symlinks in the path itself and every existing parent."""
    require(path.is_absolute() and ".." not in path.parts, f"expected absolute path: {path}")
    for part in [*reversed(path.parents), path]:
        require(not part.is_symlink(), f"symlink path: {part}")
    return path


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value), "use full immutable SHAs")
    return value


def branch(value):
    value = text(value)
    require(not value.startswith("-") and not value.startswith("refs/"), "use a local branch name")
    return value


def load_spec(path, task):
    plain_path(path.absolute())
    spec = json.loads(path.read_text(encoding="utf-8"))
    obj(spec, {"task", "integration", "receipt", "lanes"}, {"expected_tree", "cleanup"})
    require(text(spec["task"]) == task and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", task), "wrong task")
    integration = spec["integration"]
    obj(integration, {"checkout", "branch", "base"})
    root = plain_path(Path(text(integration["checkout"])))
    branch(integration["branch"])
    sha(integration["base"])
    receipt = relative(spec["receipt"])
    require(receipt.startswith(f".task-state/{task}/"), "receipt must be below .task-state/<task>/")
    plain_path(root / receipt)
    require(isinstance(spec["lanes"], list) and spec["lanes"], "declare at least one lane")
    ids, branches = set(), set()
    for lane in spec["lanes"]:
        obj(lane, {"id", "branch", "base", "tip", "owned_paths"})
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", text(lane["id"])), "invalid lane id")
        require(lane["id"] not in ids, "duplicate lane id")
        ids.add(lane["id"])
        branch(lane["branch"])
        require(lane["branch"] != integration["branch"] and lane["branch"] not in branches, "duplicate branch")
        branches.add(lane["branch"])
        sha(lane["base"])
        sha(lane["tip"])
        require(isinstance(lane["owned_paths"], list) and lane["owned_paths"], "declare owned_paths")
        for owned in lane["owned_paths"]:
            relative(owned)
            require(owned.split("/")[0] != ".task-state", "operator state cannot be owned by a lane")
            plain_path(root / owned)
    if "expected_tree" in spec:
        sha(spec["expected_tree"])
    if "cleanup" in spec:
        # Worktree teardown belongs to task-finish; no arbitrary filesystem or remote job deletion.
        obj(spec["cleanup"], {"branches"})
        names = spec["cleanup"]["branches"]
        require(isinstance(names, list) and len(names) == len(set(names)), "invalid cleanup branches")
        require(set(names) <= branches, "cleanup may only name declared lane branches")
    return spec, root


class Git:
    def __init__(self, root):
        self.root = root

    def run(self, *args, data=None, env=None, ok=True):
        # Inherited Git selectors must not redirect a declared checkout or its index.
        base_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        base_env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1", GIT_LITERAL_PATHSPECS="1")
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], input=data, capture_output=True,
            env={**base_env, **(env or {})}, timeout=30,
        )
        if ok:
            require(result.returncode == 0, f"git {args[0]} failed ({result.returncode}): {os.fsdecode(result.stderr).strip()}")
        return result

    def out(self, *args, **kwargs):
        return os.fsdecode(self.run(*args, **kwargs).stdout).strip()

    def tree(self, rev):
        return self.out("rev-parse", "--verify", f"{rev}^{{tree}}")

    def entries(self, rev):
        entries = {}
        for record in self.run("ls-tree", "-rz", "--full-tree", rev).stdout.split(b"\0"):
            if record:
                metadata, name = record.split(b"\t", 1)
                mode, kind, oid = metadata.decode("ascii").split()
                entries[os.fsdecode(name)] = (mode, oid)
        return entries

    def ancestor(self, older, newer):
        result = self.run("merge-base", "--is-ancestor", older, newer, ok=False)
        require(result.returncode in {0, 1}, "cannot establish ancestry")
        return result.returncode == 0

    def index_tree(self):
        # write-tree can persist cache-tree extensions even with OPTIONAL_LOCKS=0.
        # Snapshot first so validation never writes the operator's actual index.
        source = Path(self.out("rev-parse", "--path-format=absolute", "--git-path", "index"))
        with tempfile.TemporaryDirectory(prefix="land-twin-read-index-") as directory:
            snapshot = Path(directory) / "index"
            shutil.copyfile(source, snapshot)
            return self.out("write-tree", env={"GIT_INDEX_FILE": str(snapshot)})

    def visible_index(self):
        flags = self.run("ls-files", "-v", "-z").stdout.split(b"\0")
        require(not any(entry and (entry[:1].islower() or entry[:1] == b"S") for entry in flags),
                "hidden index flags (assume-unchanged/skip-worktree); inspect and clear explicitly")

    def clean(self, rev="HEAD"):
        self.visible_index()
        # Do not refresh the real index during --check.
        require(not self.run("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z").stdout,
                "dirty tracked worktree; preserve operator work")
        require(self.index_tree() == self.tree(rev), "dirty tracked index; preserve operator work")

    def idle(self):
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
            path = Path(self.out("rev-parse", "--path-format=absolute", "--git-path", name))
            require(not path.exists(), f"in-progress Git operation: {name}")


@contextmanager
def state_lock(path):
    # Optional platform capability is imported at use time; unsupported hosts fail loudly.
    import fcntl

    plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save(path, value):
    """Atomic, fsynced replacement. Keep previous attempt records inside the receipt."""
    plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_checkout(git, spec):
    require(Path(git.out("rev-parse", "--show-toplevel")) == git.root, "checkout must be the Git root")
    require(git.out("symbolic-ref", "--quiet", "HEAD") == f'refs/heads/{spec["integration"]["branch"]}',
            "wrong integration branch")
    for name in [spec["integration"]["branch"], *(lane["branch"] for lane in spec["lanes"])]:
        git.run("check-ref-format", "--branch", name)
    for rev in [spec["integration"]["base"], *(rev for lane in spec["lanes"] for rev in (lane["base"], lane["tip"]))]:
        require(git.out("rev-parse", "--verify", f"{rev}^{{commit}}") == rev, "moved or invalid base/tip")
    require(not git.out("ls-files", "--", spec["receipt"]), "receipt cannot replace a tracked file")
    require(git.run("check-ignore", "--quiet", "--", spec["receipt"], env={"GIT_LITERAL_PATHSPECS": "0"}, ok=False).returncode == 0,
            "receipt must be ignored operator state")


def compose(git, spec):
    """Each edge carries an exact tree; never diff merge-base(main, tip). [GRPH-32]"""
    current = git.entries(spec["integration"]["base"])
    steps = []
    with tempfile.TemporaryDirectory(prefix="land-twin-index-") as directory:
        env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        git.run("read-tree", spec["integration"]["base"], env=env)
        for lane in spec["lanes"]:
            require(git.ancestor(lane["base"], lane["tip"]), f'lane {lane["id"]}: base is not an ancestor of tip')
            base, tip = git.entries(lane["base"]), git.entries(lane["tip"])
            changes = {name: tip.get(name) for name in sorted(base.keys() | tip.keys()) if base.get(name) != tip.get(name)}
            for name, desired in changes.items():
                relative(name)
                plain_path(git.root / name)
                require(any(name == owner or name.startswith(owner + "/") for owner in lane["owned_paths"]),
                        f'lane {lane["id"]}: unowned path {name!r}')
                require(current.get(name) in (base.get(name), desired), f'lane {lane["id"]}: clobber at {name!r}')
                for entry in (base.get(name), desired):
                    require(entry is None or entry[0] in {"100644", "100755"}, f"unsupported symlink/submodule: {name!r}")
            # Remove old entries before adding desired entries, including directory/file replacements.
            remove = b"".join(b"0 " + b"0" * len(lane["tip"]) + b"\t" + os.fsencode(name) + b"\0" for name in changes)
            if remove:
                git.run("update-index", "-z", "--index-info", data=remove, env=env)
            add = b"".join(f"{entry[0]} {entry[1]}\t".encode() + os.fsencode(name) + b"\0"
                           for name, entry in changes.items() if entry)
            if add:
                git.run("update-index", "-z", "--index-info", data=add, env=env)
            for name, desired in changes.items():
                if desired:
                    current[name] = desired
                else:
                    current.pop(name, None)
            tree = git.out("write-tree", env=env)
            require(git.entries(tree) == current, "composed index lost blob/mode entries")
            steps.append({"lane": lane["id"], "tip": lane["tip"], "tree": tree, "paths": list(changes)})
    require("expected_tree" not in spec or spec["expected_tree"] == steps[-1]["tree"], "wrong expected composed tree")
    return steps


def check_refs(git, spec, state, cleanup=False):
    retired = {entry["branch"] for entry in state.get("cleanup_results", []) if entry.get("result") in {"deleted", "deleting"}}
    for lane in spec["lanes"]:
        result = git.run("rev-parse", "--verify", "--quiet", f'refs/heads/{lane["branch"]}', ok=False)
        if cleanup and lane["branch"] in retired and result.returncode == 1:
            continue
        require(result.returncode == 0 and os.fsdecode(result.stdout).strip() == lane["tip"],
                f'lane {lane["id"]}: moved/missing branch tip')


def check_untracked(git, paths):
    # Include ignored files: a lane must never replace an operator's ignored payload either.
    untracked = git.run("ls-files", "--others", "-z").stdout.split(b"\0")
    for raw in untracked:
        if raw:
            name = os.fsdecode(raw)
            require(not any(name == p or name.startswith(p + "/") or p.startswith(name + "/") for p in paths),
                    f"untracked write collision: {name!r}")


def message(spec, lane):
    return f'Land {spec["task"]} lane {lane["id"]}\n\nLane-tip: {lane["tip"]}\nLane-base: {lane["base"]}'


def verify_landing(git, spec, step, record, parent):
    obj(record, {"lane", "commit", "parent", "tree", "tip"})
    require(record["lane"] == step["lane"] and record["parent"] == parent
            and record["tree"] == step["tree"] and record["tip"] == step["tip"], "invalid landing receipt")
    sha(record["commit"])
    require(git.tree(record["commit"]) == step["tree"], "landing tree differs from receipt")
    parents = git.out("show", "-s", "--format=%P", record["commit"]).split()
    require(parents == ([parent] if git.ancestor(step["tip"], parent) else [parent, step["tip"]]),
            "landing does not preserve declared history")
    lane = next(lane for lane in spec["lanes"] if lane["id"] == step["lane"])
    require(git.out("show", "-s", "--format=%B", record["commit"]) == message(spec, lane), "unexpected landing message")


def validate_history(git, spec, steps, state, allow_pending):
    require(isinstance(state["landings"], list) and len(state["landings"]) <= len(steps), "invalid landing list")
    parent = spec["integration"]["base"]
    for step, record in zip(steps, state["landings"], strict=False):
        verify_landing(git, spec, step, record, parent)
        parent = record["commit"]
    git.visible_index()
    pending = state.get("pending")
    head = git.out("rev-parse", "HEAD")
    if pending:
        require(allow_pending, "partial apply: rerun --apply with the preserved receipt")
        require(len(state["landings"]) < len(steps), "unexpected pending landing")
        step = steps[len(state["landings"])]
        require(pending == {**step, "parent": parent}, "pending receipt differs from checked composition")
        if head != parent:
            # Crash after commit but before final receipt save: verify before adopting HEAD.
            record = {key: pending[key] for key in ("lane", "parent", "tree", "tip")}
            record["commit"] = head
            verify_landing(git, spec, step, record, parent)
            git.clean()
            git.idle()
            state["landings"].append(record)
            state["pending"] = None
        else:
            require(not git.run("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z").stdout,
                    "pending apply has dirty worktree; preserve work and inspect receipt")
            require(git.index_tree() in {git.tree(parent), step["tree"]}, "pending index changed; preserve work")
            merge = git.run("rev-parse", "--verify", "MERGE_HEAD", ok=False)
            require(merge.returncode != 0 or os.fsdecode(merge.stdout).strip() == step["tip"], "foreign merge in progress")
            # Other Git operations are never ours.
            for name in ("CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
                require(not Path(git.out("rev-parse", "--path-format=absolute", "--git-path", name)).exists(),
                        f"foreign operation: {name}")
        return
    require(head == parent, "integration HEAD moved from declared base/receipted landing")
    git.clean()
    git.idle()


def apply(git, spec, steps, state, path):
    for lane, step in zip(spec["lanes"][len(state["landings"]):], steps[len(state["landings"]):], strict=True):
        parent = git.out("rev-parse", "HEAD")
        check_refs(git, spec, state)
        check_untracked(git, step["paths"])
        if not state.get("pending"):
            git.clean()
            git.idle()
            state["pending"] = {**step, "parent": parent}
            save(path, state)  # Write-ahead evidence, before any real index/worktree mutation.
        merge = git.run("rev-parse", "--verify", "MERGE_HEAD", ok=False)
        if merge.returncode != 0 and not git.ancestor(step["tip"], parent):
            git.run("merge", "--strategy=ours", "--no-commit", "--no-ff", "--allow-unrelated-histories", lane["tip"])
        old_index = git.index_tree()
        require(old_index in {git.tree(parent), step["tree"]}, "index changed during apply")
        # Two-tree checkout protects untracked files; never reset/discard operator work.
        git.run("read-tree", "-m", "-u", old_index, step["tree"])
        require(git.index_tree() == step["tree"], "index differs from checked lane tree")
        timestamp = git.out("show", "-s", "--format=%ct", lane["tip"])
        env = {"GIT_AUTHOR_NAME": "Land twin lanes", "GIT_AUTHOR_EMAIL": "land-twin@localhost",
               "GIT_COMMITTER_NAME": "Land twin lanes", "GIT_COMMITTER_EMAIL": "land-twin@localhost",
               "GIT_AUTHOR_DATE": f"@{timestamp} +0000", "GIT_COMMITTER_DATE": f"@{timestamp} +0000"}
        # Normal Git commit runs configured hooks. A rejected gate remains pending, never bypassed.
        git.run("commit", "--allow-empty", "-m", message(spec, lane), env=env)
        record = {"lane": lane["id"], "commit": git.out("rev-parse", "HEAD"), "parent": parent,
                  "tree": step["tree"], "tip": lane["tip"]}
        verify_landing(git, spec, step, record, parent)
        git.clean()
        state["landings"].append(record)
        state["pending"] = None
        save(path, state)
    require(git.tree("HEAD") == state["composed_tree"], "final tree differs from checked composition")
    state["status"] = "applied"


def cleanup(git, spec, state, path):
    require(len(state["landings"]) == len(spec["lanes"]) and not state.get("pending"), "cleanup needs positive landing evidence")
    worktrees = []
    for raw in git.run("worktree", "list", "--porcelain", "-z").stdout.split(b"\0"):
        if raw.startswith(b"worktree "):
            worktrees.append(Path(os.fsdecode(raw[9:])))
    for root in worktrees:
        other = Git(plain_path(root))
        require(not other.run("status", "--porcelain", "-z", "--untracked-files=all").stdout,
                f"dirty worktree: {root}; task-finish must preserve and close it first")
        other.visible_index()
        other.idle()
    results = {entry["branch"]: entry for entry in state.get("cleanup_results", [])}
    for name in spec.get("cleanup", {}).get("branches", []):
        if name in results and results[name].get("result") == "deleted":
            continue
        lane = next(lane for lane in spec["lanes"] if lane["branch"] == name)
        require(git.ancestor(lane["tip"], "HEAD"), f"unmerged history: {name}")
        present = git.run("rev-parse", "--verify", "--quiet", f"refs/heads/{name}", ok=False)
        if present.returncode == 1 and name in results and results[name].get("result") == "deleting":
            results[name] = {"branch": name, "result": "deleted"}
            state["cleanup_results"] = list(results.values())
            save(path, state)
            continue
        require(present.returncode == 0 and os.fsdecode(present.stdout).strip() == lane["tip"],
                f"moved branch before deletion: {name}")
        # Write-ahead cleanup evidence allows recovery if interrupted immediately after -d.
        results[name] = {"branch": name, "result": "deleting"}
        state["cleanup_results"] = list(results.values())
        save(path, state)
        # -d is deliberate: if Git refuses, keep the branch and its reason. Never use -D.
        result = git.run("branch", "-d", "--", name, ok=False)
        results[name] = {"branch": name, "result": "deleted" if result.returncode == 0 else "retained"}
        if result.returncode:
            results[name]["reason"] = os.fsdecode(result.stderr).strip()
        state["cleanup_results"] = list(results.values())
        save(path, state)
    state["status"] = "cleaned"


def validate_state(state, spec):
    """Validate durable node output before using it as the next input. [GRPH-33]"""
    require(state["status"] in {"checked", "applied", "cleaned"}, "invalid receipt status")
    require(state["pending"] is None or isinstance(state["pending"], dict), "invalid pending receipt")
    require(isinstance(state["attempts"], list), "invalid receipt attempts")
    for attempt in state["attempts"]:
        obj(attempt, {"mode", "head_before", "outcome"}, {"head_after", "error"})
        require(attempt["mode"] in {"check", "apply", "cleanup"}
                and attempt["outcome"] in {"started", "ok", "failed"}, "invalid attempt contract")
        sha(attempt["head_before"])
        if "head_after" in attempt:
            sha(attempt["head_after"])
        if "error" in attempt:
            text(attempt["error"])
    require(isinstance(state["cleanup_results"], list), "invalid cleanup receipt")
    seen = set()
    for entry in state["cleanup_results"]:
        obj(entry, {"branch", "result"}, {"reason"})
        require(entry["branch"] in spec.get("cleanup", {}).get("branches", [])
                and entry["branch"] not in seen, "undeclared/duplicate cleanup evidence")
        require(entry["result"] in {"deleted", "deleting", "retained"}, "invalid cleanup result")
        if entry["result"] == "retained":
            text(entry.get("reason"))
        seen.add(entry["branch"])


def execute(spec, root, mode):
    git = Git(root)
    validate_checkout(git, spec)
    path = root / spec["receipt"]
    checkout_lock = Path(git.out("rev-parse", "--path-format=absolute", "--git-path", "land-twin-lanes.lock"))
    with state_lock(checkout_lock), state_lock(path.with_name(path.name + ".lock")):
        validate_checkout(git, spec)
        fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        steps = compose(git, spec)
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            obj(state, {"schema", "task", "spec_sha256", "integration_base", "composed_tree", "steps", "status",
                        "landings", "pending", "attempts", "cleanup_results"})
            require(state["schema"] == "land-twin-lanes/v1" and state["task"] == spec["task"]
                    and state["spec_sha256"] == fingerprint and state["steps"] == steps
                    and state["composed_tree"] == steps[-1]["tree"]
                    and state["integration_base"] == spec["integration"]["base"], "receipt/spec mismatch; preserve history")
        else:
            state = {"schema": "land-twin-lanes/v1", "task": spec["task"], "spec_sha256": fingerprint,
                     "integration_base": spec["integration"]["base"], "composed_tree": steps[-1]["tree"],
                     "steps": steps, "status": "checked", "landings": [], "pending": None,
                     "attempts": [], "cleanup_results": []}
        validate_state(state, spec)
        check_refs(git, spec, state, cleanup=mode == "cleanup")
        validate_history(git, spec, steps, state, allow_pending=mode == "apply")
        check_untracked(git, [p for step in steps for p in step["paths"]])
        state["attempts"].append({"mode": mode, "head_before": git.out("rev-parse", "HEAD"), "outcome": "started"})
        save(path, state)
        try:
            if mode == "apply":
                apply(git, spec, steps, state, path)
            elif mode == "cleanup":
                cleanup(git, spec, state, path)
            state["attempts"][-1]["outcome"] = "ok"
            state["attempts"][-1]["head_after"] = git.out("rev-parse", "HEAD")
            save(path, state)
        except (Refusal, OSError, subprocess.SubprocessError) as exc:
            state["attempts"][-1].update(outcome="failed", error=str(exc))
            save(path, state)
            raise
        return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--task", required=True, help="Expected task, independently supplied by the operator")
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("check", "apply", "cleanup"):
        modes.add_argument("--" + mode, action="store_true")
    args = parser.parse_args(argv)
    try:
        spec, root = load_spec(args.spec, args.task)
        mode = "apply" if args.apply else "cleanup" if args.cleanup else "check"
        state = execute(spec, root, mode)
    except (Refusal, OSError, ValueError, TypeError, KeyError, ImportError, subprocess.SubprocessError) as exc:
        print(f"land_twin_lanes: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(state, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
