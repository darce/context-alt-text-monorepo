#!/usr/bin/env python3
"""Bootstrap a linked WorkBay worktree so lifecycle targets resolve in it.

ORCA-1: WorkBay is the only worktree provisioner. Linked worktrees do not
inherit the gitignored overlay, so `make context` and `make slice-commit` fail
exactly where work happens (TOOL-1, VMREAP-1). This entry point links the
primary venv, copies every overlay prefix named by the harness-protocol
contract through provision_lane_worktree.py, keeps literature/ out of the
checkout, and proves both make targets resolve before reporting success.

Exit codes: 0 ok, 2 precondition, 3 provisioning, 4 postcondition. Stdout is
exactly one JSON line on success; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PROVISIONER = Path(__file__).resolve().parent / "provision_lane_worktree.py"
CONTRACT_REL = Path("docs/workbay/contracts/harness-protocol.yaml")
PREFIXES_KEY_PATH: tuple[str, ...] = (
    "bootstrap_overlay",
    "tracked_vs_overlay_boundary",
    "overlay_managed_prefixes",
)
SPARSE_PATTERNS: tuple[str, ...] = ("/*", "!/literature/")
POSTCONDITION_TARGETS: tuple[str, ...] = ("context", "slice-commit")
POSTCONDITION_TIMEOUT_S = 120
SCRUBBED_MAKE_ENV: tuple[str, ...] = ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")
STDERR_TAIL_LINES = 20
STDERR_FD = 2

EXIT_OK = 0
EXIT_PRECONDITION = 2
EXIT_PROVISIONING = 3
EXIT_POSTCONDITION = 4

KEY_PATH = ".".join(PREFIXES_KEY_PATH)


class BootstrapError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _note(message: str) -> None:
    print(f"bootstrap_worktree: {message}", file=sys.stderr)


def _tail(text: str | bytes | None) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    lines = (text or "").strip().splitlines()
    return "\n".join(lines[-STDERR_TAIL_LINES:]) if lines else "(no stderr)"


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise BootstrapError(EXIT_PRECONDITION, f"cannot run git: {exc}; put git on PATH and rerun") from exc


def _load_primary_checkout() -> Callable[[Path], Path]:
    """Load primary_checkout from the sibling provisioner; one owner for that rule."""
    spec = importlib.util.spec_from_file_location("_workbay_provision_lane_worktree", PROVISIONER)
    if spec is None or spec.loader is None:
        raise BootstrapError(EXIT_PRECONDITION, f"cannot load {PROVISIONER}; pass --primary PATH")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        # Any import-time failure is a missing precondition, not a crash: the
        # caller branches on exit 2, and --primary sidesteps the import.
        sys.modules.pop(spec.name, None)
        raise BootstrapError(
            EXIT_PRECONDITION, f"cannot load primary_checkout from {PROVISIONER}: {exc}; pass --primary PATH"
        ) from exc
    primary_checkout = getattr(module, "primary_checkout", None)
    if not callable(primary_checkout):
        raise BootstrapError(EXIT_PRECONDITION, f"{PROVISIONER} has no primary_checkout(); pass --primary PATH")
    return primary_checkout


def _resolve_worktree(raw: Path) -> Path:
    worktree = raw.expanduser().resolve()
    if not worktree.is_dir():
        raise BootstrapError(
            EXIT_PRECONDITION, f"worktree {worktree} is not a directory; pass --worktree <linked worktree path>"
        )
    proc = _git(worktree, "rev-parse", "--show-toplevel")
    toplevel = proc.stdout.strip()
    if proc.returncode != 0 or not toplevel:
        raise BootstrapError(
            EXIT_PRECONDITION,
            f"worktree {worktree} is not inside a git worktree ({_tail(proc.stderr)}); "
            "pass --worktree <linked worktree path>",
        )
    # Bootstrapping a subdirectory would drop the overlay and venv inside the
    # checkout instead of at its root.
    if Path(toplevel).resolve() != worktree:
        raise BootstrapError(
            EXIT_PRECONDITION,
            f"worktree {worktree} is not the top of its git worktree ({toplevel}); pass --worktree {toplevel}",
        )
    return worktree


def _resolve_primary(raw: Path | None, worktree: Path) -> Path:
    if raw is None:
        primary_checkout = _load_primary_checkout()
        try:
            primary = Path(primary_checkout(worktree)).resolve()
        except (RuntimeError, OSError) as exc:
            raise BootstrapError(
                EXIT_PRECONDITION, f"cannot resolve the primary checkout: {exc}; pass --primary PATH"
            ) from exc
    else:
        primary = raw.expanduser().resolve()
    if not primary.is_dir():
        raise BootstrapError(
            EXIT_PRECONDITION, f"primary {primary} is not a directory; pass --primary <primary checkout path>"
        )
    return primary


def _link_venv(*, primary: Path, worktree: Path) -> str:
    dest = worktree / ".venv"
    if dest.exists() or dest.is_symlink():
        return "present"
    src = primary / ".venv"
    if not src.exists():
        _note(f"{src} does not exist; the worktree has no .venv (make targets may not parse)")
        return "absent"
    try:
        dest.symlink_to(src, target_is_directory=True)
    except OSError as exc:
        raise BootstrapError(
            EXIT_PROVISIONING, f"cannot link {dest} -> {src}: {exc}; create the link by hand and rerun"
        ) from exc
    return "linked"


def _contract_error(contract: Path, why: str) -> BootstrapError:
    return BootstrapError(
        EXIT_PRECONDITION,
        f"{contract}: {KEY_PATH} {why}; restore the WorkBay overlay contract in the primary checkout "
        "(workbay install / update) and rerun",
    )


def _overlay_prefixes(primary: Path) -> list[str]:
    contract = primary / CONTRACT_REL
    try:
        import yaml
    except ImportError as exc:
        raise BootstrapError(
            EXIT_PRECONDITION,
            f"pyyaml is not importable by {sys.executable}, so {KEY_PATH} cannot be read from {contract}; "
            "run with the primary checkout's .venv python (uv sync)",
        ) from exc
    try:
        text = contract.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _contract_error(contract, "is unavailable because the contract file is missing") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise _contract_error(contract, f"is unreadable ({exc})") from exc
    try:
        node: object = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _contract_error(contract, f"is unreadable because the file is not valid YAML ({exc})") from exc

    walked: list[str] = []
    for key in PREFIXES_KEY_PATH:
        if not isinstance(node, dict):
            where = ".".join(walked) or "the document root"
            raise _contract_error(contract, f"is missing because {where} is not a mapping")
        walked.append(key)
        if key not in node:
            raise _contract_error(contract, f"is missing ({'.'.join(walked)} not found)")
        node = node[key]
    if not isinstance(node, list) or not node:
        raise _contract_error(contract, "must be a non-empty list of non-empty strings")
    for index, item in enumerate(node):
        if not isinstance(item, str) or not item.strip():
            raise _contract_error(contract, f"must contain only non-empty strings (item {index} is {item!r})")
    return list(node)


def _run_provisioner(*, provisioner: Path, primary: Path, worktree: Path, prefixes: list[str]) -> None:
    argv = [sys.executable, str(provisioner), "--worktree", str(worktree), "--primary", str(primary)]
    for prefix in prefixes:
        argv += ["--overlay-path", prefix]
    try:
        # Its stdout goes to our stderr: stdout is reserved for the receipt.
        proc = subprocess.run(argv, stdout=STDERR_FD, check=False)
    except OSError as exc:
        raise BootstrapError(EXIT_PROVISIONING, f"cannot run {provisioner}: {exc}") from exc
    if proc.returncode != 0:
        raise BootstrapError(
            EXIT_PROVISIONING,
            f"{provisioner} exited {proc.returncode} (stderr above); fix the reported overlay problem and rerun",
        )


def _apply_sparse(worktree: Path, *, disabled: bool) -> str:
    if disabled:
        return "disabled"
    if _git(worktree, "config", "--bool", "core.sparseCheckout").stdout.strip() == "true":
        _note(f"{worktree} already uses sparse checkout; leaving its patterns unchanged")
        return "already"
    if not (worktree / "literature").exists():
        _note(f"{worktree}/literature does not exist; skipping sparse checkout")
        return "skipped:literature-absent"
    status = _git(worktree, "status", "--porcelain", "--", "literature")
    if status.returncode != 0:
        raise BootstrapError(
            EXIT_PROVISIONING,
            f"git status -- literature failed in {worktree} (exit {status.returncode}): {_tail(status.stderr)}",
        )
    if status.stdout.strip():
        _note(
            f"{worktree}/literature has uncommitted changes; skipping sparse checkout so they stay visible. "
            "Commit or move them, then rerun (or rerun with --no-sparse)"
        )
        return "skipped:literature-dirty"
    proc = _git(worktree, "sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS)
    if proc.returncode != 0:
        raise BootstrapError(
            EXIT_PROVISIONING,
            f"git sparse-checkout set --no-cone {' '.join(SPARSE_PATTERNS)} failed in {worktree} "
            f"(exit {proc.returncode}): {_tail(proc.stderr)}; fix it and rerun, or rerun with --no-sparse",
        )
    return "applied"


def _check_postconditions(*, make: str, worktree: Path) -> list[str]:
    # task-start invokes us from inside make: inherited MAKEFLAGS/MAKELEVEL
    # would carry the parent's command-line variables and jobserver into the
    # probe, so it would not show what a fresh shell in the worktree sees.
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED_MAKE_ENV}
    checked: list[str] = []
    for target in POSTCONDITION_TARGETS:
        argv = [make, "--no-print-directory", "-C", str(worktree), "-n", target]
        label = f"make -n {target}"
        try:
            proc = subprocess.run(
                argv,
                env=env,
                capture_output=True,
                text=True,
                timeout=POSTCONDITION_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BootstrapError(
                EXIT_POSTCONDITION,
                f"postcondition `{label}` timed out after {POSTCONDITION_TIMEOUT_S}s in {worktree}:\n"
                f"{_tail(exc.stderr)}",
            ) from exc
        except OSError as exc:
            raise BootstrapError(EXIT_POSTCONDITION, f"postcondition `{label}` could not run {make!r}: {exc}") from exc
        if proc.returncode != 0:
            raise BootstrapError(
                EXIT_POSTCONDITION,
                f"postcondition `{label}` failed in {worktree} (exit {proc.returncode}); the overlay is "
                f"incomplete or does not parse:\n{_tail(proc.stderr)}",
            )
        checked.append(target)
    return checked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worktree", type=Path, default=Path("."), help="linked worktree (default: cwd)")
    parser.add_argument(
        "--primary",
        type=Path,
        default=None,
        help="primary checkout (default: the parent of the worktree's git common dir)",
    )
    parser.add_argument("--no-sparse", action="store_true", help="do not hide literature/ via sparse checkout")
    parser.add_argument("--provisioner", type=Path, default=PROVISIONER, help=argparse.SUPPRESS)
    parser.add_argument("--make", default="make", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        worktree = _resolve_worktree(args.worktree)
        primary = _resolve_primary(args.primary, worktree)
        if worktree == primary:
            raise BootstrapError(
                EXIT_PRECONDITION,
                f"refusing to bootstrap the primary checkout {primary}; pass --worktree <linked worktree path>",
            )
        venv = _link_venv(primary=primary, worktree=worktree)
        prefixes = _overlay_prefixes(primary)
        _run_provisioner(provisioner=args.provisioner, primary=primary, worktree=worktree, prefixes=prefixes)
        sparse = _apply_sparse(worktree, disabled=args.no_sparse)
        postconditions = _check_postconditions(make=args.make, worktree=worktree)
    except BootstrapError as exc:
        _note(str(exc))
        return exc.code
    receipt = {
        "ok": True,
        "worktree": str(worktree),
        "primary": str(primary),
        "overlay_paths": prefixes,
        "venv": venv,
        "sparse": sparse,
        "postconditions": postconditions,
    }
    print(json.dumps(receipt))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
