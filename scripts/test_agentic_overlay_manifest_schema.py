from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / ".agentic-overlay.json"
LOCAL_ROOTS = {
    "skills": REPO_ROOT / "local" / ".claude" / "skills",
    "hooks": REPO_ROOT / "local" / ".github" / "hooks",
    "commands": REPO_ROOT / "local" / ".claude" / "commands",
    "prompts": REPO_ROOT / "local" / ".github" / "prompts",
    "contracts": REPO_ROOT / "local" / "docs" / "agentic" / "contracts",
}
EXPECTED_SURFACES = {
    "skills": {
        "shared_root": ".agentic/remote/.claude/skills",
        "local_root": "local/.claude/skills",
    },
    "hooks": {
        "shared_root": ".agentic/remote/.github/hooks",
        "local_root": "local/.github/hooks",
    },
    "commands": {
        "shared_root": ".agentic/remote/.claude/commands",
        "local_root": "local/.claude/commands",
    },
    "prompts": {
        "shared_root": ".agentic/remote/.github/prompts",
        "local_root": "local/.github/prompts",
    },
    "contracts": {
        "shared_root": ".agentic/remote/docs/agentic/contracts",
        "local_root": "local/docs/agentic/contracts",
    },
}


def test_overlay_consumer_manifest_and_local_roots_exist() -> None:
    assert MANIFEST_PATH.is_file(), (
        ".agentic-overlay.json is missing even though Slice 4 is supposed to cut the monorepo over to the bootstrap-managed shared surface"
    )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest.get("schema_version") == 1, "overlay manifest schema_version must stay pinned to 1"
    assert manifest.get("remote_clone_path") == ".agentic/remote", (
        "overlay manifest must point shared surfaces at the bootstrap-managed .agentic/remote clone"
    )

    surfaces = manifest.get("surfaces")
    assert isinstance(surfaces, dict), "overlay manifest must define a surfaces mapping"
    assert surfaces == EXPECTED_SURFACES, (
        "overlay manifest must declare the shared/local roots for skills, hooks, commands, prompts, and contracts"
    )

    for name, path in LOCAL_ROOTS.items():
        assert path.is_dir(), f"missing local override root for {name}: {path.relative_to(REPO_ROOT)}"