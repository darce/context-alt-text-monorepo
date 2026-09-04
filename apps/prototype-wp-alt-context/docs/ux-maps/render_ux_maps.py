#!/usr/bin/env python3
"""Deterministically render `<map_ref>.md` from `<map_ref>.uxmap.json`.

The `.uxmap.json` is the SSOT (DATA-14: one authority owns the record). This script is
the only sanctioned writer of the machine region of the sibling `.md`, so the two never
become independent hand-maintained copies (REF-09: a derived artifact that is hand-edited
drifts silently).

It wraps `workbay_canvas_mcp.ux_map.render_markdown.render_markdown_bundle` and adds the
per-screen inventory blocks (purpose / url_params / zone table) and the parity index that
`js/admin/__tests__/uxmap-render-parity.test.ts` asserts against.

Hand-authored prose sections listed in `KEEP_SECTIONS` are lifted out of the existing
`.md` and re-injected verbatim, so narrative that the structural renderer cannot express
survives a regeneration.

Usage (the canvas package is not a declared dependency of this app; point PYTHONPATH at
an installed copy):

    PYTHONPATH=<parent-of-workbay_canvas_mcp> python3 docs/ux-maps/render_ux_maps.py \
        workbench-2pane describe-gpu-tier
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAPS_DIR = Path(__file__).resolve().parent

# Hand-authored sections preserved across regeneration. Order is significant and stable.
KEEP_SECTIONS = (
    "## Vocabulary (say / don't say)",
    "## Operator interaction contract",
    "## Detailed reducer and recovery contract",
)


def _load_renderer():
    try:
        from workbay_canvas_mcp.ux_map.models import UxMap
        from workbay_canvas_mcp.ux_map.render_markdown import render_markdown_bundle
    except ImportError as exc:  # pragma: no cover - operator-facing guidance
        raise SystemExit(
            "workbay_canvas_mcp is not importable. Install mcp-workbay-canvas or set "
            "PYTHONPATH to a checkout/venv that contains it, then re-run."
        ) from exc
    return UxMap, render_markdown_bundle


def _zone_table(screen: dict) -> list[str]:
    rows = ["| zone id | label | role | states |", "| --- | --- | --- | --- |"]
    for zone in screen.get("zones", []):
        label = zone["label"].replace("|", "\\|")
        states = ", ".join(zone.get("states", []))
        rows.append(f"| `{zone['id']}` | {label} | {zone['role']} | {states} |")
    return rows


def _screen_block(screen: dict) -> list[str]:
    out: list[str] = []
    if screen.get("purpose"):
        out += [f"Purpose: {screen['purpose']}", ""]
    params = screen.get("url_params") or []
    if params:
        out += ["url_params: " + ", ".join(f"`{p}`" for p in params), ""]
    if screen.get("zones"):
        out += _zone_table(screen) + [""]
    return out


def _parity_index(doc: dict) -> list[str]:
    zone_ids: list[str] = []
    labels: list[str] = []
    for screen in doc["screens"]:
        for zone in screen.get("zones", []):
            zone_ids.append(zone["id"])
            labels.append(zone["label"])
    action_ids = [action["id"] for action in doc.get("actions", [])]
    states: list[str] = []
    for screen in doc["screens"]:
        for state in screen.get("states", []):
            if state not in states:
                states.append(state)
        for zone in screen.get("zones", []):
            for state in zone.get("states", []):
                if state not in states:
                    states.append(state)
    return [
        "## Parity index",
        "",
        "Machine-checked by `js/admin/__tests__/uxmap-parity.test.ts` and",
        "`js/admin/__tests__/uxmap-render-parity.test.ts`: every id, state, and verbatim label",
        "below must exist in the sibling `.uxmap.json`, and no `z-*`/`act-*` id may appear here",
        "that the JSON does not define. Regenerate with `docs/ux-maps/render_ux_maps.py` — never",
        "hand-edit one side.",
        "",
        "Zone ids: " + " ".join(zone_ids),
        "",
        "Action ids: " + " ".join(action_ids),
        "",
        "Zone labels (verbatim; the tables above escape `|` for markdown, this list does not):",
        "",
        *[f"- {label}" for label in labels],
        "",
        "States (all zones and screens): " + " ".join(states),
        "",
    ]


def _action_table(doc: dict) -> list[str]:
    rows = [
        "## Actions",
        "",
        "| id | verb | target | hierarchy | costly | irreversible | preview required | screen id |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for action in doc.get("actions", []):
        def escaped(key: str) -> str:
            return str(action.get(key, "")).replace("|", "\\|")

        screen_id = f"`{escaped('screen_id')}`" if action.get("screen_id") else "—"
        rows.append(
            f"| `{escaped('id')}` | {escaped('verb')} | `{escaped('target')}` | "
            f"{escaped('hierarchy')} | {'yes' if action.get('costly') else 'no'} | "
            f"{'yes' if action.get('irreversible') else 'no'} | "
            f"{'yes' if action.get('preview_required') else 'no'} | {screen_id} |"
        )
    return rows + [""]


def _domain_state_mapping(doc: dict) -> list[str]:
    mappings = doc.get("domain_state_mappings", [])
    if not mappings:
        return []
    rows = [
        "## Domain state mapping",
        "",
        "| domain state(s) | canonical state |",
        "| --- | --- |",
    ]
    for mapping in mappings:
        domain_states = ", ".join(f"`{state}`" for state in mapping["domain_states"])
        rows.append(f"| {domain_states} | `{mapping['canonical_state']}` |")
    return rows + [""]


def _extract_kept(md_path: Path) -> list[str]:
    if not md_path.exists():
        return []
    text = md_path.read_text(encoding="utf8")
    kept: list[str] = []
    for heading in KEEP_SECTIONS:
        match = re.search(rf"^{re.escape(heading)}$.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if match:
            kept += match.group(0).rstrip("\n").split("\n") + [""]
    return kept


def render(map_ref: str) -> str:
    ux_map_model, render_markdown_bundle = _load_renderer()
    doc = json.loads((MAPS_DIR / f"{map_ref}.uxmap.json").read_text(encoding="utf8"))
    # Local render extensions are lossless tables appended around the upstream bundle;
    # keep them out of the strict upstream Pydantic model and render them below.
    canonical_doc = {key: value for key, value in doc.items() if key != "domain_state_mappings"}
    bundle = render_markdown_bundle(ux_map_model.model_validate(canonical_doc)).split("\n")
    screens = {screen["id"]: screen for screen in doc["screens"]}

    out: list[str] = []
    kept = _extract_kept(MAPS_DIR / f"{map_ref}.md")
    kept_emitted = not kept

    for line in bundle:
        if not kept_emitted and line.startswith("## "):
            out += kept
            kept_emitted = True
        if line == "## Flows":
            out += _action_table(doc)
        if line == "## Not doing":
            out += _domain_state_mapping(doc)
            out += _parity_index(doc)
        out.append(line)
        heading = re.match(r"^### .*\(`([a-z0-9_-]+)`\)$", line)
        if heading and heading.group(1) in screens:
            out.append("")
            out += _screen_block(screens[heading.group(1)])
            # `_screen_block` ends with a blank line; drop the duplicate blank the bundle
            # emits immediately after the heading.
            if out and out[-1] == "":
                out.pop()
    return "\n".join(out)


def main(argv: list[str]) -> int:
    refs = argv[1:] or [path.name[: -len(".uxmap.json")] for path in sorted(MAPS_DIR.glob("*.uxmap.json"))]
    for ref in refs:
        target = MAPS_DIR / f"{ref}.md"
        target.write_text(render(ref), encoding="utf8")
        print(f"rendered {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
