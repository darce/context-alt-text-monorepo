from __future__ import annotations

from pathlib import Path

from conftest import load_module


REPO = Path(__file__).resolve().parents[3]


def test_remote_targets_have_required_nonsecret_values_for_every_env():
    manifest_module = load_module("manifest")
    render_module = load_module("render_env")
    manifest = manifest_module.load_manifest(REPO / "config/env")
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
