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
        --manifest scene/tests/seed/golden.json \\
        --images-dir /Volumes/Butter/WP/vlm/app/public/wp-content/uploads \\
        --run "Qwen3-VL-30B=out/run-bakeoff-qwen3-vl-30b-a3b.json" \\
        --media-ids 1,2,3,4,5,6,7,8,9,10 \\
        --embed-images --out report.html --title "10-image bake-off"

For a large corpus (hundreds of images) omit --embed-images: the report stays
light and text-only. --embed-images is intended for small comparison sets.

Comparability gate: every run record is checked against the manifest it is being
reported under — structurally (media_ids the manifest does not contain) and, for a
v3 manifest, against the ``provenance.manifest_sha256`` the harness stamps.
A record from a different corpus exits ``4`` and writes nothing; pass
``--allow-foreign-run LABEL`` to keep it as an explicitly badged, non-comparable
reference column instead.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_THUMB_DEFAULT = 440
EXIT_NOT_COMPARABLE = 4
EXIT_BAKEOFF_GATE = 5
_REQUIRED_BASELINE_LABELS = (
    "zero_rule_context_echo",
    "context_only_heuristic",
    "current_production",
    "blinded_human",
)

# A bake-off report may be rendered for a small exploratory fixture, but the
# explicit ``--bakeoff-gate`` is a release-surface check.  Keep the readiness
# contract here, at the report boundary, so a caller cannot turn missing
# sampling metadata into a clean headline by supplying a run record alone.
_MIN_GOLDEN_ENTRIES = 100
_MIN_STRATUM_CELL = 5
_MIN_METRIC_BACKING_ENTRIES = 5
_MANDATORY_LABEL_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("subject", ("subject_id", "subject_ids", "subject", "subjects")),
    ("demographic_cohort", ("demographic_cohort", "cohort")),
    ("domain", ("domain",)),
    ("difficulty", ("difficulty",)),
    ("capture_device", ("capture_device",)),
    ("lighting", ("lighting",)),
    ("environment", ("environment",)),
    ("session", ("session", "capture_session", "capture_session_id")),
)
_METRIC_BACKING_FIELDS = ("reference_facts", "spatial_facts", "face_boxes")


def _load_manifest(path: str) -> dict[int, dict[str, Any]]:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise ValueError(f"manifest {path} must contain a JSON object")
    entries = raw.get("entries", raw.get("items", []))
    if not isinstance(entries, list):
        raise ValueError(f"manifest {path} entries must be a JSON array")
    out: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or "media_id" not in entry:
            raise ValueError(f"manifest {path} contains an entry without media_id")
        mid = int(entry["media_id"])
        if mid in out:
            raise ValueError(f"manifest {path} contains duplicate media_id {mid}")
        out[mid] = dict(entry)
    return out


def _index_run(path: str) -> dict[int, dict[str, Any]]:
    """media_id -> {surfaces, latency_s, model_calls, tokens, error}."""
    rec = json.loads(Path(path).read_text())
    if not isinstance(rec, Mapping):
        raise ValueError(f"run record {path} must contain a JSON object")
    items = rec.get("items", [])
    if not isinstance(items, list):
        raise ValueError(f"run record {path} items must be a JSON array")
    out: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping) or "media_id" not in item:
            raise ValueError(f"run record {path} contains an item without media_id")
        mid = int(item["media_id"])
        if mid in out:
            raise ValueError(f"run record {path} contains duplicate media_id {mid}")
        describe = item.get("describe")
        if not isinstance(describe, Mapping):
            describe = {}
        raw_passes = describe.get("passes")
        if raw_passes is None:
            passes: list[Mapping[str, Any]] = []
        elif isinstance(raw_passes, list):
            if any(not isinstance(p, Mapping) for p in raw_passes):
                raise ValueError(f"run record {path} media_id {mid} has a malformed pass")
            passes = raw_passes
        else:
            raise ValueError(f"run record {path} media_id {mid} passes must be a JSON array")
        if passes:
            pass_latencies = [p.get("latency_s") for p in passes]
            latency = (
                round(sum(float(value) for value in pass_latencies), 2)
                if all(_finite_number(value) for value in pass_latencies)
                else None
            )
            calls = len(passes)
        else:
            value = item.get("latency_s")
            latency = float(value) if _finite_number(value) else None
            explicit_calls = item.get("model_calls", describe.get("model_calls"))
            calls = explicit_calls if _nonnegative_int(explicit_calls) else None
        out[mid] = {
            "title": describe.get("alt_text_title"),
            "alt": describe.get("alt_text_draft"),
            "caption": describe.get("alt_text_long"),
            "latency_s": latency,
            "model_calls": calls,
            "tokens": describe.get("tokens"),
            "error": item.get("error"),
        }
    return out


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def render_delta_banner(delta: Mapping[str, Any] | None) -> str:
    """HTML stand-in for a scored Δ. Refusal occupies the number's place."""
    if not delta:
        return ""
    if delta.get("refused"):
        reason = html.escape(str(delta.get("reason") or "refusing Δ across straddled stamps"))
        invariant = html.escape(str(delta.get("invariant") or "delta_refuses_straddled_stamps"))
        return (
            f'<p class="err">Δ REFUSED ({invariant}): {reason}</p>'
        )
    power = delta.get("power") if isinstance(delta.get("power"), Mapping) else {}
    headline = html.escape(str(power.get("headline") or ""))
    metrics = delta.get("metrics") if isinstance(delta.get("metrics"), Mapping) else {}
    rows = []
    for key, row in metrics.items():
        if not isinstance(row, Mapping):
            continue
        rows.append(
            f"<li>{html.escape(str(key))}: candidate={html.escape(str(row.get('candidate')))} "
            f"baseline={html.escape(str(row.get('baseline')))} "
            f"Δ={html.escape(str(row.get('delta')))}</li>"
        )
    head = f'<p class="err"><strong>HEADLINE: {headline}</strong></p>' if headline else ""
    return head + ("<ul>" + "".join(rows) + "</ul>" if rows else "")


