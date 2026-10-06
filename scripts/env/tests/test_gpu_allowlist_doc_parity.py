from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config/env/manifest.d/21-service-vm.toml"
RUNTIME_PATH = REPO_ROOT / "apps/prototype-description-service/scene/interface_adapters/http/deps.py"
PREFLIGHT_PATH = REPO_ROOT / "scripts/deploy/preflight-gpu-env.sh"
ALLOWLIST_VAR = "ACX_GPU_ENDPOINT_ALLOWLIST"


def _runtime_default_patterns() -> set[str]:
    module = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "_DEFAULT_GPU_ENDPOINT_ALLOWLIST"
            for target in node.targets
        ):
            patterns = ast.literal_eval(node.value)
            assert isinstance(patterns, tuple)
            return set(patterns)
    raise AssertionError("runtime GPU endpoint allowlist default was not found")


def _preflight_default_patterns(source: str | None = None) -> set[str]:
    if source is None:
        source = PREFLIGHT_PATH.read_text(encoding="utf-8")
    matches = re.findall(r'^\s*allowlist="\$\{allowlist:-([^}]*)\}"\s*$', source, re.MULTILINE)
    assert len(matches) == 1
    return {pattern.strip() for pattern in matches[0].split(",") if pattern.strip()}


def _manifest_allowlist_doc() -> str:
    manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    variable = next((var for var in manifest["var"] if var["name"] == ALLOWLIST_VAR), None)
    assert variable is not None
    return variable["doc"]


def _assert_runtime_and_preflight_defaults_match(runtime_patterns: set[str], preflight_patterns: set[str]) -> None:
    assert runtime_patterns == preflight_patterns


def test_gpu_allowlist_defaults_match_and_are_documented() -> None:
    runtime_patterns = _runtime_default_patterns()
    preflight_patterns = _preflight_default_patterns()
    _assert_runtime_and_preflight_defaults_match(runtime_patterns, preflight_patterns)

    doc = _manifest_allowlist_doc()
    assert all(pattern in doc for pattern in runtime_patterns)
