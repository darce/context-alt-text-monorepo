"""GTMSMOKE-1 endpoint-docs contract: causal RED before the separate implementation.

Scope is limited to docs/runbooks/tenant-onboarding-smoke-test.md and
docs/runbooks/clerk-production-auth.md. Production source, existing tests,
secrets, runtime, databases, GPUs and corpora are not read or written.

``test_contract_*`` tests encode the operator-authoritative GTMSMOKE-1 mapping and
cold-start order. They must FAIL against the unchanged runbooks; the failure
message names the stale claim. ``test_control_*`` tests pin behavior that is
already correct and must PASS now and remain green through that change.

Only the documented wording is pinned by literal phrase checks. Command checks
execute the documented blocks with a fake docker on PATH, as in
test_clerk_prod_invitation_prereq.py.

Canon v0.25.6 rows applied here: TEST-15 Prove the green can go red (The
Pragmatic Programmer, ch. 9); EMB-01 One embedding space per comparison
(Foundations of Vector Retrieval, ch. 1); GRPH-01 Model the work as a DAG, then
topological-sort (The Algorithm Design Manual, ch. 7); RLSE-08 Rollback written
before ship (Continuous Delivery, ch. 10 and 12), for the spare-site backup rule.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

from conftest import _write_executable

REPO_ROOT = Path(__file__).resolve().parents[3]
TENANT_RUNBOOK = REPO_ROOT / "docs/runbooks/tenant-onboarding-smoke-test.md"
CLERK_RUNBOOK = REPO_ROOT / "docs/runbooks/clerk-production-auth.md"
PORTAL_MANIFEST = REPO_ROOT / "config/env/manifest.d/30-portal-backend.toml"
CLI_PATH = "apps/prototype-description-service/scripts/manage_portal_invitations.py"
DEMO_HOST = "demo.altcontext.com"
AURA_A_RECORD = "129.213.40.111"
AURA_TARGETS = (
    ("dev-auraface", "auraface.dev.altcontext.com"),
    ("staging-auraface", "auraface.staging.api.altcontext.com"),
    ("prod-auraface", "auraface.api.altcontext.com"),
)
SPARE_PORTS = ("localhost:10023", "localhost:10018")
# Obsolete demo->FIR-production routing; each phrase is verbatim in the unchanged runbook.
OBSOLETE_FIR_ROUTING = (
    "production FIR must be identified first",
    "dedicated FIR production only",
    "First satisfy the dedicated FIR production gate",
    "Do not create a Site 1 tenant, invitation, or key in /opt/acx-backend/prod",
    "Do not issue a Site 1 invitation through the generic InsightFace",
)
FAKE_TENANT_UUID = "00000000-0000-4000-8000-000000000003"
DOCKER_LOG_FAKE = r"""#!/bin/sh
printf '%s' "$PWD" >>"$DOCKER_LOG"
for arg in "$@"; do printf '\t%s' "$arg" >>"$DOCKER_LOG"; done
printf '\n' >>"$DOCKER_LOG"
exit 0
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    assert start in text, f"missing section marker: {start!r}"
    tail = text.split(start, 1)[1]
    assert end in tail, f"missing section end marker: {end!r}"
    return tail.split(end, 1)[0]


def _sentences(text: str) -> list[str]:
    return [sentence for sentence in re.split(r"(?<=[.!?])\s+", _flat(text)) if sentence]


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped) <= set("|- "):
            continue
        rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
    return rows


def _rows_with(text: str, token: str) -> list[list[str]]:
    return [cells for cells in _table_rows(text) if any(token in cell for cell in cells)]


def _ordered_targets(text: str) -> list[list[str]]:
    section = _between(text, "## 1. Ordered targets and stop gates", "## 2. Clerk sign-in")
    return [cells for cells in _table_rows(section) if cells[0].isdigit()]


def _target_row(text: str, token: str) -> list[str]:
    matches = [cells for cells in _ordered_targets(text) if token in cells[1]]
    assert len(matches) == 1, f"expected one ordered-target row for {token}, found {len(matches)}"
    return matches[0]