def _tokens_label(tokens: Any) -> str:
    """Render the per-image token roll-up.

    Reader contract for the sibling ``_sum_usage`` writer:
    - counts ``None`` → explicit ``tokens not captured``, never ``""``
    - ``complete`` false with integer counts → trailing ``+``
    - ``complete`` true → the plain label
    A non-dict (the current integer-0 shape) must not crash.
    """
    if not isinstance(tokens, dict):
        return " · tokens not captured"
    total = tokens.get("total_tokens")
    completion = tokens.get("completion_tokens")
    if not _nonnegative_int(total) or not _nonnegative_int(completion):
        return " · tokens not captured"
    partial = "+" if not tokens.get("complete") else ""
    return f" · {total}{partial} tok ({completion} out)"


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


def _attempted_media_ids(runs: dict[str, dict[int, dict]]) -> set[int]:
    """Every media_id a run actually tried, success or failure."""
    return {mid for run in runs.values() for mid in run}


def _pick_varied(manifest: dict[int, dict], runs: dict[str, dict[int, dict]], n: int) -> list[int]:
    """Deterministic spread: multi-person, text-heavy, single-id, no-id.

    The pool is every *attempted* media_id. Timeouts and transport failures
    stay in the frame so the measured system cannot shrink its own sample.
    """
    attempted = _attempted_media_ids(runs)
    scored = sorted(m for m in manifest if m in attempted)

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
            lat = f"{lat_v:.2f}s" if _finite_number(lat_v) else "—"
            # Deterministic per-image cost = flat instance rate x inference seconds.
            cost = (f' · ${hourly_rate * lat_v / 3600:.5f}/exposure'
                    if hourly_rate is not None and _finite_number(lat_v) else "")
            calls_v = s.get("model_calls")
            calls = str(calls_v) if _nonnegative_int(calls_v) else "not captured"
            perf = (
                f'<span class="perf">{lat}{cost} · {calls} call(s)'
                f'{html.escape(_tokens_label(s.get("tokens")))}</span>'
            )
        cls = "model warn" if NON_COMPARABLE_BADGE in label else "model"
        blocks.append(
            f'<div class="run"><div class="runhead"><span class="{cls}">{html.escape(label)}</span>{perf}</div>{body}</div>'
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
.model.warn{color:var(--err)}
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
# Distinct from cli.REFUSED_METRIC_EXIT_CODE / face_pass's 3: a comparability
# refusal is not a refused metric, and callers branch on the two differently.


class ComparabilityError(RuntimeError):
    """A run record was produced against a different corpus than the one being reported."""


def _manifest_sha(manifest: Any) -> str:
    """Canonical manifest digest — byte-identical to ``cli._manifest_sha``.

    Inlined rather than imported: ``cli`` pulls cv2/onnxruntime/httpx, which this
    otherwise-stdlib report script must not require to refuse a bad input.
    """
    return hashlib.sha256(json.dumps(manifest.model_dump(), sort_keys=True).encode()).hexdigest()


def _run_provenance(path: str) -> dict[str, Any]:
    prov = json.loads(Path(path).read_text()).get("provenance")
    return prov if isinstance(prov, dict) else {}


def _expected_shas(path: str) -> tuple[set[str], str]:
    """Return the one canonical digest a v3 record must carry.

    Returns ``(shas, mode)``. Structurally-not-v3 manifests (ad-hoc fixtures)
    yield an empty set: the digest anchor is unavailable, and the structural
    corpus check below carries the gate alone. The branch is decided by the
    declared ``manifest_version``, never by swallowing a load failure.
    """
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict) or str(raw.get("manifest_version")) != "3":
        return set(), "structural only (manifest is not v3)"
    try:
        from scripts.eval_harness.manifest import ManifestError, load_manifest
    except ImportError:  # invoked by file path rather than as a module
        from .manifest import ManifestError, load_manifest  # type: ignore[no-redef]
    try:
        # Report identity is metadata-only: this module never opens manifest
        # images while calculating the digest. Requiring GOLDEN_IMAGES_DIR here
        # would make the advertised offline report unusable on a laptop and
        # would prevent the comparability gate from producing its badge.
        manifest = load_manifest(
            path,
            metadata_only=True,
            skip_hash_verification=True,
            hash_skip_reason="bake-off report identity check does not read image bytes",
        )
    except ManifestError as exc:
        raise ComparabilityError(
            f"--manifest {path} declares manifest_version 3 but does not load as one: {exc}. "
            "Fix the manifest, or report against the manifest the runs were actually made on."
        ) from exc
    return {_manifest_sha(manifest)}, "structural + manifest digest"


