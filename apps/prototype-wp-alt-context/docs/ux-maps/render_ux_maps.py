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
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from difflib import unified_diff
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
MAPS_DIR = Path(os.environ.get("UX_MAPS_DIR", Path(__file__).resolve().parent)).resolve()
ASCII_FRAME_WIDTH = 62
ASCII_CONTENT_WIDTH = ASCII_FRAME_WIDTH - 2

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


def _display_width(value: str) -> int:
    """Return terminal-cell width without adding an optional wcwidth dependency."""
    width = 0
    for char in value:
        if unicodedata.combining(char) or char in {"\u200d", "\ufe0e", "\ufe0f"}:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _truncate_display(value: str, width: int) -> str:
    if _display_width(value) <= width:
        return value
    kept: list[str] = []
    used = 0
    for char in value:
        char_width = _display_width(char)
        if used + char_width > width - 1:
            break
        kept.append(char)
        used += char_width
    return "".join(kept) + "…"


def _fit_ascii_row(line: str) -> str:
    """Fit every emitted ASCII row to the one 62-cell frame contract."""
    if line.startswith("+") and line.endswith("+"):
        return "+" + ("-" * ASCII_CONTENT_WIDTH) + "+"
    if not line.startswith("|"):
        return line
    content = line[1:-1] if line.endswith("|") else line[1:]
    content = _truncate_display(content.rstrip(), ASCII_CONTENT_WIDTH)
    return "|" + content + (" " * (ASCII_CONTENT_WIDTH - _display_width(content))) + "|"


def _normalize_ascii_frames(markdown: str) -> str:
    """Normalize all plain-text fenced sketches, including retained detailed sketches."""
    lines = markdown.split("\n")
    fence_language: str | None = None
    for index, line in enumerate(lines):
        if line.startswith("```"):
            fence_language = line[3:] if fence_language is None else None
        elif fence_language in {"", "text"} and (line.startswith("|") or line.startswith("+")):
            lines[index] = _fit_ascii_row(line)
    return "\n".join(lines)


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
    return _normalize_ascii_frames(_restore_kept("\n".join(out), kept))


def _visible_render_issues(doc: dict, markdown: str) -> list[str]:
    """Validate visible ASCII/Mermaid rows that the lossless comments cannot cover."""
    issues: list[str] = []
    screens_section = markdown.partition("## Screens")[2].partition("\n## Actions")[0]
    for screen in doc["screens"]:
        match = re.search(
            rf"^### .* \(`{re.escape(screen['id'])}`\)\n([\s\S]*?)(?=^### |\Z)",
            screens_section,
            re.MULTILINE,
        )
        if not match:
            issues.append(f"screen {screen['id']}: visible block is absent")
            continue
        fence = re.search(r"```(?:text)?\n([\s\S]*?)```", match.group(1))
        visible = fence.group(1) if fence else ""
        # The canonical renderer truncates long values, so a stable leading fragment
        # is the discriminating comparison for the operator-visible screen title row.
        fragment = screen["title"][: min(len(screen["title"]), 24)]
        kind_marker = f"[{screen['kind']}]"
        header_row = next((line for line in visible.splitlines() if kind_marker in line), None)
        if fragment not in (header_row if header_row is not None else visible):
            issues.append(f"screen {screen['id']}: visible title {fragment!r} is absent")

    flows_section = markdown.partition("## Flows")[2].partition("\n## Open questions")[0]
    for flow in doc["flows"]:
        match = re.search(
            rf"^### .* \(`{re.escape(flow['id'])}`\)\n([\s\S]*?)(?=^### |\Z)",
            flows_section,
            re.MULTILINE,
        )
        if not match:
            issues.append(f"flow {flow['id']}: visible Mermaid block is absent")
            continue
        mermaid = re.search(r"```mermaid\n([\s\S]*?)```", match.group(1))
        edge_labels = re.findall(r"-->\|([^|]+)\|", mermaid.group(1) if mermaid else "")
        expected_labels = [
            step["branch_label"] for step in flow["steps"] if step.get("branch_label")
        ]
        if len(edge_labels) < max(1, len(flow["steps"]) - 1):
            issues.append(f"flow {flow['id']}: visible Mermaid edge row is absent")
        for label in edge_labels:
            if not any(label == expected or label in expected or expected in label for expected in expected_labels):
                issues.append(f"flow {flow['id']}: visible Mermaid label {label!r} is not sourced by JSON")
    return issues


def _check_projection(map_ref: str) -> tuple[str, str]:
    """Return expected/actual lossless projections without importing the optional renderer."""
    parity_module = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/uxmap/renderParity.ts"
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
    doc = json.loads(json_path.read_text(encoding="utf8"))
    markdown = markdown_path.read_text(encoding="utf8")
    projections["expected"]["visibleRenderIssues"] = []
    projections["actual"]["visibleRenderIssues"] = _visible_render_issues(doc, markdown)
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


def _atomic_write(target: Path, rendered: str) -> None:
    """Durably replace one artifact without exposing a partial file."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _render_and_write(refs: list[str]) -> None:
    """Render and validate the complete batch before replacing any target."""
    batch: list[tuple[Path, str]] = []
    for ref in refs:
        rendered = render(ref)
        if not rendered.strip():
            raise ValueError(f"{ref}: renderer produced an empty artifact")
        batch.append((MAPS_DIR / f"{ref}.md", rendered))
    for target, rendered in batch:
        _atomic_write(target, rendered)
        print(f"rendered {target.name}")


def main(argv: list[str]) -> int:
    args = argv[1:]
    check_only = bool(args and args[0] == "--check")
    if check_only:
        args = args[1:]
    refs = args or [path.name[: -len(".uxmap.json")] for path in sorted(MAPS_DIR.glob("*.uxmap.json"))]
    if check_only:
        return check(refs)
    try:
        _render_and_write(refs)
    except ImportError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
