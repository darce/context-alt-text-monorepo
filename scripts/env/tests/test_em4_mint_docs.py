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
    manifest_docs = [
        entries_by_name[name].get("doc", "")
        for name in (
            "RECOGNITION_VAULT_SECRET_MAP",
            "ACX_DESCRIPTION_ADAPTER",
            "ACX_GPU_ENDPOINT_API_KEY",
        )
    ]
    docs = "\n".join(manifest_docs)
    normalized_docs = " ".join(docs.split())
    rendered_example = (
        REPO_ROOT / "apps/prototype-description-service/.env.prod.example"
    ).read_text()

    assert 'GPU_KEY_MINT_ARGS="--approve-mint"' in docs
    for text in (*manifest_docs, rendered_example):
        assert "--ssh-target" not in text
        assert "approved-vm" not in text
    mint_command = 'make gpu-key-mint GPU_KEY_MINT_ARGS="--approve-mint"'
    for doc in manifest_docs:
        assert mint_command in [line.strip() for line in doc.splitlines()]
    rendered_lines = [
        line.removeprefix("# ").strip() for line in rendered_example.splitlines()
    ]
    assert rendered_lines.count(mint_command) == len(manifest_docs)
    assert "make env-examples" in docs
    assert "derives automatically" in docs
    assert re.search(
        r"\badd\b.{0,80}\bOCID\b.{0,80}RECOGNITION_VAULT_SECRET_MAP",
        normalized_docs,
        flags=re.IGNORECASE,
    ) is None
