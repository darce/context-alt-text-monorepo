#!/usr/bin/env python3
"""Build a self-contained, browser-openable HTML bake-off report.

Renders one card per image: the image itself (downscaled data-URI thumbnail),
its WP ``media_id``, filename, curated identities, and — side by side — every
model/run's output surfaces with per-image performance data (wall-clock latency
+ model-call count). One or many run-records => a single-model report or an
N-model comparison. Fully offline: open the HTML in any browser; JS-side search
filters over media_id, filename, names, and all descriptions.

Usage:
    python -m scripts.eval_harness.build_bakeoff_report \\
        --manifest scripts/eval_harness/corpus646-interleave-manifest-20260716.json \\
        --images-dir /Volumes/Butter/WP/vlm/app/public/wp-content/uploads \\
        --run "Qwen3-VL-30B=out/run-altq-646-interleave-v3.json" \\
        --media-ids 632,626,623,650,648,642,640,651,610,584 \\
        --embed-images --out report.html --title "10-image bake-off"

For a large corpus (hundreds of images) omit --embed-images: the report stays
light and text-only. --embed-images is intended for small comparison sets.

Comparability gate: every run record is checked against the manifest it is being
reported under, via the ``provenance.manifest_sha256`` the harness already stamps.
A record from a different corpus exits ``3`` and writes nothing; pass
``--allow-foreign-run LABEL`` to keep it as an explicitly badged, non-comparable
reference column instead.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path
from typing import Any

_THUMB_DEFAULT = 440


def _load_manifest(path: str) -> dict[int, dict[str, Any]]:
    raw = json.loads(Path(path).read_text())
    entries = raw.get("entries", raw.get("items", []))
    return {int(e["media_id"]): e for e in entries}


def _index_run(path: str) -> dict[int, dict[str, Any]]:
    """media_id -> {surfaces, latency_s, model_calls, error}."""
    rec = json.loads(Path(path).read_text())
    out: dict[int, dict[str, Any]] = {}
    for item in rec.get("items", []):
        mid = int(item["media_id"])
        describe = item.get("describe") or {}
        passes = describe.get("passes") or []
        if passes:
            latency = round(sum(p.get("latency_s") or 0 for p in passes), 2)
            calls = len(passes)
        else:
            latency = item.get("latency_s")
            calls = 1
        out[mid] = {
            "title": describe.get("alt_text_title"),
            "alt": describe.get("alt_text_draft"),
            "caption": describe.get("alt_text_long"),
            "latency_s": latency,
            "model_calls": calls,
            "error": item.get("error"),
        }
    return out


def _thumb_data_uri(image_path: Path, px: int) -> str | None:
    try:
        from PIL import Image  # lazy: only needed with --embed-images
    except ImportError:
        return None
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((px, px))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _resolve_image(images_dir: Path, entry: dict[str, Any]) -> Path | None:
    rel = entry.get("path")
    if not rel:
        return None
    cand = images_dir / rel
    if cand.exists():
        return cand
    # tolerate a manifest path that already carries the uploads suffix
    suffix = str(rel).split("uploads/", 1)[-1]
    alt = images_dir / suffix
    return alt if alt.exists() else None


def _pick_varied(manifest: dict[int, dict], runs: dict[str, dict[int, dict]], n: int) -> list[int]:
    """Deterministic spread: multi-person, text-heavy, single-id, no-id."""
    scored = sorted(m for m in manifest if any(m in r and not r[m].get("error") for r in runs.values()))

    def text_heavy(mid: int) -> bool:
        for r in runs.values():
            s = r.get(mid, {})
            blob = f"{s.get('caption') or ''} {s.get('alt') or ''}".lower()
            if any(w in blob for w in ("screenshot", "text ", "message", "words", "sign reads")):
                return True
        return False

    def names(mid: int) -> int:
        return len(manifest[mid].get("present_identities", []))

    multi = [m for m in scored if names(m) >= 2]
    text = [m for m in scored if text_heavy(m) and names(m) < 2]
    single = [m for m in scored if names(m) == 1 and not text_heavy(m)]
    noid = [m for m in scored if names(m) == 0 and not text_heavy(m)]
    pick: list[int] = []
    for pool, want in ((multi, 3), (text, 3), (single, 2), (noid, 2)):
        taken = 0
        for m in pool:
            if len(pick) >= n or taken >= want:
                break
            if m not in pick:
                pick.append(m)
                taken += 1
    # backfill to n from anything scored (keeps the pick deterministic and full)
    for m in scored:
        if len(pick) >= n:
            break
        if m not in pick:
            pick.append(m)
    return pick[:n]


def _card_html(mid: int, entry: dict, runs: dict[str, dict], thumb: str | None, hourly_rate: float | None = None) -> str:
    fname = html.escape(Path(entry.get("path", "")).name)
    idents = entry.get("present_identities", [])
    chips = (
        "".join(f'<span class="chip">{html.escape(n)}</span>' for n in idents)
        if idents
        else '<span class="none">no curated identity</span>'
    )
    img = (
        f'<img loading="lazy" src="{thumb}" alt="media {mid}">'
        if thumb
        else '<div class="noimg">image not embedded</div>'
    )
    blocks = []
    for label, run in runs.items():
        s = run.get(mid)
        if s is None:
            body = '<p class="none">not in this run</p>'
            perf = ""
        elif s.get("error"):
            body = f'<p class="err">{html.escape(str(s["error"])[:160])}</p>'
            perf = ""
        else:
            parts = []
            if s.get("title"):
                parts.append(f'<p class="surf"><span class="lab">Title</span>{html.escape(s["title"])}</p>')
            if s.get("alt"):
                parts.append(f'<p class="surf"><span class="lab">Alt</span>{html.escape(s["alt"])}</p>')
            if s.get("caption"):
                parts.append(f'<p class="surf"><span class="lab">Caption</span>{html.escape(s["caption"])}</p>')
            if not parts and s.get("caption") is None and s.get("alt") is None:
                parts.append('<p class="none">empty output</p>')
            body = "".join(parts)
            lat_v = s.get("latency_s")
            lat = f"{lat_v:.2f}s" if isinstance(lat_v, (int, float)) else "—"
            # Deterministic per-image cost = flat instance rate x inference seconds.
            cost = (f' · ${hourly_rate * lat_v / 3600:.5f}/img'
                    if hourly_rate is not None and isinstance(lat_v, (int, float)) else "")
            perf = f'<span class="perf">{lat}{cost} · {s.get("model_calls", "?")} call(s)</span>'
        blocks.append(
            f'<div class="run"><div class="runhead"><span class="model">{html.escape(label)}</span>{perf}</div>{body}</div>'
        )
    return (
        f'<article class="card">'
        f'<div class="imgwrap">{img}<div class="mid">#{mid}</div></div>'
        f'<div class="body"><div class="meta"><span class="file">{fname}</span></div>'
        f'<div class="chips">{chips}</div>'
        f'<div class="runs">{"".join(blocks)}</div></div></article>'
    )


_STYLE = """
:root{--paper:#FAF9F6;--ink:#22221E;--muted:#6B6A61;--line:#E4E2D8;--accent:#0E6B6A;
--chip:#0E6B6A;--chip-bg:#E3F0EF;--card:#FFF;--err:#9B3B2E;--perf:#8A5A13}
@media(prefers-color-scheme:dark){:root{--paper:#191A17;--ink:#E8E6DD;--muted:#98968A;--line:#33342E;
--accent:#7FD1CE;--chip:#7FD1CE;--chip-bg:#12312F;--card:#20211D;--err:#E08573;--perf:#E4B366}}
:root[data-theme=dark]{--paper:#191A17;--ink:#E8E6DD;--muted:#98968A;--line:#33342E;--accent:#7FD1CE;--chip:#7FD1CE;--chip-bg:#12312F;--card:#20211D;--err:#E08573;--perf:#E4B366}
:root[data-theme=light]{--paper:#FAF9F6;--ink:#22221E;--muted:#6B6A61;--line:#E4E2D8;--accent:#0E6B6A;--chip:#0E6B6A;--chip-bg:#E3F0EF;--card:#FFF;--err:#9B3B2E;--perf:#8A5A13}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding-bottom:4rem}
header{position:sticky;top:0;background:var(--paper);border-bottom:1px solid var(--line);padding:1rem 1.25rem;z-index:5}
h1{font-size:1.15rem;margin:0 0 .2rem;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:.8rem;margin:0}
input[type=search]{margin-top:.7rem;width:100%;max-width:360px;padding:.45rem .7rem;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);font:inherit}
input[type=search]:focus{outline:2px solid var(--accent);outline-offset:1px}
main{max-width:64rem;margin:0 auto;padding:1.1rem 1.25rem}
.count{color:var(--muted);font-size:.76rem;margin:.2rem 0 .9rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:0 0 1rem;overflow:hidden;display:grid;grid-template-columns:220px 1fr}
@media(max-width:640px){.card{grid-template-columns:1fr}}
.imgwrap{position:relative;background:#0000000d;display:flex;align-items:center;justify-content:center;min-height:150px}
.imgwrap img{width:100%;height:100%;object-fit:cover;display:block}
.noimg{color:var(--muted);font-size:.72rem;padding:2rem 1rem;text-align:center}
.mid{position:absolute;top:.4rem;left:.4rem;background:var(--accent);color:var(--paper);font:600 .72rem/1 ui-monospace,Menlo,monospace;padding:.25rem .5rem;border-radius:5px;font-variant-numeric:tabular-nums}
.body{padding:.85rem 1rem}
.meta{margin-bottom:.35rem}
.file{font:.72rem/1.3 ui-monospace,Menlo,monospace;color:var(--muted);overflow-wrap:anywhere}
.chips{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.5rem}
.chip{background:var(--chip-bg);color:var(--chip);border-radius:999px;padding:.14rem .6rem;font:600 .72rem/1.3 inherit}
.none{color:var(--muted);font-size:.74rem;font-style:italic;margin:.1rem 0}
.runs{display:flex;flex-direction:column;gap:.6rem}
.run{border-top:1px solid var(--line);padding-top:.55rem}
.runhead{display:flex;align-items:baseline;gap:.6rem;margin-bottom:.25rem}
.model{font:600 .82rem/1 inherit;color:var(--accent)}
.perf{margin-left:auto;font:.72rem/1 ui-monospace,Menlo,monospace;color:var(--perf);font-variant-numeric:tabular-nums}
.surf{margin:.15rem 0;max-width:64ch}
.lab{display:inline-block;min-width:3.6rem;font:600 .64rem/1.4 inherit;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.err{color:var(--err);font-size:.8rem;font-weight:600}
mark{background:var(--chip-bg);color:inherit;border-radius:2px}
"""

_SCRIPT = """
const cards=[...document.querySelectorAll('.card')];
const q=document.getElementById('q'),count=document.getElementById('count');
function upd(){const t=q.value.trim().toLowerCase();let n=0;
cards.forEach(c=>{const hit=!t||c.dataset.search.includes(t);c.style.display=hit?'':'none';if(hit)n++;});
count.textContent=n+' of '+cards.length+' images';}
q.addEventListener('input',upd);upd();
"""


def build(
    manifest: dict[int, dict],
    runs: dict[str, dict[int, dict]],
    media_ids: list[int],
    images_dir: Path | None,
    embed: bool,
    thumb_px: int,
    title: str,
    subtitle: str,
    hourly_rate: float | None = None,
) -> str:
    cards = []
    for mid in media_ids:
        entry = manifest.get(mid, {"media_id": mid, "path": "", "present_identities": []})
        thumb = None
        if embed and images_dir is not None:
            p = _resolve_image(images_dir, entry)
            if p is not None:
                thumb = _thumb_data_uri(p, thumb_px)
        search = " ".join(
            [str(mid), Path(entry.get("path", "")).name, *entry.get("present_identities", [])]
            + [
                str(v)
                for r in runs.values()
                for v in (r.get(mid, {}).get("title"), r.get(mid, {}).get("alt"), r.get(mid, {}).get("caption"))
                if v
            ]
        ).lower()
        card = _card_html(mid, entry, runs, thumb, hourly_rate)
        cards.append(
            card.replace('<article class="card">', f'<article class="card" data-search="{html.escape(search)}">')
        )
    return (
        f"<title>{html.escape(title)}</title>\n<style>{_STYLE}</style>\n"
        f'<header><h1>{html.escape(title)}</h1><p class="sub">{html.escape(subtitle)}</p>'
        f'<input type="search" id="q" placeholder="Search media_id, names, captions, filenames…" aria-label="Search"></header>\n'
        f'<main><p class="count" id="count" role="status"></p>{"".join(cards)}</main>\n'
        f"<script>{_SCRIPT}</script>\n"
    )


NON_COMPARABLE_BADGE = " ⚠ NOT COMPARABLE"
EXIT_NOT_COMPARABLE = 3


class ComparabilityError(RuntimeError):
    """A run record was produced against a different corpus than the one being reported."""


def _run_provenance(path: str) -> dict[str, Any]:
    prov = json.loads(Path(path).read_text()).get("provenance")
    return prov if isinstance(prov, dict) else {}


def _manifest_identity(path: str) -> tuple[str | None, str]:
    """Canonical ``manifest_sha256`` for ``path``, matching ``cli._manifest_sha``.

    Returns ``(sha, mode)``. A v3 manifest is loaded through the real validator so
    the digest is byte-identical to the one every run record stamps. Anything that
    is structurally not a v3 manifest (ad-hoc fixtures) yields ``(None, ...)`` and
    downgrades the check to cross-run agreement — the branch is decided by the
    declared ``manifest_version``, never by swallowing a load failure.
    """
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict) or raw.get("manifest_version") != 3:
        return None, "cross-run only (manifest is not v3)"
    from scripts.eval_harness.cli import _manifest_sha  # heavy import: v3 path only
    from scripts.eval_harness.manifest import load_manifest

    return _manifest_sha(load_manifest(path)), "verified against manifest"


def _check_comparability(
    manifest_path: str, provenances: dict[str, dict[str, Any]], consented: set[str]
) -> tuple[dict[str, str], str]:
    """Refuse to render run records drawn from a different split [EVAL-01, EXP-07].

    A 646-image run record is a *superset* of a 10-image manifest, so every cell
    populates and the column renders as an unmarked control while measuring a
    different corpus. The identity that makes the two distinguishable —
    ``provenance.manifest_sha256`` — is already stamped on every record, so the
    mismatch is detectable and is treated as fatal rather than cosmetic.

    Returns ``(foreign_reasons, mode)``; raises ``ComparabilityError`` for any
    mismatch the operator has not explicitly consented to via
    ``--allow-foreign-run``. Consented runs stay in the report but carry a
    permanent badge so they can never be read as a like-for-like control.
    """
    expected, mode = _manifest_identity(manifest_path)
    shas = {label: (prov.get("manifest_sha256") or "") for label, prov in provenances.items()}

    reasons: dict[str, str] = {}
    for label, sha in shas.items():
        if not sha:
            reasons[label] = "run record carries no provenance.manifest_sha256"
        elif expected is not None and sha != expected:
            reasons[label] = f"ran against manifest {sha[:12]}, report declares {expected[:12]}"
    if expected is None:
        # No manifest-side anchor: runs must at least agree with each other, else
        # the columns are measuring different corpora regardless of the header.
        distinct = {s for s in shas.values() if s}
        if len(distinct) > 1:
            majority = max(distinct, key=lambda s: sum(1 for v in shas.values() if v == s))
            for label, sha in shas.items():
                if sha and sha != majority:
                    reasons[label] = f"ran against manifest {sha[:12]}, other runs used {majority[:12]}"
        elif not distinct:
            reasons.clear()  # nothing anywhere carries provenance: nothing to contradict

    unconsented = {label: why for label, why in reasons.items() if label not in consented}
    if unconsented:
        lines = "\n".join(f"  - {label}: {why}" for label, why in sorted(unconsented.items()))
        raise ComparabilityError(
            f"run record(s) not comparable to --manifest {manifest_path}:\n{lines}\n"
            "A run made on a different corpus renders as an unmarked control column. Either "
            "re-run those models on this manifest, or pass --allow-foreign-run LABEL to keep "
            "the column as an explicitly badged, non-comparable reference."
        )
    for label in sorted(consented - set(reasons)):
        print(f"note: --allow-foreign-run {label!r} is stale; that run matches this manifest", file=sys.stderr)
    return reasons, mode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a self-contained bake-off HTML report.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument(
        "--run", action="append", required=True, metavar="LABEL=PATH", help="repeatable; model label = run-record path"
    )
    ap.add_argument("--images-dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--media-ids", help="comma-separated subset; default = varied auto-pick")
    ap.add_argument("--limit", type=int, default=10, help="auto-pick count when --media-ids absent")
    ap.add_argument("--embed-images", action="store_true")
    ap.add_argument("--thumb-px", type=int, default=_THUMB_DEFAULT)
    ap.add_argument("--title", default="Bake-off report")
    ap.add_argument("--cost-total", type=float, default=None,
                    help="total run cost in USD; report renders total + cost-per-image")
    ap.add_argument("--hourly-rate", type=float, default=None,
                    help="instance $/hr; renders deterministic per-image cost = rate x inference seconds")
    ap.add_argument("--allow-foreign-run", action="append", default=[], metavar="LABEL",
                    help="repeatable; consent to render LABEL even though it ran against a different "
                         "manifest. The column is badged non-comparable instead of passing as a control.")
    args = ap.parse_args(argv)
    for _name, _val in (("--hourly-rate", args.hourly_rate), ("--cost-total", args.cost_total)):
        if _val is not None and _val < 0:
            ap.error(f"{_name} must be non-negative, got {_val}")

    manifest = _load_manifest(args.manifest)
    runs: dict[str, dict[int, dict]] = {}
    provenances: dict[str, dict[str, Any]] = {}
    for spec in args.run:
        if "=" not in spec:
            ap.error(f"--run must be LABEL=PATH, got {spec!r}")
        label, path = spec.split("=", 1)
        runs[label] = _index_run(path)
        provenances[label] = _run_provenance(path)

    try:
        foreign, identity_mode = _check_comparability(args.manifest, provenances, set(args.allow_foreign_run))
    except ComparabilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_COMPARABLE
    if foreign:
        runs = {(f"{label}{NON_COMPARABLE_BADGE} ({foreign[label]})" if label in foreign else label): cells
                for label, cells in runs.items()}

    if args.media_ids:
        media_ids = [int(x) for x in args.media_ids.split(",") if x.strip()]
    else:
        media_ids = _pick_varied(manifest, runs, args.limit)

    images_dir = Path(args.images_dir) if args.images_dir else None
    if args.embed_images and images_dir is None:
        ap.error("--embed-images requires --images-dir")

    subtitle = (f"{len(media_ids)} images · {len(runs)} run(s): {', '.join(runs)} · "
                f"manifest identity: {identity_mode} · self-contained, offline")
    if args.cost_total is not None and media_ids:
        subtitle += f" · total ${args.cost_total:.2f} · ${args.cost_total / len(media_ids):.4f}/image"
    doc = build(manifest, runs, media_ids, images_dir, args.embed_images, args.thumb_px, args.title, subtitle, args.hourly_rate)
    Path(args.out).write_text(doc)
    print(f"wrote {args.out} ({len(doc) / 1024:.0f}KB, {len(media_ids)} images, {len(runs)} run(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
