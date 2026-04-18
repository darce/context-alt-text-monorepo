"""Probe 4: test project-scoped skills (.codex/skills/) and user-scoped symlinks."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "packages" / "codex-subagent-bridge" / "src"))
from codex_subagent_bridge import AppServerClient


def names_scopes(r):
    out = []
    for e in r.get("data", []):
        for s in e.get("skills", []):
            out.append((s.get("name"), s.get("scope")))
    return sorted(out)


# Temporarily create a symlink/dir inside .codex/skills/ to test project-scope
proj_skills = REPO / ".codex" / "skills"
created = False
if not proj_skills.exists():
    proj_skills.mkdir(parents=True)
    (proj_skills / "probe-test").mkdir()
    (proj_skills / "probe-test" / "SKILL.md").write_text(
        "---\nname: probe-test\ndescription: E17-12 project-scope probe. Remove after.\n---\n\n# Probe Test\nTemporary.\n"
    )
    created = True
    print(f"Created temporary {proj_skills}/probe-test")

client = AppServerClient(cwd=str(REPO), env=dict(os.environ))
client.start()
try:
    client.initialize()
    r = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
    print("project-scope probe:", names_scopes(r))
finally:
    client.close()
    if created:
        shutil.rmtree(proj_skills)
        print(f"Removed {proj_skills}")
