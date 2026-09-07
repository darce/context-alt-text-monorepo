"""The intent-durability half of the GPU lifecycle contract must stay executable.

GPUOPS-1-CANON-03/06/08: the operator intent is a write-ahead record for a
durable external mutation (a running GPU that bills by the hour), but the
intent file itself lives on tmpfs. The durable half is
`infra/oci/gpu_lifecycle/intent_journal.py`. Prose describing it rots the
moment the module moves, so this guard reads the module, the installer units
and the contract together and refuses to let the three disagree (rg-005
contract parity, rg-006 documented behaviour must be real).

It deliberately asserts on the *contract-bearing* names — the default path, the
record vocabulary, the bounded size, the re-arm budget — not on prose wording.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "docs/workbay/contracts/gpu-lifecycle.md"
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
JOURNAL = REPO_ROOT / "infra/oci/gpu_lifecycle/intent_journal.py"

_CLI_FLAG = "--intent-journal-path"


def _contract() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _journal_constant(name: str) -> str:
    """The literal a module-level constant is assigned, as written in source.

    Read from source rather than imported: the contract has to agree with what
    a reviewer sees in the file, and importing would let a runtime-computed
    value satisfy a guard about a documented default.
    """
    match = re.search(
        rf"^{re.escape(name)}\s*=\s*(?P<value>.+?)\s*$",
        JOURNAL.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert match is not None, (
        f"{JOURNAL.name} no longer defines {name}; this guard has lost the "
        "value it compares the contract against"
    )
    return match.group("value")


def test_contract_names_the_module_that_makes_the_intent_durable() -> None:
    """A tmpfs-only grant is the defect; the contract must name its durable half."""
    contract = _contract()

    assert "infra/oci/gpu_lifecycle/intent_journal.py" in contract, (
        "the contract must name the module that persists operator intent, or "
        "the durability claim has no referent"
    )
    assert JOURNAL.exists(), "the contract names an intent journal module that does not exist"


def test_contract_states_the_journal_default_path_the_code_uses() -> None:
    default = _journal_constant("DEFAULT_INTENT_JOURNAL_PATH")
    path_literal = re.fullmatch(r'Path\("(?P<path>[^"]+)"\)', default)
    assert path_literal is not None, f"unexpected default journal path expression: {default}"
    path = path_literal.group("path")

    assert f"`{path}`" in _contract(), (
        f"the journal defaults to {path}; the contract states a different path"
    )
    assert path.startswith("/var/lib/acx-gpu/"), (
        f"the journal defaults to {path}, which is not the unit StateDirectory; "
        "a journal outside durable storage does not survive the reboot it exists to record"
    )


def test_the_deployed_units_actually_pass_the_journal_path() -> None:
    """A default nothing wires up is a claim, not a deployment (rg-006)."""
    installer = INSTALLER.read_text(encoding="utf-8")
    default = _journal_constant("DEFAULT_INTENT_JOURNAL_PATH")
    path = re.fullmatch(r'Path\("(?P<path>[^"]+)"\)', default).group("path")  # type: ignore[union-attr]

    services = re.findall(
        r"sudo tee [^\n]*/acx-gpu-(start|reap)\.service.*?<<UNIT\n(.*?)\nUNIT",
        installer,
        flags=re.DOTALL,
    )
    assert {name for name, _ in services} == {"start", "reap"}, (
        "expected both lifecycle units in the installer"
    )
    for name, unit in services:
        assert f"{_CLI_FLAG} {path}" in unit, (
            f"acx-gpu-{name}.service does not pass {_CLI_FLAG} {path}; the "
            "intent journal would not be written on the deployed host"
        )
        assert "StateDirectory=acx-gpu" in unit, (
            f"acx-gpu-{name}.service must own the state directory it journals into"
        )


def test_contract_lists_exactly_the_record_kinds_the_journal_writes() -> None:
    """The record vocabulary is the audit trail's schema (sr-007, HAI-06)."""
    source = JOURNAL.read_text(encoding="utf-8")
    body = re.search(
        r"class JournalRecordKind\(StrEnum\):.*?(?=\n\n_|\nclass |\n@)",
        source,
        flags=re.DOTALL,
    )
    assert body is not None, f"{JOURNAL.name} no longer defines JournalRecordKind"
    kinds = set(re.findall(r'^\s{4}[A-Z_]+ = "([a-z_]+)"$', body.group(0), flags=re.MULTILINE))
    assert kinds, "JournalRecordKind parsed empty; this guard would be vacuous"

    contract = _contract()
    documented = set()
    for line in contract.splitlines():
        if line.startswith("| `") and "|" in line[3:]:
            candidate = line.split("|")[1].strip().strip("`")
            if candidate in kinds:
                documented.add(candidate)

    assert documented == kinds, (
        "the contract's journal record table and JournalRecordKind disagree; "
        f"undocumented: {sorted(kinds - documented)}, stale: {sorted(documented - kinds)}"
    )


def test_contract_states_the_bounds_that_keep_the_journal_safe_to_leave_running() -> None:
    """An unbounded append-only file on a unattended host is an outage (rg-007)."""
    contract = _contract()

    max_records = _journal_constant("DEFAULT_MAX_JOURNAL_RECORDS")
    assert max_records in contract, (
        f"the journal keeps {max_records} records; the contract does not state that bound"
    )

    rearm = _journal_constant("DEFAULT_DEFERRED_STOP_REARM_SECONDS")
    rearm_seconds = int(float(rearm))
    assert f"{rearm_seconds} s" in contract or f"{rearm_seconds} seconds" in contract, (
        f"the deferred-stop re-arm budget is {rearm_seconds}s; the contract does not state it"
    )


def test_contract_states_the_monotonic_and_reboot_rules_the_fence_enforces() -> None:
    """The two rules that stop a clock correction from spending money (RES-10)."""
    contract = _contract().lower()

    assert "boot_id" in contract and "/proc/sys/kernel/random/boot_id" in contract, (
        "the contract must state that a reboot revokes an in-flight grant"
    )
    assert "monotonic" in contract, "the contract must state the monotonic expiry origin"
    assert "backwards" in contract, (
        "the contract must state that a backwards clock correction cannot re-arm a spent grant"
    )
    # The journal must actually read the boot identity it claims to fence on.
    assert "read_host_boot_id" in JOURNAL.read_text(encoding="utf-8"), (
        "the contract claims a boot-identity fence the journal does not implement"
    )
