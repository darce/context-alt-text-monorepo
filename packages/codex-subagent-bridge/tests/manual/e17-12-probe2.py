"""E17-12 Slice 1 probe (round 2): retry perCwdExtraUserRoots with sequence shape."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "packages" / "codex-subagent-bridge" / "src"))

from codex_subagent_bridge import AppServerClient


def dump(label, obj):
    print(f"\n=== {label} ===")
    s = json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj
    print(s[:6000])


def name_list(resp):
    try:
        entries = resp.get("data", []) if isinstance(resp, dict) else []
        out = []
        for e in entries:
            for s in e.get("skills", []):
                out.append((s.get("name"), s.get("scope"), s.get("path")))
        return out
    except Exception as exc:
        return [("ERR", str(exc), "")]


def probe():
    client = AppServerClient(cwd=str(REPO), env=dict(os.environ))
    client.start()
    skills_root = str(REPO / ".claude" / "skills")
    try:
        client.initialize()

        # Shape A: list of paths (no cwd key)
        try:
            r = client._request(
                "skills/list",
                {
                    "cwds": [str(REPO)],
                    "forceReload": True,
                    "perCwdExtraUserRoots": [skills_root],
                },
            )
            dump("A: perCwdExtraUserRoots=[path]", name_list(r))
        except Exception as exc:
            dump("A ERROR", str(exc))

        # Shape B: list of {cwd, roots}
        try:
            r = client._request(
                "skills/list",
                {
                    "cwds": [str(REPO)],
                    "forceReload": True,
                    "perCwdExtraUserRoots": [{"cwd": str(REPO), "roots": [skills_root]}],
                },
            )
            dump("B: [{cwd,roots:[path]}]", name_list(r))
        except Exception as exc:
            dump("B ERROR", str(exc))

        # Shape C: list of {cwd, extraUserRoots}
        try:
            r = client._request(
                "skills/list",
                {
                    "cwds": [str(REPO)],
                    "forceReload": True,
                    "perCwdExtraUserRoots": [{"cwd": str(REPO), "extraUserRoots": [skills_root]}],
                },
            )
            dump("C: [{cwd,extraUserRoots}]", name_list(r))
        except Exception as exc:
            dump("C ERROR", str(exc))

        # Shape D: top-level extraUserRoots
        try:
            r = client._request(
                "skills/list",
                {
                    "cwds": [str(REPO)],
                    "forceReload": True,
                    "extraUserRoots": [skills_root],
                },
            )
            dump("D: extraUserRoots=[path]", name_list(r))
        except Exception as exc:
            dump("D ERROR", str(exc))

        # E: Inspect checked-in protocol fixture if available
        fixture = (
            REPO
            / "packages"
            / "codex-subagent-bridge"
            / "tests"
            / "fixtures"
            / "codex_app_server_protocol.v2.schemas.json"
        )
        if fixture.exists():
            schema = json.loads(fixture.read_text())
            for key in ("skills/list", "skills/config/write"):
                node = schema.get(key) or schema.get("methods", {}).get(key)
                dump(f"fixture:{key}", node)
            # also dump top-level keys
            dump("fixture top-level keys", list(schema.keys())[:50])
    finally:
        client.close()


if __name__ == "__main__":
    probe()
