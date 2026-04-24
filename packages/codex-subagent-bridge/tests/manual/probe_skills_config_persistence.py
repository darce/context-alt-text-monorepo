"""Probe round 3: persistence + static config search."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "packages" / "codex-subagent-bridge" / "src"))

from codex_subagent_bridge import AppServerClient


def names(r):
    out = []
    for e in r.get("data", []):
        for s in e.get("skills", []):
            out.append(s.get("name"))
    return sorted(out)


def probe():
    client = AppServerClient(cwd=str(REPO), env=dict(os.environ))
    client.start()
    skills_root = str(REPO / ".claude" / "skills")
    try:
        client.initialize()

        # Baseline: no extra roots
        r1 = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
        print("before:", names(r1))

        # Register via perCwdExtraUserRoots
        r2 = client._request(
            "skills/list",
            {
                "cwds": [str(REPO)],
                "forceReload": True,
                "perCwdExtraUserRoots": [{"cwd": str(REPO), "extraUserRoots": [skills_root]}],
            },
        )
        print("with_roots:", names(r2))

        # Next call, SAME session, no perCwdExtraUserRoots — does it stick?
        r3 = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
        print("after (no param):", names(r3))

        # Try skills/config/write to 'register' a root directly
        try:
            r4 = client._request(
                "skills/config/write",
                {
                    "enabled": True,
                    "path": skills_root,
                },
            )
            print("config/write dir:", r4)
        except Exception as exc:
            print("config/write dir ERROR:", exc)

        # Recheck
        r5 = client._request("skills/list", {"cwds": [str(REPO)], "forceReload": True})
        print("after config/write:", names(r5))

    finally:
        client.close()


if __name__ == "__main__":
    probe()
