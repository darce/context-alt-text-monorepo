"""Probe 4: test project-scoped skills (.codex/skills/) and user-scoped symlinks.

E17-12-BR-03: always create a dedicated temporary `probe-test` entry under
`.codex/skills/` regardless of whether the parent directory already exists,
and always clean it up. Avoids silently skipping the discovery check in the
shipped-repo condition where `.codex/skills/` already contains generated
symlinks.
"""

from __future__ import annotations

import os
import shutil
import sys
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


proj_skills = REPO / ".codex" / "skills"
proj_skills.mkdir(parents=True, exist_ok=True)

probe_dir = proj_skills / "probe-test"
if probe_dir.exists() or probe_dir.is_symlink():
    raise SystemExit(
        f"Refusing to overwrite pre-existing {probe_dir}; remove it and rerun."
    )

probe_dir.mkdir()
(probe_dir / "SKILL.md").write_text(
    "---\nname: probe-test\ndescription: E17-12 project-scope probe. Remove after.\n---\n\n# Probe Test\nTemporary.\n"
)
print(f"Created temporary {probe_dir}")

client = AppServerClient(cwd=str(REPO), env=dict(os.environ))
client.start()
try:
    client.initialize()
    r = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
    print("project-scope probe:", names_scopes(r))
finally:
    client.close()
    shutil.rmtree(probe_dir)
    print(f"Removed {probe_dir}")
