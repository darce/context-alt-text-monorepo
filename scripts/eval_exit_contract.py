"""Operator-surface copy of the score CLI exit contract (S2R5-24).

Numbers are loaded from ``eval_exit_contract.env`` so Makefile, shell
wrappers, and Python publishers share one spelling. The scorer
(``scripts.eval_harness.cli``) is the origin and is not imported here.
"""

from __future__ import annotations

from pathlib import Path

_ENV_PATH = Path(__file__).with_name("eval_exit_contract.env")
_REQUIRED = (
    "EVAL_EXIT_CLEAN",
    "EVAL_EXIT_PARTIAL",
    "EVAL_EXIT_USAGE",
    "EVAL_EXIT_REFUSED",
)


def load_exit_contract(path: Path = _ENV_PATH) -> dict[str, int]:
    values: dict[str, int] = {}
    text = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        values[key] = int(value)
    missing = [name for name in _REQUIRED if name not in values]
    if missing:
        raise ValueError(f"eval_exit_contract.env missing {missing}")
    return values


_CODES = load_exit_contract()
EXIT_CLEAN = _CODES["EVAL_EXIT_CLEAN"]
EXIT_PARTIAL = _CODES["EVAL_EXIT_PARTIAL"]
EXIT_USAGE = _CODES["EVAL_EXIT_USAGE"]
EXIT_REFUSED = _CODES["EVAL_EXIT_REFUSED"]
