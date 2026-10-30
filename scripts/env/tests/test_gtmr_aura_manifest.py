"""Causal manifest contract for three isolated AuraFace 512d targets.

Generic/FIR runtime controls pin the accepted fbcd8ee0 contract (provenance below),
superseding the original pre-Aura fingerprints from commit 0d3ff19d, tree 1fb33a6.
The Aura contract originated at that older source; its mutation controls prove
the gate can fail. Environment labels and resource names are configuration,
not observed resources.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import load_module

manifest_api = load_module("manifest")
render_api = load_module("render_env")
ManifestError = manifest_api.ManifestError

REPO = Path(__file__).resolve().parents[3]
MANIFEST_ROOT = REPO / "config" / "env"

AURA_LABELS = ("dev-auraface", "staging-auraface", "prod-auraface")
GENERIC_TARGETS = ("svc-local", "svc-vm", "svc-fir", "demo")
GENERIC_LABELS = ("local", "dev", "staging", "prod", "fir", "demo")
AURA_REMOTE_PATHS = {label: f"/opt/acx-backend/{label}/.env" for label in AURA_LABELS}
AURA_LEASE_ENV = {label: label for label in AURA_LABELS}

FACE_EXPECTED = {
    "PGVECTOR_DIM": "512",
    "RECOGNITION_FACE_PIPELINE_PROFILE": "auraface",
    "RECOGNITION_FACE_PIPELINE_MODELS_DIR": "/data/cache/face_pipeline",
    "RECOGNITION_AURAFACE_MODELS_DIR": "/data/cache/face_pipeline",
}
SECURITY_EXPECTED = {
    "RECOGNITION_AUTH_ENABLED": "true",
    "RECOGNITION_ADMIN_ENABLED": "false",
}
STORE_SECRETS = ("POSTGRES_PASSWORD", "POSTGRES_DSN", "POSTGRES_SYNC_DSN")

FIR_CONTROL = {
    "ACX_ENV": "dev-fir",
    "COMPOSE_PROJECT_NAME": "acx-dev-fir",
    "ACX_IMAGE_TAG": "dev-fir",
    "ACX_NETWORK_NAME": "acx-dev-fir-net",
    "ACX_PGDATA_PATH": "/opt/acx-backend/data/dev-fir-pgdata",
    "ACX_MODELS_PATH": "/opt/acx-backend/data/dev-models",
    "POSTGRES_DB": "alt_context_dev_fir",
    "POSTGRES_USER": "acx_dev_fir",
    "PGVECTOR_DIM": "128",
    "RECOGNITION_FACE_PIPELINE_PROFILE": "face_pipeline",
    "RECOGNITION_FACE_PIPELINE_MODELS_DIR": "/data/cache/face_pipeline",
    "RECOGNITION_AUTH_ENABLED": "true",
    "RECOGNITION_ADMIN_ENABLED": "false",
}

# Fixed expectations reviewed against accepted source fbcd8ee0fba416f703637f87b130fd3dbf25434c,
# tree 267daa6f8164913f6880f975fac1fd0beeddf99d; never regenerated during tests.
# Supersedes tree 1fb33a6: each VM render adds only ACX_GPU_OPERATOR_TENANT_IDS=,
# the existing deny-all operator default (pre-existing drift, separate from FIR).
# FIR adds gpu_qwen30b, http://10.0.1.9:8000, an empty endpoint allowlist, and the
# conditionally required host ACX_GPU_ENDPOINT_API_KEY. Its semantic contract is
# covered by test_fir_gpu_manifest.py; local/demo runtime pins remain unchanged.
# sha256 covers ALL sorted runtime assignments plus required-but-unsupplied host
# secret names, using the fake resolver below. Do not filter GPU keys or secrets.
EXISTING_RENDER_GOLDEN = {
    ("svc-local", "local"): ("0b4466bebdf663a9e427912cafdb0dd73085cd3921fc05b71547c2d17b216092", 18),
    ("svc-vm", "dev"): ("0eb822cd23b3a1b612a8a9c0a1a8a16978a831e0ae7d83b1d65f8df9a45c4b18", 46),
    ("svc-vm", "staging"): ("b058595a0477379a799f28b0eba5a73bade97ba095f5596526f8e6e9640f50fa", 38),
    ("svc-vm", "prod"): ("ee903838f3da1384eafbcd795a9dae8774b44a90d062cb087ff82b42faf055c8", 51),
    ("svc-fir", "fir"): ("9c557c835bc7365fa41fe526ff3330520896aa9623fd6224ec1695c9b483d254", 35),
    ("demo", "demo"): ("1b07a0150a4b99495c4caceddc761b6f7b5894398ee27b0c3be07737c2cc7daa", 16),
}


def _identity_expected(label: str) -> dict[str, str]:
    store = label.replace("-", "_")
    return {
        "ACX_ENV": label,
        "COMPOSE_PROJECT_NAME": f"acx-{label}",
        "ACX_IMAGE_TAG": label,
        "ACX_NETWORK_NAME": f"acx-{label}-net",
        "ACX_PGDATA_PATH": f"/opt/acx-backend/data/{label}-pgdata",
        "ACX_MODELS_PATH": f"/opt/acx-backend/data/{label}-models",
        "POSTGRES_DB": f"alt_context_{store}",
        "POSTGRES_USER": f"acx_{store}",
    }


IDENTITY_NAMES = tuple(_identity_expected(AURA_LABELS[0]))
CONFIG_NAMES = IDENTITY_NAMES + tuple(FACE_EXPECTED) + tuple(SECURITY_EXPECTED)
REQUIRED_NAMES = CONFIG_NAMES + STORE_SECRETS


def _expected_config() -> dict[str, dict[str, str]]:
    """Return name -> {aura label: expected rendered value} for every config contract row."""
    table: dict[str, dict[str, str]] = {}
    for label in AURA_LABELS:
        row = {**_identity_expected(label), **FACE_EXPECTED, **SECURITY_EXPECTED}
        for name, value in row.items():
            table.setdefault(name, {})[label] = value
    return table


@functools.lru_cache(maxsize=1)
def _real_manifest():
    return manifest_api.load_manifest(MANIFEST_ROOT)


def _vars_by_name(manifest) -> dict:
    return {var.name: var for var in manifest.vars}


def _declared_var(manifest, name: str):
    var = _vars_by_name(manifest).get(name)
    if var is None:
        pytest.fail(f"{name} is not declared in any manifest fragment")
    return var


def _aura_targets(manifest) -> list[str]:
    return sorted(name for name, target in manifest.targets.items() if set(target.envs) & set(AURA_LABELS))


def _selector_gaps(manifest) -> list[str]:
    names = _aura_targets(manifest)
    if len(names) != 1:
        return [f"expected exactly one target serving {list(AURA_LABELS)}, found {names or 'none'}"]
    envs = set(manifest.targets[names[0]].envs)
    if envs != set(AURA_LABELS):
        return [f"{names[0]}: envs {sorted(envs)} must be exactly {sorted(AURA_LABELS)}"]
    return []


def _aura_target_name(manifest) -> str:
    gaps = _selector_gaps(manifest)
    if gaps:
        pytest.fail("; ".join(gaps))
    return _aura_targets(manifest)[0]


def _target_gaps(manifest) -> list[str]:
    names = _aura_targets(manifest)
    if len(names) != 1:
        return [f"no single Aura target to bind (found {names or 'none'})"]
    target = manifest.targets[names[0]]
    gaps: list[str] = []
    if dict(target.remote_paths) != AURA_REMOTE_PATHS:
        gaps.append(f"{target.name}: remote_paths {dict(target.remote_paths)!r} != {AURA_REMOTE_PATHS!r}")
    if dict(target.lease_env) != AURA_LEASE_ENV:
        gaps.append(f"{target.name}: lease_env {dict(target.lease_env)!r} != {AURA_LEASE_ENV!r}")
    own_paths = set(target.remote_paths.values())
    for other in manifest.targets.values():
        if other.name == target.name:
            continue
        shared = sorted(set(other.remote_paths.values()) & own_paths)
        if shared:
            gaps.append(f"{other.name}: remote path {shared} is shared with an Aura stack")
    by_name = _vars_by_name(manifest)
    for name in REQUIRED_NAMES:
        var = by_name.get(name)
        if var is None:
            continue  # reported by the value gap checks
        if target.name not in var.targets:
            gaps.append(f"{name} is not a variable of {target.name}")
        elif not manifest_api.effective_var(manifest, var, target.name).required:
            gaps.append(f"{name} is not required on {target.name}")
    return gaps


def _value_gaps(manifest, expected_by_name: dict[str, dict[str, str]], *, unique: bool) -> list[str]:
    by_name = _vars_by_name(manifest)
    gaps: list[str] = []
    for name, per_label in expected_by_name.items():
        var = by_name.get(name)
        if var is None:
            gaps.append(f"{name} is not declared in any manifest fragment")
            continue
        for label, expected in per_label.items():
            actual = var.values.get(label)
            if actual != expected:
                gaps.append(f"{name}[{label}] is {actual!r}, expected {expected!r}")
            if unique and actual is not None:
                shared = sorted(env for env, value in var.values.items() if env != label and value == actual)
                if shared:
                    gaps.append(f"{name}[{label}] reuses the value of {shared}")
    return gaps


def _subset(names: tuple[str, ...]) -> dict[str, dict[str, str]]:
    table = _expected_config()
    return {name: table[name] for name in names}


def _identity_gaps(manifest) -> list[str]:
    return _value_gaps(manifest, _subset(IDENTITY_NAMES), unique=True)


def _face_gaps(manifest) -> list[str]:
    return _value_gaps(manifest, _subset(tuple(FACE_EXPECTED)), unique=False)


def _security_gaps(manifest) -> list[str]:
    return _value_gaps(manifest, _subset(tuple(SECURITY_EXPECTED)), unique=False)


def _secret_gaps(manifest) -> list[str]:
    by_name = _vars_by_name(manifest)
    gaps: list[str] = []
    for name in STORE_SECRETS:
        var = by_name.get(name)
        if var is None:
            gaps.append(f"{name} is not declared in any manifest fragment")
            continue
        for label in AURA_LABELS:
            ref = var.secret.get(label)
            if ref is None:
                gaps.append(f"{name}[{label}] has no secret reference")
                continue
            if ref != "host:":
                shared = sorted(env for env, other in var.secret.items() if env != label and other == ref)
                if shared:
                    gaps.append(f"{name}[{label}] reuses secret reference of {shared}")
    return gaps


def _all_gaps(manifest) -> list[str]:
    return (
        _selector_gaps(manifest)
        + _target_gaps(manifest)
        + _identity_gaps(manifest)
        + _face_gaps(manifest)
        + _security_gaps(manifest)
        + _secret_gaps(manifest)
    )


class FakeSecretResolver:
    """Deterministic secret backend stand-in; records every reference it is asked to resolve."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, name: str, reference: str) -> str:
        self.calls.append((name, reference))
        return f"fake({name}|{reference})"