def _fenced_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:sh|bash)\n(.*?)```", text, re.DOTALL)


def _prerequisite(clerk: str) -> str:
    return _flat(_between(clerk, "## Production LAUNCH prerequisite (before A3/deployment)", "Official references:"))


def _session_template(clerk: str) -> dict[str, str]:
    match = re.search(r"```json\n(.*?)```", clerk, re.DOTALL)
    assert match, "session template JSON block missing"
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"session template is not valid JSON: {exc}") from exc


def _prod_clerk_values() -> dict[str, str]:
    manifest = tomllib.loads(_read(PORTAL_MANIFEST))
    by_name = {var["name"]: var for var in manifest["var"]}
    return {name: by_name[name]["values"]["prod"] for name in by_name if name.startswith("ACX_CLERK_")}


def _pair(row: list[str], flag: str, value: str) -> bool:
    return any(row[i] == flag and row[i + 1] == value for i in range(len(row) - 1))


# --- RED: operator-authoritative mapping in tenant-onboarding-smoke-test.md ---


def test_contract_demo_site_is_insightface_512_not_fir_production() -> None:
    row = _target_row(_read(TENANT_RUNBOOK), DEMO_HOST)
    service, effective_url = row[2], row[3]
    assert "InsightFace" in service and "512" in service, (
        f"demo row must name the InsightFace 512D space, got service={service!r}"
    )
    assert "FIR" not in service, f"demo row still routes to FIR production: {service!r}"
    assert "fir.api.altcontext.com" not in effective_url, (
        f"demo effective URL still targets the FIR production hostname: {effective_url!r}"
    )


def test_contract_wp10010_row_names_insightface_512_space() -> None:
    row = " | ".join(_target_row(_read(TENANT_RUNBOOK), "localhost:10010"))
    assert "InsightFace" in row and "512" in row, "wp-context-alt-text:10010 row must name the InsightFace 512D space"


def test_contract_wp10028_row_names_sface_128_space() -> None:
    row = " | ".join(_target_row(_read(TENANT_RUNBOOK), "localhost:10028"))
    assert "SFace" in row and "128" in row, "fir:10028 row must name the FIR SFace 128D space"


def test_contract_spare_sites_r10023_and_vlm10018_are_aura512_candidates() -> None:
    text = _read(TENANT_RUNBOOK)
    missing = []
    for port in SPARE_PORTS:
        rows = [" ".join(cells) for cells in _rows_with(text, port)]
        if not any("AuraFace" in row and "512" in row for row in rows):
            missing.append(port)
    assert not missing, f"spare actual ports not bound to AuraFace 512D rows: {missing}"


def test_contract_two_spare_sites_serve_three_aura_targets_third_pending_without_wiping() -> None:
    text = _flat(_read(TENANT_RUNBOOK))
    assert re.search(r"two spare sites", text, re.IGNORECASE), "missing two-spare-site statement"
    third = [s for s in _sentences(text) if re.search(r"\bthird\b", s, re.IGNORECASE) and "Aura" in s]
    assert third and all("pending" in s.lower() for s in third), "third Aura fixture must be recorded as pending"
    assert re.search(r"back(?:ed)? up", text, re.IGNORECASE), "spare sites must be backed up before Aura work"
    assert re.search(r"do not wipe", text, re.IGNORECASE), "spare sites must keep the do-not-wipe content rule"


def test_contract_frozen_aura_target_labels_bind_to_their_hostnames() -> None:
    text = _read(TENANT_RUNBOOK)
    unbound = [
        label for label, host in AURA_TARGETS if not any(label in " ".join(cells) for cells in _rows_with(text, host))
    ]
    assert not unbound, f"frozen Aura target labels not bound to their hostnames: {unbound}"


def test_contract_aura_names_are_labelled_proposed_configuration_not_observed() -> None:
    section = _flat(_between(_read(TENANT_RUNBOOK), "## 6. Model-space and quality boundary", "## 7. Supplied status"))
    assert "proposed configuration" in section, "Aura names must be labelled proposed configuration"
    assert "not observed" in section, "Aura names must be stated as not observed resources"


def test_contract_obsolete_demo_to_fir_production_routing_is_removed() -> None:
    text = _flat(_read(TENANT_RUNBOOK))
    present = [phrase for phrase in OBSOLETE_FIR_ROUTING if phrase in text]
    assert not present, f"obsolete demo->FIR-production routing still documented: {present}"


# --- RED: Clerk invitation CLI status in clerk-production-auth.md ---


def test_contract_clerk_cli_is_recorded_present_in_source_not_absent() -> None:
    prerequisite = _prerequisite(_read(CLERK_RUNBOOK))
    assert "does **not** include the invitation CLI" not in prerequisite, (
        "launch prerequisite still asserts the invitation CLI is absent from the tree"
    )
    assert CLI_PATH in prerequisite, "launch prerequisite must name the source CLI path"
    assert re.search(r"\bpresent\b", prerequisite, re.IGNORECASE), "source presence of the CLI is not recorded"


# --- RED: cold-start order in the image-description smoke ---


def test_contract_description_precheck_does_not_require_live_gpu_before_demand() -> None:
    section = _between(
        _read(TENANT_RUNBOOK), "### Separate image-description smoke", "## 6. Model-space and quality boundary"
    )
    stale = [
        sentence
        for sentence in _sentences(section)
        if "live and authenticated" in sentence
        and not re.search(r"post-demand|after (?:the )?demand|\bSTART\b", sentence)
    ]
    assert not stale, f"GPU liveness is still a pre-demand prerequisite: {stale}"


def test_contract_cold_start_is_initial_stopped_then_demand_caused_start() -> None:
    section = _between(
        _read(TENANT_RUNBOOK), "### Separate image-description smoke", "## 6. Model-space and quality boundary"
    )
    sentences = _sentences(section)
    missing = []
    if not any(re.search(r"initial(?:ly)? STOPPED", s) for s in sentences):
        missing.append("initial STOPPED")
    if not any("pre-demand" in s.lower() and "credential" in s.lower() and "config" in s.lower() for s in sentences):
        missing.append("pre-demand config/credential checks")
    if not any("START" in s and "authenticated" in s.lower() and "ready" in s.lower() for s in sentences):
        missing.append("authenticated GPU readiness after START")
    if not any("prewarm" in s.lower() and "prerequisite" in s.lower() for s in sentences):
        missing.append("prewarming is not a prerequisite")
    assert not missing, f"cold-start contract missing: {missing}"


# --- CONTROLS: already correct; must pass now and stay green ---


def test_control_wp10028_row_binds_dev_fir_store_url_and_key_environment() -> None:
    row = _target_row(_read(TENANT_RUNBOOK), "localhost:10028")
    assert "dev-fir" in row[2]
    assert row[3] == "https://fir.dev.api.altcontext.com"
    assert row[4].startswith("dev-fir")


def test_control_aura_rows_never_reuse_original_sites() -> None:
    rows = [cells for cells in _table_rows(_read(TENANT_RUNBOOK)) if "aura" in " ".join(cells).lower()]
    assert rows, "AuraFace planned-name rows are missing"
    for cells in rows:
        joined = " ".join(cells)
        for port in ("localhost:10010", "localhost:10028"):
            assert port not in joined, f"AuraFace row reuses original site {port}: {cells}"


def test_control_aura_planned_names_keep_frozen_a_record_and_ttl() -> None:
    text = _read(TENANT_RUNBOOK)
    for _label, host in AURA_TARGETS:
        rows = [" ".join(cells) for cells in _rows_with(text, host)]
        assert rows, f"planned name {host} is missing"
        assert any(AURA_A_RECORD in row and "TTL 300" in row for row in rows), f"{host} lost its frozen A record or TTL"


def test_control_existing_generic_and_fir_endpoints_are_preserved() -> None:
    preserve = [s for s in _sentences(_read(TENANT_RUNBOOK)) if "Preserve fir.dev.api.altcontext.com" in s]
    assert preserve, "preservation statement for existing endpoints is missing"
    for host in (
        "fir.dev.api.altcontext.com",
        "fir.api.altcontext.com",
        "dev.api.altcontext.com",
        "staging.api.altcontext.com",
        "api.altcontext.com",
    ):
        assert host in preserve[0], f"{host} is no longer preserved"


def test_control_model_space_widths_and_canon_rules_stay_separate() -> None:
    text = _flat(_read(TENANT_RUNBOOK))
    for phrase in (
        "generic InsightFace 512D",
        "FIR SFace 128D",
        "AuraFace 512D",
        "InsightFace and AuraFace remain distinct provenance even at equal width",
        "Never copy or pad vectors",
        "EMB-01, one embedding space per comparison",
    ):
        assert phrase in text, f"missing model-space contract: {phrase}"


def test_control_clerk_cli_path_is_tracked_in_git() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", CLI_PATH],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_control_clerk_serving_image_guard_remains_a_stop_gate() -> None:
    prerequisite = _prerequisite(_read(CLERK_RUNBOOK))
    for phrase in (
        "STOP: do not begin A3/deployment or production LAUNCH",
        "production service release to deploy includes that CLI",
        "confirm the deployed production API also includes it",
    ):
        assert phrase in prerequisite, f"serving-image stop gate lost: {phrase}"


def test_control_clerk_session_template_keeps_quoted_verified_claims() -> None:
    claims = _session_template(_read(CLERK_RUNBOOK))
    expected = {
        "email": "{{user.primary_email_address}}",
        "email_verified": "{{user.email_verified}}",
    }
    for key, value in expected.items():
        assert claims.get(key) == value, f"session template claim {key} changed"


def test_control_clerk_verifier_literals_match_prod_manifest() -> None:
    values = _prod_clerk_values()
    audience = values["ACX_CLERK_AUDIENCE"]
    parties = values["ACX_CLERK_AUTHORIZED_PARTIES"]
    issuer_host = values["ACX_CLERK_ISSUER"].removeprefix("https://")
    clerk = _flat(_read(CLERK_RUNBOOK))
    tenant = _flat(_read(TENANT_RUNBOOK))
    assert _session_template(_read(CLERK_RUNBOOK))["aud"] == audience
    assert f"ACX_CLERK_AUDIENCE={audience}" in tenant
    assert f"ACX_CLERK_AUTHORIZED_PARTIES={parties}" in tenant
    assert audience in clerk and parties in clerk
    assert f"`{issuer_host}`" in clerk


def test_control_description_endpoint_credential_stays_server_side() -> None:
    text = _flat(_read(TENANT_RUNBOOK))
    assert (
        "Keep the endpoint credential on the server/GPU side; never put it in WordPress, the browser, "
        "or the tenant API key field."
    ) in text


def test_control_documented_prod_write_blocks_fail_closed_without_verified_stack_dir(tmp_path: Path) -> None:
    blocks = [block for block in _fenced_blocks(_read(TENANT_RUNBOOK)) if "--env prod" in block]
    assert blocks, "no documented prod-env command blocks were checked"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker.log"
    _write_executable(fake_bin / "docker", DOCKER_LOG_FAKE)
    env = {key: value for key, value in os.environ.items() if key != "FIR_PROD_STACK_DIR"}
    env.update({"PATH": str(fake_bin), "DOCKER_LOG": str(log)})
    for block in blocks:
        result = subprocess.run(
            ["/bin/bash", "-c", block],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode != 0, f"prod write block ran without a verified stack dir: {block.splitlines()[0]!r}"
        assert "FIR_PROD_STACK_DIR" in result.stderr, "fail-closed guard message is missing"
    assert not log.exists(), "docker must not run while the verified stack directory is unset"


def test_control_site3_dev_fir_cli_binds_store_and_port_10028(tmp_path: Path) -> None:
    block = next(b for b in _fenced_blocks(_read(TENANT_RUNBOOK)) if "--env dev-fir tenant create" in b)
    stack = tmp_path / "dev-fir"
    stack.mkdir()
    script = block.replace("/opt/acx-backend/dev-fir", str(stack)).replace("<site-3-tenant-uuid>", FAKE_TENANT_UUID)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker.log"
    _write_executable(fake_bin / "docker", DOCKER_LOG_FAKE)
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(fake_bin), "DOCKER_LOG": str(log)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    rows = [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4, f"expected the guard plus three documented CLI calls, got {len(rows)}"
    assert all(row[0] == str(stack) for row in rows), "documented commands must run in the dev-fir stack directory"
    tenant_create = next(row for row in rows if "tenant" in row and "create" in row)
    assert _pair(tenant_create, "--env", "dev-fir")
    assert _pair(tenant_create, "--tenant", FAKE_TENANT_UUID)
    assert _pair(tenant_create, "--site-url", "http://localhost:10028")