def _check_comparability(
    manifest_ids: set[int],
    run_ids: dict[str, set[int]],
    provenances: dict[str, dict[str, Any]],
    consented: set[str],
    manifest_path: str,
    expected: set[str],
) -> dict[str, str]:
    """Refuse to render run records drawn from a different split [EVAL-01, EXP-07].

    A 646-image run record is a *superset* of a 10-image manifest, so every cell
    populates and the column renders as an unmarked control while measuring a
    different corpus. Two independent signals catch that:

    1. **Structural** — media_ids present in the record but absent from the
       manifest. Version-independent, derived from data in hand, and trusts no
       self-declared metadata. This is what catches 646-vs-10.
    2. **Digest** — ``provenance.manifest_sha256`` against either in-tree recipe.
       Catches same-or-subset corpora that the structural check cannot see, but
       only when the manifest is a loadable v3.

    Returns the per-label reasons; raises ``ComparabilityError`` for any mismatch
    the operator has not consented to via ``--allow-foreign-run``. Consented runs
    stay in the report but carry a permanent badge, so they can never be read as
    a like-for-like control.
    """
    shas: dict[str, str] = {}
    for label, prov in provenances.items():
        raw = prov.get("manifest_sha256")
        shas[label] = raw if isinstance(raw, str) else ("" if raw is None else str(raw))

    reasons: dict[str, str] = {}
    for label, ids in run_ids.items():
        extra = sorted(ids - manifest_ids)
        if extra:
            sample = ", ".join(str(i) for i in extra[:3]) + ("…" if len(extra) > 3 else "")
            reasons[label] = (
                f"covers {len(ids)} media_ids, {len(extra)} of which this "
                f"{len(manifest_ids)}-image manifest does not contain ({sample})"
            )

    if expected:
        for label, sha in shas.items():
            if label in reasons:
                continue
            if not sha:
                reasons[label] = "run record carries no provenance.manifest_sha256 to verify against this manifest"
            elif sha not in expected:
                accepted = " or ".join(sorted(e[:12] for e in expected))
                reasons[label] = f"ran against manifest {sha[:12]}, report declares {accepted}"
    else:
        # No manifest-side anchor: runs must at least agree with each other, else
        # the columns are measuring different corpora regardless of the header.
        distinct = {s for s in shas.values() if s}
        if len(distinct) > 1:
            majority = max(distinct, key=lambda s: sum(1 for v in shas.values() if v == s))
            for label, sha in shas.items():
                if sha and sha != majority and label not in reasons:
                    reasons[label] = f"ran against manifest {sha[:12]}, other runs used {majority[:12]}"

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
    return reasons


def _load_record_info(path: str) -> dict[str, Any]:
    """Load one run record and retain observed, rather than inferred, counters."""
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise ValueError(f"run record {path} must contain a JSON object")
    indexed = _index_run(path)
    items = raw.get("items", [])
    assert isinstance(items, list)  # _index_run validated this above
    calls = [cell.get("model_calls") for cell in indexed.values()]
    return {
        "raw": dict(raw),
        "indexed": indexed,
        "provenance": raw.get("provenance") if isinstance(raw.get("provenance"), Mapping) else {},
        "exposures": len(items),
        "calls": sum(calls) if all(_nonnegative_int(value) for value in calls) else None,
        "calls_complete": all(_nonnegative_int(value) for value in calls),
        "errors": sum(
            1 for item in items if isinstance(item, Mapping) and item.get("error")
        ),
        "monitoring": isinstance(raw.get("timing"), Mapping)
        and isinstance(raw.get("gpu"), Mapping),
    }