def _render(manifest, target: str, env: str, resolver: FakeSecretResolver, host_lines=None):
    missing: set[str] = set()
    text = render_api.render_target(
        manifest,
        target,
        env,
        resolve=resolver,
        host_lines=host_lines,
        missing_host_keys=missing,
    )
    return text, missing


def _runtime_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.lstrip().startswith("#") and "=" in line]


def _assignments(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _runtime_lines(text):
        name, value = line.split("=", 1)
        values[name] = value.strip("'\"")
    return values


def _fingerprint(manifest, target: str, env: str) -> tuple[str, int]:
    text, missing = _render(manifest, target, env, FakeSecretResolver())
    lines = _runtime_lines(text)
    payload = "\n".join(sorted(lines)) + "\nmissing_host=" + ",".join(sorted(missing))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(lines)


def _with_var(manifest, name: str, mutate: Callable):
    _declared_var(manifest, name)
    return dataclasses.replace(
        manifest,
        vars=tuple(mutate(var) if var.name == name else var for var in manifest.vars),
    )


def _without_value(manifest, name: str, label: str):
    return _with_var(
        manifest,
        name,
        lambda var: dataclasses.replace(var, values={k: v for k, v in var.values.items() if k != label}),
    )


def _generic_part(real, name: str, attribute: str) -> dict[str, str]:
    var = _vars_by_name(real).get(name)
    if var is None:
        return {}
    return {env: value for env, value in getattr(var, attribute).items() if env not in AURA_LABELS}


def _synthetic_manifest(mutate: Callable | None = None):
    """Build an in-memory manifest holding a complete Aura contract plus real generic values.

    Only generic targets are copied from production. Any production target that serves an Aura
    label is dropped first, so the fixture holds exactly one Aura target (the synthetic one)
    whether or not production currently declares its own Aura target.
    """
    real = _real_manifest()
    config = {
        name: {**_generic_part(real, name, "values"), **per_label}
        for name, per_label in _expected_config().items()
    }
    secrets = {
        name: {**_generic_part(real, name, "secret"), **dict.fromkeys(AURA_LABELS, "host:")}
        for name in STORE_SECRETS
    }
    remote = dict(AURA_REMOTE_PATHS)
    if mutate is not None:
        mutate(config, secrets, remote)
    target_name = "svc-aura-synthetic"
    target = manifest_api.Target(
        name=target_name,
        audience="backend",
        envs=AURA_LABELS,
        path=None,
        example=None,
        sections=("Compose",),
        doc=None,
        remote_paths=remote,
        preserve=(),
        lease_env=dict(AURA_LEASE_ENV),
    )
    variables = [
        manifest_api.Var(
            name=name, cls="config", targets=(target_name,), section="Compose", doc="", example="",
            required=True, values=values, secret={}, derive=None, source="synthetic",
        )
        for name, values in config.items()
    ]
    variables += [
        manifest_api.Var(
            name=name, cls="secret", targets=(target_name,), section="Postgres", doc="", example="",
            required=True, values={}, secret=refs, derive=None, source="synthetic",
        )
        for name, refs in secrets.items()
    ]
    generic_targets = {
        name: existing
        for name, existing in real.targets.items()
        if not set(existing.envs) & set(AURA_LABELS)
    }
    targets = {**generic_targets, target_name: target}
    return manifest_api.Manifest(targets=targets, vars=tuple(variables), overrides={})


# ---------------------------------------------------------------------------
# RED: causal contract for the three Aura targets (real production manifest)
# ---------------------------------------------------------------------------


def test_one_manifest_target_serves_exactly_the_three_aura_labels():
    gaps = _selector_gaps(_real_manifest())
    assert not gaps, "\n".join(gaps)


@pytest.mark.parametrize("label", AURA_LABELS)
def test_aura_label_renders_through_the_aura_target(label):
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    text, _ = _render(manifest, target, label, FakeSecretResolver())
    assert f"ACX_ENV={label}" in text


@pytest.mark.parametrize("generic_label", GENERIC_LABELS)
def test_aura_target_refuses_generic_and_fir_labels(generic_label):
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    with pytest.raises(ManifestError, match="unsupported env"):
        _render(manifest, target, generic_label, FakeSecretResolver())


def test_aura_target_binds_stack_paths_lease_labels_and_required_values():
    gaps = _target_gaps(_real_manifest())
    assert not gaps, "\n".join(gaps)


def test_aura_resource_identity_is_declared_per_label_and_never_reused():
    gaps = _identity_gaps(_real_manifest())
    assert not gaps, "\n".join(gaps)


def test_aura_face_pipeline_is_declared_as_auraface_512d_per_label():
    gaps = _face_gaps(_real_manifest())
    assert not gaps, "\n".join(gaps)


def test_aura_auth_on_and_admin_closed_per_label():
    gaps = _security_gaps(_real_manifest())
    assert not gaps, "\n".join(gaps)


def test_aura_store_secret_references_are_declared_and_not_shared_with_other_labels():
    gaps = _secret_gaps(_real_manifest())
    assert not gaps, "\n".join(gaps)


@pytest.mark.parametrize("label", AURA_LABELS)
def test_rendered_aura_env_carries_the_required_identity_face_and_security_values(label):
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    text, missing = _render(manifest, target, label, FakeSecretResolver())
    rendered = _assignments(text)
    expected = {**_identity_expected(label), **FACE_EXPECTED, **SECURITY_EXPECTED}
    mismatched = {name: (rendered.get(name), value) for name, value in expected.items() if rendered.get(name) != value}
    assert not mismatched, f"{label} rendered values differ: {mismatched}"
    unresolved = [name for name in STORE_SECRETS if name not in rendered and name not in missing]
    assert not unresolved, f"{label} renders neither a value nor a required host line for {unresolved}"


@pytest.mark.parametrize("label", AURA_LABELS)
def test_aura_render_resolves_only_its_own_secret_references(label):
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    resolver = FakeSecretResolver()
    _render(manifest, target, label, resolver)
    by_name = _vars_by_name(manifest)
    foreign = []
    for name, reference in resolver.calls:
        var = by_name.get(name)
        if var is None or var.secret.get(label) != reference or any(env != label and other == reference for env, other in var.secret.items()):
            foreign.append((name, reference))
    assert not foreign, f"{label} resolved references it does not own: {foreign}"


@pytest.mark.parametrize(
    ("label", "name"),
    [
        (label, name)
        for label in AURA_LABELS
        for name in (
            "ACX_PGDATA_PATH",
            "ACX_NETWORK_NAME",
            "POSTGRES_DB",
            "PGVECTOR_DIM",
            "RECOGNITION_FACE_PIPELINE_PROFILE",
            "RECOGNITION_AURAFACE_MODELS_DIR",
        )
    ],
)
def test_missing_required_identity_or_face_value_refuses_render(label, name):
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    _declared_var(manifest, name)
    mutated = _without_value(manifest, name, label)
    with pytest.raises(ManifestError, match="missing value") as info:
        render_api.render_target(
            mutated, target, label, resolve=FakeSecretResolver(), missing_host_keys=set()
        )
    assert name in str(info.value)


@pytest.mark.parametrize("label", AURA_LABELS)
@pytest.mark.parametrize("name", STORE_SECRETS)
def test_store_secret_requirement_follows_its_declared_scheme(label, name):
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    ref = _declared_var(manifest, name).secret.get(label)
    assert ref is not None, f"{name}[{label}] has no secret reference"
    _, missing = _render(manifest, target, label, FakeSecretResolver())
    if ref == "host:":
        assert name in missing, f"{name}[{label}] is a host secret but is not demanded when its line is absent"
        supplied = {
            other: [f"{other}=fake-{other}"]
            for other in STORE_SECRETS
            if other != name and _declared_var(manifest, other).secret.get(label) == "host:"
        }
        with pytest.raises(ManifestError, match=name):
            render_api.render_target(
                manifest, target, label, resolve=FakeSecretResolver(),
                host_lines=supplied, missing_host_keys=None,
            )
    else:
        assert name not in missing, f"{name}[{label}] is not a host secret yet demands a host line"


def test_aura_example_is_generated_from_the_target_render():
    manifest = _real_manifest()
    target = _aura_target_name(manifest)
    gaps = render_api.check_example(manifest, target, REPO)
    assert gaps == [], gaps


# ---------------------------------------------------------------------------
# Healthy controls: must pass against the accepted production contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("target", "env"), list(EXISTING_RENDER_GOLDEN))
def test_existing_target_runtime_render_is_unchanged(target, env):
    assert _fingerprint(_real_manifest(), target, env) == EXISTING_RENDER_GOLDEN[(target, env)]


def test_fir_stack_keeps_its_sface_128_identity_and_gains_no_aura_path():
    manifest = _real_manifest()
    text, _ = _render(manifest, "svc-fir", "fir", FakeSecretResolver())
    rendered = _assignments(text)
    mismatched = {k: (rendered.get(k), v) for k, v in FIR_CONTROL.items() if rendered.get(k) != v}
    assert not mismatched, mismatched
    assert "RECOGNITION_AURAFACE_MODELS_DIR" not in rendered


@pytest.mark.parametrize("target", GENERIC_TARGETS)
def test_generic_targets_refuse_every_aura_label(target):
    manifest = _real_manifest()
    for label in AURA_LABELS:
        with pytest.raises(ManifestError, match="unsupported env"):
            _render(manifest, target, label, FakeSecretResolver())


def test_gap_gate_accepts_a_complete_synthetic_aura_contract():
    assert _all_gaps(_synthetic_manifest()) == []


MUTATIONS = [
    pytest.param(
        lambda c, s, r: c["ACX_PGDATA_PATH"].update({"dev-auraface": "/opt/acx-backend/data/dev-pgdata"}),
        "ACX_PGDATA_PATH[dev-auraface] reuses",
        id="generic-dev-pgdata",
    ),
    pytest.param(
        lambda c, s, r: c["ACX_NETWORK_NAME"].update({"prod-auraface": c["ACX_NETWORK_NAME"]["dev-auraface"]}),
        "ACX_NETWORK_NAME[prod-auraface] reuses",
        id="sibling-network",
    ),
    pytest.param(
        lambda c, s, r: c["POSTGRES_DB"].update({"staging-auraface": "alt_context_dev_fir"}),
        "POSTGRES_DB[staging-auraface] reuses",
        id="fir-database",
    ),
    pytest.param(
        lambda c, s, r: c["RECOGNITION_FACE_PIPELINE_PROFILE"].pop("staging-auraface"),
        "RECOGNITION_FACE_PIPELINE_PROFILE[staging-auraface] is None",
        id="missing-profile",
    ),
    pytest.param(
        lambda c, s, r: c["PGVECTOR_DIM"].update({"dev-auraface": "128"}),
        "PGVECTOR_DIM[dev-auraface] is '128'",
        id="fir-width",
    ),
    pytest.param(
        lambda c, s, r: s["POSTGRES_DSN"].update({"prod-auraface": s["POSTGRES_DSN"]["prod"]}),
        "POSTGRES_DSN[prod-auraface] reuses secret reference",
        id="generic-prod-dsn-reference",
    ),
    pytest.param(
        lambda c, s, r: r.update({"dev-auraface": "/opt/acx-backend/dev/.env"}),
        "is shared with an Aura stack",
        id="generic-stack-file",
    ),
    pytest.param(
        lambda c, s, r: c["RECOGNITION_ADMIN_ENABLED"].update({"prod-auraface": "true"}),
        "RECOGNITION_ADMIN_ENABLED[prod-auraface] is 'true'",
        id="admin-open-on-prod",
    ),
]


@pytest.mark.parametrize(("mutate", "expected"), MUTATIONS)
def test_gap_gate_refuses_each_substitution_or_omission(mutate, expected):
    gaps = _all_gaps(_synthetic_manifest(mutate))
    assert any(expected in gap for gap in gaps), gaps
