from __future__ import annotations

from pathlib import Path

import pytest

from conftest import load_module


REPO = Path(__file__).resolve().parents[3]


def collect_remote_pairs(manifest):
    return {
        (target_name, env)
        for target_name, target in manifest.targets.items()
        if target.remote_paths
        for env in target.envs
    }


def assert_required_remote_pairs(remote_pairs):
    expected_pairs = {
        ("svc-vm", "dev"),
        ("svc-vm", "staging"),
        ("svc-vm", "prod"),
        ("svc-fir", "fir"),
        ("demo", "demo"),
    }
    missing_pairs = expected_pairs - remote_pairs
    assert not missing_pairs, "missing remote deployment pairs: " + ", ".join(
        f"{target_name}:{env}" for target_name, env in sorted(missing_pairs)
    )


def test_remote_deployment_pair_guard_rejects_missing_prod():
    manifest = load_module("manifest").load_manifest(REPO / "config/env")
    remote_pairs = collect_remote_pairs(manifest) - {("svc-vm", "prod")}

    with pytest.raises(AssertionError, match="missing remote deployment pairs: svc-vm:prod"):
        assert_required_remote_pairs(remote_pairs)


def test_remote_targets_have_required_nonsecret_values_for_every_env():
    manifest_module = load_module("manifest")
    render_module = load_module("render_env")
    manifest = manifest_module.load_manifest(REPO / "config/env")
    assert_required_remote_pairs(collect_remote_pairs(manifest))
    missing = []
    remote_envs = []

    for target_name, target in manifest.targets.items():
        if not target.remote_paths:
            continue
        target_vars = [
            manifest_module.effective_var(manifest, var, target_name)
            for var in manifest.vars
            if target_name in var.targets
        ]
        for env in target.envs:
            remote_envs.append((target_name, env, target_vars))
            missing.extend(
                f"{target_name}:{env}:{var.name}"
                for var in target_vars
                if var.cls in {"config", "public"}
                and var.required
                and var.derive is None
                and not var.derive_vault_map
                and env not in var.values
            )

    assert not missing, "required remote config vars lack per-env values: " + ", ".join(missing)

    for target_name, env, target_vars in remote_envs:
        fake_host_lines = {
            var.name: [f"{var.name}=fake-secret"]
            for var in target_vars
            if var.cls == "secret" and var.secret.get(env) == "host:"
        }
        render_module.render_target(
            manifest,
            target_name,
            env,
            resolve=lambda name, _reference: f"fake-{name}",
            host_lines=fake_host_lines,
        )