def _parse_label_path(
    specs: list[str],
    *,
    option: str,
    known: set[str] | None = None,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"{option} must be LABEL=PATH, got {spec!r}")
        label, path = spec.split("=", 1)
        if not label or not path:
            raise ValueError(f"{option} must have non-empty LABEL and PATH, got {spec!r}")
        if known is not None and label not in known:
            raise ValueError(f"{option} label {label!r} is not recognised")
        if label in parsed:
            raise ValueError(f"duplicate {option} label {label!r}")
        parsed[label] = path
    return parsed


def _parse_labels(values: list[str], *, option: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {option} value")
    if any(not value for value in values):
        raise ValueError(f"{option} values must be non-empty")
    return tuple(values)


def _load_serving_gate_failure(path: str, expected_id: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise ValueError(f"serving-gate-failed record {path} must contain a JSON object")
    if raw.get("kind") != "serving-gate-failed" or raw.get("status") != "serving-gate-failed":
        raise ValueError(f"serving-gate-failed record {path} has the wrong kind/status")
    if raw.get("candidate_id") != expected_id:
        raise ValueError(
            f"serving-gate-failed record {path} names {raw.get('candidate_id')!r}, expected {expected_id!r}"
        )
    if not isinstance(raw.get("reason"), str) or not raw["reason"]:
        raise ValueError(f"serving-gate-failed record {path} has no reason")
    if not isinstance(raw.get("evidence"), Mapping) or not raw["evidence"]:
        raise ValueError(f"serving-gate-failed record {path} has no evidence")
    return dict(raw)


def _entry_value(entry: Mapping[str, Any], field: str, aliases: Sequence[str]) -> Any:
    """Read a readiness field, allowing capture metadata to be namespaced."""
    for key in aliases:
        if key in entry:
            return entry[key]
    capture = entry.get("capture")
    if isinstance(capture, Mapping):
        for key in aliases:
            if key in capture:
                return capture[key]
    return None


def _is_populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_is_populated(item) for item in value)
    return bool(value)


def _label_values(value: Any) -> tuple[str, ...]:
    """Return explicit categorical labels without manufacturing a category."""
    if isinstance(value, str):
        value = value.strip()
        return (value,) if value else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        labels: list[str] = []
        for item in value:
            labels.extend(_label_values(item))
        return tuple(labels)
    return ()


def _entry_subjects(entry: Mapping[str, Any]) -> set[str]:
    """Get subject labels for leakage checks; empty means no evidence."""
    aliases = ("subject_id", "subject_ids", "subject", "subjects", "present_identities")
    for key in aliases:
        if key in entry:
            return set(_label_values(entry[key]))
    return set()


def _corpus_readiness_reasons(manifest: Mapping[int, Mapping[str, Any]]) -> list[str]:
    """Describe missing corpus evidence; callers must keep the result not_ready."""
    total = len(manifest)
    reasons: list[str] = []
    if total < _MIN_GOLDEN_ENTRIES:
        reasons.append(
            f"Golden-100 data unavailable: manifest contains {total} entries"
        )

    for field, aliases in _MANDATORY_LABEL_FIELDS:
        populated_ids = [
            media_id
            for media_id, entry in manifest.items()
            if _is_populated(_entry_value(entry, field, aliases))
        ]
        if len(populated_ids) != total:
            missing = sorted(set(manifest) - set(populated_ids))
            reasons.append(
                f"mandatory {field} strata unavailable: {len(populated_ids)}/{total} entries "
                f"populated (missing media_ids {', '.join(str(mid) for mid in missing[:8])})"
            )
        counts = Counter(
            label
            for entry in manifest.values()
            for label in _label_values(_entry_value(entry, field, aliases))
        )
        under = sorted(label for label, count in counts.items() if count < _MIN_STRATUM_CELL)
        if under:
            detail = ", ".join(f"{label}={counts[label]}" for label in under[:8])
            reasons.append(
                f"{field} strata below minimum cell size {_MIN_STRATUM_CELL}: {detail}"
            )

    for field in _METRIC_BACKING_FIELDS:
        populated = sum(
            1 for entry in manifest.values() if _is_populated(entry.get(field))
        )
        if populated < _MIN_METRIC_BACKING_ENTRIES:
            reasons.append(
                f"{field} metric backing unavailable: {populated}/{total} entries populated "
                f"(minimum {_MIN_METRIC_BACKING_ENTRIES}; claim remains not_ready)"
            )
    return reasons


def _selection_disjointness_reasons(
    reported: Mapping[int, Mapping[str, Any]],
    selections: Mapping[str, Mapping[int, Mapping[str, Any]]],
) -> list[str]:
    """Require an auditable selection/calibration frame before a bake-off pass."""
    if not selections:
        return [
            "selection disjointness unavailable: --selection-manifest is required; "
            "model/prompt/threshold selection cannot be certified"
        ]

    reasons: list[str] = []
    reported_media = set(reported)
    reported_sha = {
        str(entry.get("sha256")).strip()
        for entry in reported.values()
        if isinstance(entry.get("sha256"), str) and entry.get("sha256", "").strip()
    }
    reported_paths = {
        str(entry.get("path")).strip()
        for entry in reported.values()
        if isinstance(entry.get("path"), str) and entry.get("path", "").strip()
    }
    if len(reported_sha) != len(reported):
        reasons.append(
            "selection disjointness unavailable: reported manifest lacks a non-empty sha256 "
            f"for {len(reported) - len(reported_sha)} entr{'y' if len(reported) - len(reported_sha) == 1 else 'ies'}"
        )
    if any(not _entry_subjects(entry) for entry in reported.values()):
        reasons.append(
            "selection disjointness unavailable: reported manifest lacks explicit subject evidence "
            "for one or more entries"
        )
    reported_subjects = {
        subject for entry in reported.values() for subject in _entry_subjects(entry)
    }

    for label, selection in selections.items():
        prefix = f"selection manifest {label!r}"
        if not selection:
            reasons.append(f"{prefix} is empty")
            continue
        selection_sha = {
            str(entry.get("sha256")).strip()
            for entry in selection.values()
            if isinstance(entry.get("sha256"), str) and entry.get("sha256", "").strip()
        }
        missing_sha = len(selection) - len(selection_sha)
        if missing_sha:
            reasons.append(
                f"{prefix} lacks a non-empty sha256 for {missing_sha} entr{'y' if missing_sha == 1 else 'ies'}"
            )
        if any(not _entry_subjects(entry) for entry in selection.values()):
            reasons.append(f"{prefix} lacks explicit subject evidence for one or more entries")
        media_overlap = sorted(set(selection) & reported_media)
        sha_overlap = sorted(selection_sha & reported_sha)
        path_overlap = sorted(
            {
                str(entry.get("path")).strip()
                for entry in selection.values()
                if isinstance(entry.get("path"), str) and entry.get("path", "").strip()
            }
            & reported_paths
        )
        subject_overlap = sorted(
            {
                subject
                for entry in selection.values()
                for subject in _entry_subjects(entry)
            }
            & reported_subjects
        )
        if media_overlap:
            reasons.append(f"{prefix} overlaps reported media_id values: {media_overlap[:8]}")
        if sha_overlap:
            reasons.append(f"{prefix} overlaps reported sha256 values: {sha_overlap[:4]}")
        if path_overlap:
            reasons.append(f"{prefix} overlaps reported paths: {path_overlap[:4]}")
        if subject_overlap:
            reasons.append(
                f"{prefix} overlaps reported subject values: {subject_overlap[:8]}"
            )
    return reasons


def _gate_evaluation(
    manifest: dict[int, dict[str, Any]],
    records: Mapping[str, dict[str, Any]],
    baselines: Mapping[str, dict[str, Any]],
    serving_failures: Mapping[str, dict[str, Any]],
    *,
    expected_candidates: Sequence[str],
    expected_incumbents: Sequence[str],
    required_baselines: Sequence[str],
    score_ok: Mapping[str, str],
    foreign: Mapping[str, str] | None = None,
    selection_manifests: Mapping[str, Mapping[int, Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate the sealed bake-off readiness contract without inventing data."""
    reasons: list[str] = []
    axes: dict[str, str] = {}

    data_reasons = _corpus_readiness_reasons(manifest)
    reasons.extend(data_reasons)
    axes["data"] = "pass" if not data_reasons else "not_ready"
    selection_reasons = _selection_disjointness_reasons(manifest, selection_manifests or {})
    reasons.extend(selection_reasons)
    axes["selection"] = "pass" if not selection_reasons else "not_ready"

    missing_candidates = [
        candidate_id
        for candidate_id in expected_candidates
        if candidate_id not in records and candidate_id not in serving_failures
    ]
    serving_ids = [candidate_id for candidate_id in expected_candidates if candidate_id in serving_failures]
    unexpected_serving = sorted(set(serving_failures) - set(expected_candidates))
    missing_incumbents = [
        incumbent_id for incumbent_id in expected_incumbents if incumbent_id not in records
    ]
    missing_baselines = [label for label in required_baselines if label not in baselines]
    errored = [label for label, info in (*records.items(), *baselines.items()) if info["errors"]]
    foreign = foreign or {}
    required_labels = {
        *expected_candidates,
        *expected_incumbents,
        *required_baselines,
    }
    foreign_required = sorted(set(foreign) & required_labels)
    required_records = [
        (label, records[label])
        for label in (*expected_candidates, *expected_incumbents)
        if label in records
    ] + [(label, baselines[label]) for label in required_baselines if label in baselines]
    incomplete_media: list[str] = []
    manifest_ids = set(manifest)
    for label, info in required_records:
        observed_ids = set(info["indexed"])
        if observed_ids == manifest_ids:
            continue
        missing = sorted(manifest_ids - observed_ids)
        extra = sorted(observed_ids - manifest_ids)
        details = []
        if missing:
            details.append("missing " + ", ".join(str(media_id) for media_id in missing[:8]))
        if extra:
            details.append("unexpected " + ", ".join(str(media_id) for media_id in extra[:8]))
        incomplete_media.append(f"{label} ({'; '.join(details)})")
    missing_roster_contract = []
    if not expected_candidates:
        missing_roster_contract.append("expected candidate roster was not supplied")
    if not expected_incumbents:
        missing_roster_contract.append("expected incumbent roster was not supplied")
    reasons.extend(missing_roster_contract)
    if missing_candidates:
        reasons.append("missing candidate run records: " + ", ".join(sorted(missing_candidates)))
    if serving_ids:
        reasons.append("serving gate failures: " + ", ".join(sorted(serving_ids)))
    if unexpected_serving:
        reasons.append("unexpected serving gate failures: " + ", ".join(unexpected_serving))
    if missing_incumbents:
        reasons.append("missing incumbent run records: " + ", ".join(sorted(missing_incumbents)))
    if missing_baselines:
        reasons.append("missing required baseline arms: " + ", ".join(sorted(missing_baselines)))
    if incomplete_media:
        reasons.append("incomplete media-id multiset: " + "; ".join(sorted(incomplete_media)))
    if foreign_required:
        reasons.append(
            "foreign run records cannot satisfy bakeoff gate: " + ", ".join(foreign_required)
        )
    if errored:
        reasons.append("run records contain item errors: " + ", ".join(sorted(errored)))
    axes["model"] = "pass" if not (
        missing_roster_contract
        or missing_candidates
        or serving_ids
        or missing_incumbents
        or missing_baselines
        or incomplete_media
        or foreign_required
        or errored
    ) else "not_ready"

    missing_score = [
        candidate_id
        for candidate_id in expected_candidates
        if candidate_id in records
        and candidate_id not in serving_failures
        and not Path(score_ok.get(candidate_id, "")).is_file()
    ]
    if missing_score:
        reasons.append("missing successful score markers: " + ", ".join(sorted(missing_score)))
    axes["infra"] = "pass" if not (
        missing_roster_contract
        or serving_ids
        or unexpected_serving
        or missing_candidates
        or missing_incumbents
        or incomplete_media
        or foreign_required
        or errored
        or missing_score
    ) else "not_ready"

    monitor_labels = [
        candidate_id for candidate_id in expected_candidates if candidate_id in records
    ] + [incumbent_id for incumbent_id in expected_incumbents if incumbent_id in records]
    missing_monitoring = [
        label for label in monitor_labels if not records[label]["monitoring"]
    ]
    if missing_monitoring:
        reasons.append("missing timing/gpu monitoring mappings: " + ", ".join(sorted(missing_monitoring)))
    if (
        not monitor_labels
        or missing_roster_contract
        or missing_candidates
        or missing_incumbents
        or serving_ids
        or incomplete_media
        or foreign_required
    ):
        axes["monitoring"] = "not_ready"
    else:
        axes["monitoring"] = "pass" if not missing_monitoring else "not_ready"

    if any(value == "fail" for value in axes.values()):
        status = "fail"
    elif any(value != "pass" for value in axes.values()):
        status = "not_ready"
    else:
        status = "pass"
    return {"status": status, "axes": axes, "reasons": tuple(dict.fromkeys(reasons))}


def _gate_html(
    evaluation: Mapping[str, Any],
    serving_failures: Mapping[str, Mapping[str, Any]],
) -> str:
    status = html.escape(str(evaluation.get("status", "not_ready")))
    axes = evaluation.get("axes", {})
    readiness = " ".join(
        f"{name}={html.escape(str(axes.get(name, 'not_ready')))}"
        for name in ("data", "selection", "model", "infra", "monitoring")
    )
    reasons = evaluation.get("reasons", ())
    reason_html = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in reasons)
    failure_html = "".join(
        f"<li>{html.escape(label)}: {html.escape(str(record.get('reason', 'unknown reason')))}</li>"
        for label, record in sorted(serving_failures.items())
    )
    details = ""
    if reason_html:
        details += f"<ul>{reason_html}</ul>"
    if failure_html:
        details += f"<p>serving-gate-failed records:</p><ul>{failure_html}</ul>"
    return (
        '<section class="gate">'
        f"<p><strong>bakeoff-gate: {status}</strong></p>"
        f'<p class="sub">readiness: {readiness}</p>{details}'
        "</section>"
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build a self-contained bake-off HTML report.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument(
        "--run", action="append", default=[], metavar="LABEL=PATH", help="repeatable; model label = run-record path"
    )
    ap.add_argument(
        "--baseline-run", action="append", default=[], metavar="LABEL=PATH",
        help="repeatable; one of the required interpretable baseline arms = run-record path",
    )
    ap.add_argument(
        "--serving-gate-failed", action="append", default=[], metavar="ID=PATH",
        help="repeatable; candidate id = machine-readable serving-gate-failed record",
    )
    ap.add_argument(
        "--expected-candidate", action="append", default=[], metavar="ID",
        help="repeatable; sealed competing candidate id required by --bakeoff-gate",
    )
    ap.add_argument(
        "--expected-incumbent", action="append", default=[], metavar="ID",
        help="repeatable; incumbent id required by --bakeoff-gate",
    )
    ap.add_argument(
        "--required-baseline", action="append", default=[], metavar="LABEL",
        help="repeatable; assert/document one of the four baseline arms required by --bakeoff-gate",
    )
    ap.add_argument(
        "--score-ok", action="append", default=[], metavar="ID=PATH",
        help="repeatable; marker written only after a candidate score succeeds",
    )
    ap.add_argument(
        "--bakeoff-gate", action="store_true",
        help="render and enforce the sealed roster/data/selection/infra/monitoring readiness gate",
    )
    ap.add_argument(
        "--selection-manifest", action="append", default=[], metavar="PATH",
        help="repeatable; model/prompt/threshold selection corpus that must be disjoint from --manifest",
    )
    ap.add_argument("--images-dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--media-ids", help="comma-separated subset; default = varied auto-pick")
    ap.add_argument("--limit", type=int, default=10, help="auto-pick count when --media-ids absent")
    ap.add_argument("--embed-images", action="store_true")
    ap.add_argument("--thumb-px", type=int, default=_THUMB_DEFAULT)
    ap.add_argument("--title", default="Bake-off report")
    ap.add_argument("--cost-total", type=float, default=None,
                    help="total run cost in USD; pair with --cost-denominator")
    ap.add_argument(
        "--cost-denominator", choices=("exposure", "call"), default=None,
        help="denominator for --cost-total: per model/image exposure or measured model call",
    )
    ap.add_argument("--hourly-rate", type=float, default=None,
                    help="instance $/hr; renders deterministic per-image cost = rate x inference seconds")
    ap.add_argument(
        "--delta-json",
        default=None,
        help="optional scored baseline_delta JSON object; refused Δ is rendered in place of numbers",
    )
    ap.add_argument("--allow-foreign-run", action="append", default=[], metavar="LABEL",
                    help="repeatable; consent to render LABEL even though it ran against a different "
                         "manifest. The column is badged non-comparable instead of passing as a control.")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    for _name, _val in (("--hourly-rate", args.hourly_rate), ("--cost-total", args.cost_total)):
        if _val is not None and _val < 0:
            ap.error(f"{_name} must be non-negative, got {_val}")
    if args.cost_total is not None and args.cost_denominator is None:
        ap.error("--cost-total requires --cost-denominator {exposure,call}")
    if args.cost_total is None and args.cost_denominator is not None:
        ap.error("--cost-denominator requires --cost-total")

    try:
        expected_candidates = _parse_labels(args.expected_candidate, option="--expected-candidate")
        expected_incumbents = _parse_labels(args.expected_incumbent, option="--expected-incumbent")
        requested_baselines = _parse_labels(args.required_baseline, option="--required-baseline")
        # The four interpretable arms are a contract, not a caller-selected
        # subset. Explicit flags may make the command self-documenting, but
        # they cannot weaken the gate by omitting another required arm.
        required_baselines = tuple(dict.fromkeys((*requested_baselines, *_REQUIRED_BASELINE_LABELS)))
        unknown_baselines = set(required_baselines) - set(_REQUIRED_BASELINE_LABELS)
        if unknown_baselines:
            raise ValueError(
                "unknown --required-baseline label(s): " + ", ".join(sorted(unknown_baselines))
            )
        run_specs = _parse_label_path(args.run, option="--run")
        baseline_specs = _parse_label_path(
            args.baseline_run,
            option="--baseline-run",
            known=set(_REQUIRED_BASELINE_LABELS),
        )
        overlap = set(run_specs) & set(baseline_specs)
        if overlap:
            raise ValueError("run and baseline labels overlap: " + ", ".join(sorted(overlap)))
        serving_specs = _parse_label_path(args.serving_gate_failed, option="--serving-gate-failed")
        score_specs = _parse_label_path(args.score_ok, option="--score-ok")
        if len(args.selection_manifest) != len(set(args.selection_manifest)):
            raise ValueError("duplicate --selection-manifest path")
        serving_failures = {
            candidate_id: _load_serving_gate_failure(path, candidate_id)
            for candidate_id, path in serving_specs.items()
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        ap.error(str(exc))

    # Resolve the digest anchor first: a declared-v3 manifest that does not load
    # must be a diagnosed refusal, not a ValueError out of _load_manifest.
    try:
        expected_shas, identity_mode = _expected_shas(args.manifest)
    except ComparabilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_COMPARABLE

    try:
        manifest = _load_manifest(args.manifest)
        selection_manifests = {
            path: _load_manifest(path) for path in args.selection_manifest
        }
        run_info = {label: _load_record_info(path) for label, path in run_specs.items()}
        baseline_info = {label: _load_record_info(path) for label, path in baseline_specs.items()}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: unable to load bake-off input: {exc}", file=sys.stderr)
        return EXIT_NOT_COMPARABLE
    if not run_info and not baseline_info and not serving_failures and not args.bakeoff_gate:
        ap.error("at least one --run, --baseline-run, or --serving-gate-failed is required")

    all_info = {**run_info, **baseline_info}
    runs = {label: info["indexed"] for label, info in all_info.items()}
    provenances = {label: info["provenance"] for label, info in all_info.items()}

    try:
        foreign = _check_comparability(
            set(manifest),
            {label: set(cells) for label, cells in runs.items()},
            provenances,
            set(args.allow_foreign_run),
            args.manifest,
            expected_shas,
        )
    except ComparabilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if Path(args.out).exists():
            print(f"warning: {args.out} was NOT rewritten and still holds an older report", file=sys.stderr)
        return EXIT_NOT_COMPARABLE
    if foreign:
        badged = {(f"{label}{NON_COMPARABLE_BADGE} ({foreign[label]})" if label in foreign else label): cells
                  for label, cells in runs.items()}
        if len(badged) != len(runs):
            print("error: badged run labels collide; rename the --run labels", file=sys.stderr)
            return EXIT_NOT_COMPARABLE
        runs = badged

    if args.bakeoff_gate:
        gate_candidates = expected_candidates
        gate_incumbents = expected_incumbents
        evaluation = _gate_evaluation(
            manifest,
            run_info,
            baseline_info,
            serving_failures,
            expected_candidates=gate_candidates,
            expected_incumbents=gate_incumbents,
            required_baselines=required_baselines,
            score_ok=score_specs,
            foreign=foreign,
            selection_manifests=selection_manifests,
        )
    else:
        evaluation = None

    if args.media_ids:
        media_ids = [int(x) for x in args.media_ids.split(",") if x.strip()]
    else:
        media_ids = _pick_varied(manifest, runs, args.limit)

    images_dir = Path(args.images_dir) if args.images_dir else None
    if args.embed_images and images_dir is None:
        ap.error("--embed-images requires --images-dir")

    subtitle = f"{len(media_ids)} images · {len(runs)} run(s): {', '.join(runs)} · manifest identity: {identity_mode} · self-contained, offline"
    if args.cost_total is not None:
        exposures = sum(int(info["exposures"]) for info in all_info.values())
        if args.cost_denominator == "exposure":
            denominator = exposures
        else:
            if any(not info["calls_complete"] for info in all_info.values()):
                ap.error("--cost-denominator call requires explicit model_calls for every exposure")
            denominator = sum(int(info["calls"] or 0) for info in all_info.values())
        subtitle += f" · total ${args.cost_total:.2f}"
        if denominator:
            subtitle += f" · ${args.cost_total / denominator:.4f}/{args.cost_denominator}"
    doc = build(manifest, runs, media_ids, images_dir, args.embed_images, args.thumb_px, args.title, subtitle, args.hourly_rate)
    if evaluation is not None:
        doc = doc.replace("<main>", "<main>" + _gate_html(evaluation, serving_failures), 1)
    if args.delta_json:
        delta_payload = json.loads(Path(args.delta_json).read_text(encoding="utf-8"))
        banner = render_delta_banner(delta_payload)
        if banner:
            doc = doc.replace("<main>", "<main>" + banner, 1)
    Path(args.out).write_text(doc)
    print(f"wrote {args.out} ({len(doc) / 1024:.0f}KB, {len(media_ids)} images, {len(runs)} run(s))")
    if evaluation is not None and evaluation["status"] != "pass":
        print(f"bakeoff-gate: {evaluation['status']}", file=sys.stderr)
        return EXIT_BAKEOFF_GATE
    return 0


if __name__ == "__main__":
    sys.exit(main())
