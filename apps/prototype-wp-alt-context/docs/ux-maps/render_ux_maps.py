#!/usr/bin/env python3
"""Deterministically render `<map_ref>.md` from `<map_ref>.uxmap.json`.

The `.uxmap.json` is the SSOT (DATA-14: one authority owns the record). This script is
the only sanctioned writer of the machine region of the sibling `.md`, so the two never
become independent hand-maintained copies (REF-09: a derived artifact that is hand-edited
drifts silently).

It wraps `workbay_canvas_mcp.ux_map.render_markdown.render_markdown_bundle` and adds the
per-screen inventory blocks (purpose / url_params / zone table) and the parity index that
`js/admin/__tests__/uxmap-render-parity.test.ts` asserts against.

Hand-authored prose sections listed in `KEEP_SECTIONS` come from the independent
`render_ux_maps.contracts.json` authority, with their original heading anchors. Normal
regeneration never rewrites that source or learns expected contracts from an artifact.

Usage (the canvas package is optional and only required when writing artifacts):

    PYTHONPATH=<parent-of-workbay_canvas_mcp> python3 docs/ux-maps/render_ux_maps.py \
        workbench-2pane describe-gpu-tier

    python3 docs/ux-maps/render_ux_maps.py --check
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterator
from difflib import unified_diff
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
MAPS_DIR = Path(os.environ.get("UX_MAPS_DIR", Path(__file__).resolve().parent)).resolve()
ASCII_FRAME_WIDTH = 62
ASCII_CONTENT_WIDTH = ASCII_FRAME_WIDTH - 2
VISIBLE_PROJECTION_PATH = Path(__file__).resolve().with_name("render_ux_maps.visible.json")
CONTRACTS_PATH = Path(__file__).resolve().with_name("render_ux_maps.contracts.json")

# Hand-authored sections preserved across regeneration. Order is significant and stable.
KEEP_SECTIONS = (
    "## Vocabulary (say / don't say)",
    "## Operator interaction contract",
    "## Detailed reducer and recovery contract",
)


class OptionalRendererUnavailable(ImportError):
    """Only absence of the top-level optional package permits snapshot fallback."""


def _load_renderer():
    try:
        from workbay_canvas_mcp.ux_map.models import UxMap
        from workbay_canvas_mcp.ux_map.render_markdown import render_markdown_bundle
    except ModuleNotFoundError as exc:  # pragma: no cover - operator-facing guidance
        if exc.name != "workbay_canvas_mcp":
            raise
        raise OptionalRendererUnavailable(
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
    if screen.get("action_states"):
        out += ["Action states: " + ", ".join(screen["action_states"]), ""]
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
        if _display_width(content) + _display_width(suffix) > width:
            rows.append(f"|{content}{' ' * (width - _display_width(content))}|")
            content = f" states+: {state}"
        else:
            content += suffix
    rows.append(f"|{content}{' ' * (width - _display_width(content))}|")
    return rows


def _is_grapheme_extension(char: str) -> bool:
    return (
        unicodedata.category(char).startswith("M")
        or char in {"\ufe0e", "\ufe0f"}
        or "\U0001f3fb" <= char <= "\U0001f3ff"
    )


def _graphemes(value: str) -> Iterator[str]:
    """Yield the extended clusters used by UX-map labels and ASCII sketches."""
    cluster = ""
    for char in value:
        if not cluster:
            cluster = char
        elif (_is_grapheme_extension(char) or char == "\u200d" or cluster.endswith("\u200d")
              or (len(cluster) == 1 and _is_regional_indicator(cluster) and _is_regional_indicator(char))):
            cluster += char
        else:
            yield cluster
            cluster = char
    if cluster:
        yield cluster


def _is_regional_indicator(char: str) -> bool:
    return "\U0001f1e6" <= char <= "\U0001f1ff"


def _grapheme_width(cluster: str) -> int:
    visible = [
        char
        for char in cluster
        if not _is_grapheme_extension(char) and char != "\u200d" and unicodedata.category(char) != "Cf"
    ]
    if not visible:
        return 0
    # Keycaps and emoji joined into one pictograph occupy one two-cell terminal glyph,
    # irrespective of the number of code points that encode the cluster.
    if "\u20e3" in cluster or "\u200d" in cluster or "\ufe0f" in cluster or any(_is_regional_indicator(c) for c in visible):
        return 2
    return 2 if any(unicodedata.east_asian_width(char) in {"W", "F"} for char in visible) else 1


def _display_width(value: str) -> int:
    """Return terminal-cell width by grapheme cluster, not by Unicode code point."""
    return sum(_grapheme_width(cluster) for cluster in _graphemes(value))


def _truncate_display(value: str, width: int) -> str:
    if _display_width(value) <= width:
        return value
    kept: list[str] = []
    used = 0
    for cluster in _graphemes(value):
        cluster_width = _grapheme_width(cluster)
        if used + cluster_width > width - 1:
            break
        kept.append(cluster)
        used += cluster_width
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
    conditional = any("when" in action for action in doc.get("actions", []))
    rows = [
        "## Actions",
        "",
        "| id | verb | target | hierarchy | costly | irreversible | preview required | screen id |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if conditional:
        rows[2] += " when (recovery state) |"
        rows[3] += " --- |"
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
        if conditional:
            rows[-1] += " " + ", ".join(action.get("when", ["always"])) + " |"
    return rows + [""]


def _conditional_action_rows(doc: dict, screen: dict) -> list[str]:
    """Show each mutually exclusive recovery separately; never truncate its condition."""
    rows = []
    actions = [action for action in doc.get("actions", []) if action.get("screen_id") == screen["id"]]
    for state in screen["action_states"]:
        rows.append(_fit_ascii_row(f"| when {state} |"))
        available = [action for action in actions if state in action.get("when", screen["action_states"])]
        for action in available:
            mark = "PRIMARY" if action["hierarchy"] == "primary" else action["hierarchy"]
            rows.append(_fit_ascii_row(f"|   [{mark}] {action['verb']} |"))
        if not available:
            rows.append(_fit_ascii_row("|   No action (silent) |"))
    return rows


def _validate_action_conditions(doc: dict) -> None:
    """Local schema extension: disjoint cases bound primary actions on each screen."""
    screens = {screen["id"]: screen for screen in doc["screens"]}
    for action in doc.get("actions", []):
        if "when" not in action:
            continue
        states = screens.get(action.get("screen_id"), {}).get("action_states", [])
        when = action["when"]
        if not isinstance(when, list) or not when or any(state not in states for state in when):
            raise ValueError(f"{action['id']}: invalid action condition")
    for screen in screens.values():
        states = screen.get("action_states", ["default"])
        if not isinstance(states, list) or not states or any(not isinstance(state, str) or not state.strip() for state in states):
            raise ValueError(f"{screen['id']}: invalid action states")
        primaries = [action for action in doc.get("actions", []) if action.get("screen_id") == screen["id"] and action["hierarchy"] == "primary"]
        for state in states:
            if sum(state in action.get("when", states) for action in primaries) > 1:
                raise ValueError(f"{screen['id']}: multiple primary actions for {state}")


def _slice_section(doc: dict) -> list[str]:
    slices = doc.get("slices", [])
    return ["## Suggested task-slice decomposition (from map)", "", *[f"{i}. {item}" for i, item in enumerate(slices, 1)], ""] if slices else []


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
    # ATX headings may be indented, padded, or closed with hashes. Detect their
    # semantic names, while preserving the section bytes for authority comparison.
    heading_matches = list(re.finditer(
        r"^ {0,3}##[ \t]+([^\r\n]*?)(?:[ \t]+#+)?[ \t]*\r?$", text, re.MULTILINE
    ))
    kept: list[tuple[int, str | None, str]] = []
    for heading in headings:
        matches = [match for match in heading_matches if "## " + match.group(1) == heading]
        if len(matches) > 1:
            raise ValueError(f"duplicate retained contract heading: {heading}")
        if not matches:
            continue
        match = matches[0]
        following = next((item for item in heading_matches if item.start() > match.start()), None)
        end = following.start() if following else len(text)
        anchor = "## " + following.group(1) if following else None
        kept.append((match.start(), anchor, text[match.start():end].strip("\n")))
    return [(anchor, section) for _, anchor, section in sorted(kept)]


def _extract_kept(md_path: Path) -> list[tuple[str | None, str]]:
    if not md_path.exists():
        return []
    return _extract_kept_text(md_path.read_text(encoding="utf8"))


def _kept_contract(map_ref: str) -> list[tuple[str | None, str]]:
    """Read the reviewed source; no regeneration path may write this file."""
    source = json.loads(CONTRACTS_PATH.read_text(encoding="utf8"))
    if source.get("version") != 1 or map_ref not in source.get("maps", {}):
        raise ValueError(f"{map_ref}: retained contract authority is absent or invalid")
    sections = source["maps"][map_ref]
    if not isinstance(sections, list) or any(
        not isinstance(item, list) or len(item) != 2
        or (item[0] is not None and not isinstance(item[0], str))
        or not isinstance(item[1], str) for item in sections
    ):
        raise ValueError(f"{map_ref}: retained contract authority is invalid")
    return [(anchor, section) for anchor, section in sections]


def _validate_retained_contract(map_ref: str, markdown: str) -> None:
    if _extract_kept_text(markdown) != _kept_contract(map_ref):
        raise ValueError(f"{map_ref}: retained contract differs from independent authority {CONTRACTS_PATH.name}")


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
    _validate_action_conditions(doc)
    # Local render extensions are lossless tables appended around the upstream bundle;
    # keep them out of the strict upstream Pydantic model and render them below.
    canonical_doc = {key: value for key, value in doc.items() if key not in {"domain_state_mappings", "slices"}}
    canonical_doc["actions"] = [{k: v for k, v in action.items() if k != "when"} for action in doc.get("actions", [])]
    canonical_doc["screens"] = [{k: v for k, v in screen.items() if k != "action_states"} for screen in doc["screens"]]
    bundle = render_markdown_bundle(ux_map_model.model_validate(canonical_doc)).split("\n")
    screens = {screen["id"]: screen for screen in doc["screens"]}
    flows = {flow["id"]: flow for flow in doc["flows"]}

    out: list[str] = []
    kept = _kept_contract(map_ref)
    active_flow: dict | None = None
    active_screen: dict | None = None
    skip_actions = False

    for line in bundle:
        if skip_actions:
            if not line.startswith("+"):
                continue
            skip_actions = False
        if active_screen is not None and active_screen.get("action_states") and line.startswith("| ACTIONS"):
            out.append(line)
            out += _conditional_action_rows(doc, active_screen)
            skip_actions = True
            continue
        if line == "## Flows":
            out += _action_table(doc)
        if line == "## Not doing":
            out += _slice_section(doc)
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


def _visible_projection(markdown: str) -> list[dict[str, object]]:
    """Project every operator-visible row from plain-text and Mermaid fences.

    Whitespace is retained because padding is part of an ASCII frame's contract. The
    renderer-backed and fallback checks intentionally share this extractor so neither
    path can enforce a weaker set of visible rows.
    """
    projection: list[dict[str, object]] = []
    heading = ""
    fence_heading = ""
    fence_language: str | None = None
    rows: list[str] = []
    for line in markdown.splitlines():
        if fence_language is None:
            if line.startswith("#"):
                heading = line
            if line.startswith("```"):
                fence_language = line[3:].strip()
                fence_heading = heading
                rows = []
            continue
        if line.startswith("```"):
            if fence_language in {"", "text", "mermaid"}:
                projection.append(
                    {"heading": fence_heading, "language": fence_language, "rows": rows}
                )
            fence_language = None
            rows = []
            continue
        rows.append(line)
    if fence_language is not None:
        raise ValueError(f"unterminated {fence_language or 'plain-text'} fence after {fence_heading!r}")
    return projection


def _source_digest(json_path: Path) -> str:
    # Universal-newline decoding keeps LF and autocrlf checkouts equivalent.
    return hashlib.sha256(json_path.read_text(encoding="utf8").encode("utf8")).hexdigest()


def _projection_digest(projection: list[dict[str, object]]) -> str:
    encoded = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    return hashlib.sha256(encoded).hexdigest()


def _read_visible_snapshot(map_ref: str, json_path: Path) -> str:
    try:
        snapshot = json.loads(VISIBLE_PROJECTION_PATH.read_text(encoding="utf8"))
        entry = snapshot["maps"][map_ref]
        recorded_digest = entry["source_sha256"]
        projection_digest = entry["projection_sha256"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{map_ref}: visible projection snapshot is absent or invalid") from exc
    if recorded_digest != _source_digest(json_path):
        raise RuntimeError(
            f"{map_ref}: UX-map JSON changed without regenerating its visible projection snapshot"
        )
    if not isinstance(projection_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", projection_digest):
        raise RuntimeError(f"{map_ref}: visible projection snapshot digest is invalid")
    return projection_digest


SCREEN_METADATA_KEYS = ("Purpose", "url_params", "Action states", "Screen states")


def scan_declarations(block: str, screen_id: str, first_line: int = 1) -> dict[str, str]:
    """Pure counterpart of renderParity.scanDeclarations for exhaustive probes."""
    declarations = {}
    locations = {}
    for index, line in enumerate(block.split("\n")):
        candidate = re.sub(r"^(?:(?:>|[-+*]|\d+[.)])\s*)+", "", line.lstrip()).strip()
        label, colon, value = candidate.partition(":")
        if not colon:
            continue
        label = " ".join(re.sub(r"[_*`]+", "", label).split()).lower()
        key = next((key for key in SCREEN_METADATA_KEYS if key.replace("_", "").lower() == label), None)
        if key is None:
            continue
        number = first_line + index
        if key in locations:
            raise ValueError(f"screen {screen_id} has duplicate {key} declarations at lines {locations[key]} and {number}")
        locations[key] = number
        declarations[key] = re.sub(r"^[_*`]+", "", value).strip()
    return declarations


def _check_projection(map_ref: str, rendered: str | None = None) -> tuple[str, str]:
    """Return complete expected/actual projections with or without the optional renderer."""
    parity_module = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/uxmap/renderParity.ts"
    json_path = MAPS_DIR / f"{map_ref}.uxmap.json"
    markdown_path = MAPS_DIR / f"{map_ref}.md"
    _validate_action_conditions(json.loads(json_path.read_text(encoding="utf8")))
    script = "\n".join(
        [
            "import fs from 'node:fs';",
            f"import {{ parseRenderedUxMap, projectUxMapForRenderParity }} from {json.dumps(parity_module.as_uri())};",
            f"const source = JSON.parse(fs.readFileSync({json.dumps(str(json_path))}, 'utf8'));",
            f"const markdown = fs.readFileSync({json.dumps(str(markdown_path))}, 'utf8');",
            "console.log(JSON.stringify({expected: projectUxMapForRenderParity(source), actual: parseRenderedUxMap(markdown)}, null, 2));",
        ]
    )
    try:
        completed = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "--eval", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{map_ref}: Node parity check exceeded 10s deadline") from exc
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    projections = json.loads(completed.stdout)
    markdown = markdown_path.read_text(encoding="utf8")
    snapshot_digest = _read_visible_snapshot(map_ref, json_path)
    if rendered is not None:
        rendered_digest = _projection_digest(_visible_projection(rendered))
        if rendered_digest != snapshot_digest:
            raise RuntimeError(
                f"{map_ref}: renderer visibleProjectionSha256 {rendered_digest} differs "
                f"from source-pinned snapshot {snapshot_digest}"
            )
        _validate_retained_contract(map_ref, rendered)
    projections["expected"]["retainedContracts"] = _kept_contract(map_ref)
    projections["actual"]["retainedContracts"] = _extract_kept_text(markdown)
    projections["expected"]["visibleProjectionSha256"] = snapshot_digest
    projections["actual"]["visibleProjectionSha256"] = _projection_digest(
        _visible_projection(markdown)
    )
    expected = json.dumps(projections["expected"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    actual = json.dumps(projections["actual"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return expected, actual


def check(refs: list[str]) -> int:
    drifted = False
    for ref in refs:
        try:
            try:
                rendered = render(ref)
                expected, actual = _check_projection(ref, rendered)
            except OptionalRendererUnavailable:
                # The optional canvas package is deliberately not an app dependency.
                # A source-pinned snapshot supplies the renderer-side visible rows;
                # both branches use the same complete projection and comparison.
                expected, actual = _check_projection(ref)
        except (OSError, RuntimeError, ValueError, ImportError) as exc:
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


def _updated_visible_snapshot(rendered_by_ref: dict[str, str]) -> str:
    """Record generated rows only after checking the independent retained authority."""
    try:
        snapshot = json.loads(VISIBLE_PROJECTION_PATH.read_text(encoding="utf8"))
    except FileNotFoundError:
        snapshot = {"version": 1, "maps": {}}
    if snapshot.get("version") != 1 or not isinstance(snapshot.get("maps"), dict):
        raise ValueError(f"invalid visible projection snapshot: {VISIBLE_PROJECTION_PATH}")
    for ref, markdown in rendered_by_ref.items():
        _validate_retained_contract(ref, markdown)
        json_path = MAPS_DIR / f"{ref}.uxmap.json"
        snapshot["maps"][ref] = {
            "source_sha256": _source_digest(json_path),
            "projection_sha256": _projection_digest(_visible_projection(markdown)),
        }
    return json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _render_and_write(refs: list[str]) -> None:
    """Render and validate the complete batch before replacing any target."""
    batch: list[tuple[Path, str]] = []
    rendered_by_ref: dict[str, str] = {}
    for ref in refs:
        rendered = render(ref)
        if not rendered.strip():
            raise ValueError(f"{ref}: renderer produced an empty artifact")
        batch.append((MAPS_DIR / f"{ref}.md", rendered))
        rendered_by_ref[ref] = rendered
    batch.append((VISIBLE_PROJECTION_PATH, _updated_visible_snapshot(rendered_by_ref)))
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
