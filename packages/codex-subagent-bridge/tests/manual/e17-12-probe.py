"""E17-12 Slice 1 probe: drive live Codex app-server and test skill-root registration paths.

Not committed. Output is summarized into the discovery report.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'packages' / 'codex-subagent-bridge' / 'src'))

from codex_subagent_bridge import AppServerClient  # noqa: E402


def dump(label: str, obj):
    print(f"\n=== {label} ===")
    print(json.dumps(obj, indent=2, default=str)[:4000])


def probe():
    client = AppServerClient(cwd=str(REPO), env=dict(os.environ))
    client.start()
    try:
        init = client.initialize()
        dump("initialize", init)

        # Check what capabilities the server advertises for skills.
        caps = init.get("capabilities") if isinstance(init, dict) else None
        dump("server capabilities", caps)

        # Path (c) RPC probe: skills/list
        try:
            r = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
            dump("skills/list (cwds only)", r)
        except Exception as exc:
            dump("skills/list (cwds only) ERROR", str(exc))

        # Try perCwdExtraUserRoots with the repo .claude/skills path
        skills_root = REPO / ".claude" / "skills"
        try:
            r = client._request("skills/list", {
                "cwds": [str(REPO)],
                "forceReload": True,
                "perCwdExtraUserRoots": {str(REPO): [str(skills_root)]},
            })
            dump("skills/list (perCwdExtraUserRoots repo .claude/skills)", r)
        except Exception as exc:
            dump("skills/list (perCwdExtraUserRoots) ERROR", str(exc))

        # skills/config/write with an in-repo path
        target_skill = skills_root / "branch-review" / "SKILL.md"
        try:
            r = client._request("skills/config/write", {
                "enabled": True,
                "path": str(target_skill),
            })
            dump("skills/config/write (branch-review)", r)
        except Exception as exc:
            dump("skills/config/write ERROR", str(exc))

        # Re-list after config/write
        try:
            r = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
            dump("skills/list (after config/write)", r)
        except Exception as exc:
            dump("skills/list (after config/write) ERROR", str(exc))

    finally:
        client.close()


if __name__ == "__main__":
    probe()
