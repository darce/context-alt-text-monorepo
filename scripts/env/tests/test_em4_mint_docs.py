from __future__ import annotations

import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config/env/manifest.d/21-service-vm.toml"


def test_gpu_mint_manifest_docs_match_mint_flow() -> None:
    with MANIFEST_PATH.open("rb") as manifest_file:
        manifest = tomllib.load(manifest_file)

    entries = [*manifest.get("override", []), *manifest.get("var", [])]
    entries_by_name = {entry["name"]: entry for entry in entries}
    docs = "\n".join(
        entries_by_name[name].get("doc", "")
        for name in (
            "RECOGNITION_VAULT_SECRET_MAP",
            "ACX_DESCRIPTION_ADAPTER",
            "ACX_GPU_ENDPOINT_API_KEY",
        )
    )
    normalized_docs = " ".join(docs.split())

    assert 'GPU_KEY_MINT_ARGS="--approve-mint' in docs
    assert "make env-examples" in docs
    assert "derives automatically" in docs
    assert re.search(
        r"\badd\b.{0,80}\bOCID\b.{0,80}RECOGNITION_VAULT_SECRET_MAP",
        normalized_docs,
        flags=re.IGNORECASE,
    ) is None
