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
`.md` and re-injected verbatim at their original generated-heading anchors, so narrative
that the structural renderer cannot express survives a regeneration without moving.

Usage (the canvas package is optional and only required when writing artifacts):

    PYTHONPATH=<parent-of-workbay_canvas_mcp> python3 docs/ux-maps/render_ux_maps.py \
        workbench-2pane describe-gpu-tier

    python3 docs/ux-maps/render_ux_maps.py --check
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from difflib import unified_diff
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
        raise ImportError(
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


def _ascii_state_rows(states: list[str], width: int = 60) -> list[str]:
    """Render every state without changing the renderer's canonical frame width."""
    if not states:
        return []
    rows: list[str] = []
    content = " states: "
    for state in states:
        suffix = state if content.endswith(": ") else f" | {state}"
        if len(content) + len(suffix) > width:
            rows.append(f"|{content.ljust(width)}|")
            content = f" states+: {state}"
        else:
            content += suffix
    rows.append(f"|{content.ljust(width)}|")
    return rows


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


def _extract_kept_text(text: str, headings: tuple[str, ...] = KEEP_SECTIONS) -> list[tuple[str | None, str]]:
    """Capture each kept section and the generated heading that originally followed it."""
    heading_matches = list(re.finditer(r"^## .+$", text, re.MULTILINE))
    kept: list[tuple[int, str | None, str]] = []
    for heading in headings:
        match = re.search(rf"^{re.escape(heading)}$", text, re.MULTILINE)
        if not match:
            continue
        following = next((item for item in heading_matches if item.start() > match.start()), None)
        end = following.start() if following else len(text)
        anchor = following.group(0) if following else None
        kept.append((match.start(), anchor, text[match.start():end].strip("\n")))
    return [(anchor, section) for _, anchor, section in sorted(kept)]


def _extract_kept(md_path: Path) -> list[tuple[str | None, str]]:
    if not md_path.exists():
        return []
    return _extract_kept_text(md_path.read_text(encoding="utf8"))


def _restore_kept(generated: str, kept: list[tuple[str | None, str]]) -> str:
    """Restore preserved sections immediately before the same following heading."""
    anchored: dict[str | None, list[str]] = {}
    for anchor, section in kept:
        anchored.setdefault(anchor, []).append(section)

    restored = generated
    for anchor, sections in anchored.items():
        insertion = "\n\n".join(section.strip("\n") for section in sections) + "\n\n"
        if anchor is None:
            restored = restored.rstrip("\n") + "\n\n" + insertion.rstrip("\n") + "\n"
            continue
        marker = f"{anchor}\n"
        position = restored.find(marker)
        if position < 0:
            raise ValueError(f"cannot restore kept section: anchor {anchor!r} is absent from generated output")
        restored = restored[:position] + insertion + restored[position:]
    return restored


def render(map_ref: str) -> str:
    ux_map_model, render_markdown_bundle = _load_renderer()
    doc = json.loads((MAPS_DIR / f"{map_ref}.uxmap.json").read_text(encoding="utf8"))
    # Local render extensions are lossless tables appended around the upstream bundle;
    # keep them out of the strict upstream Pydantic model and render them below.
    canonical_doc = {key: value for key, value in doc.items() if key != "domain_state_mappings"}
    bundle = render_markdown_bundle(ux_map_model.model_validate(canonical_doc)).split("\n")
    screens = {screen["id"]: screen for screen in doc["screens"]}
    flows = {flow["id"]: flow for flow in doc["flows"]}

    out: list[str] = []
    kept = _extract_kept(MAPS_DIR / f"{map_ref}.md")
    active_flow: dict | None = None
    active_screen: dict | None = None

    for line in bundle:
        if line == "## Flows":
            out += _action_table(doc)
        if line == "## Not doing":
            out += _domain_state_mapping(doc)
            out += _parity_index(doc)
        if active_screen is not None and line.startswith("| states:"):
            out += _ascii_state_rows(active_screen.get("states", []))
            continue
        out.append(line)
        heading = re.match(r"^### .*\(`([a-z0-9_-]+)`\)$", line)
        if heading and heading.group(1) in flows:
            active_flow = flows[heading.group(1)]
        if active_flow is not None and line.lstrip().startswith("%% flow:"):
            steps = [
                {
                    "screen_id": step["screen_id"],
                    "branch_label": step.get("branch_label"),
                }
                for step in active_flow["steps"]
            ]
            out.append("  %% steps: " + json.dumps(steps, ensure_ascii=False, separators=(",", ":")))
            active_flow = None
        if heading and heading.group(1) in screens:
            active_screen = screens[heading.group(1)]
            out.append("")
            out += _screen_block(screens[heading.group(1)])
            # `_screen_block` ends with a blank line; drop the duplicate blank the bundle
            # emits immediately after the heading.
            if out and out[-1] == "":
                out.pop()
    return _restore_kept("\n".join(out), kept)


def _check_projection(map_ref: str) -> tuple[str, str]:
    """Return expected/actual lossless projections without importing the optional renderer."""
    repo_root = MAPS_DIR.parents[3]
    parity_module = repo_root / "apps/prototype-wp-alt-context/js/admin/uxmap/renderParity.ts"
    json_path = MAPS_DIR / f"{map_ref}.uxmap.json"
    markdown_path = MAPS_DIR / f"{map_ref}.md"
    script = "\n".join(
        [
            "import fs from 'node:fs';",
            f"import {{ parseRenderedUxMap, projectUxMapForRenderParity }} from {json.dumps(parity_module.as_uri())};",
            f"const source = JSON.parse(fs.readFileSync({json.dumps(str(json_path))}, 'utf8'));",
            f"const markdown = fs.readFileSync({json.dumps(str(markdown_path))}, 'utf8');",
            "console.log(JSON.stringify({expected: projectUxMapForRenderParity(source), actual: parseRenderedUxMap(markdown)}, null, 2));",
        ]
    )
    completed = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    projections = json.loads(completed.stdout)
    expected = json.dumps(projections["expected"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    actual = json.dumps(projections["actual"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return expected, actual


def check(refs: list[str]) -> int:
    drifted = False
    for ref in refs:
        try:
            try:
                expected = render(ref)
                actual = (MAPS_DIR / f"{ref}.md").read_text(encoding="utf8")
            except ImportError:
                # The optional canvas package is deliberately not an app dependency.
                # The lossless projection exercises the same source/renderer boundary
                # and still rejects every machine-owned semantic drift in --check mode.
                expected, actual = _check_projection(ref)
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"{ref}: parity check failed: {exc}", file=sys.stderr)
            drifted = True
            continue
        if expected == actual:
            continue
        drifted = True
        sys.stderr.writelines(
            unified_diff(
                actual.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=f"{ref}.md (parsed)",
                tofile=f"{ref}.uxmap.json (rendered in memory)",
            )
        )
    if drifted:
        return 1
    print(f"all UX-map artifacts are current ({len(refs)} checked)")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    check_only = bool(args and args[0] == "--check")
    if check_only:
        args = args[1:]
    refs = args or [path.name[: -len(".uxmap.json")] for path in sorted(MAPS_DIR.glob("*.uxmap.json"))]
    if check_only:
        return check(refs)
    try:
        for ref in refs:
            target = MAPS_DIR / f"{ref}.md"
            target.write_text(render(ref), encoding="utf8")
            print(f"rendered {target.name}")
    except ImportError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
