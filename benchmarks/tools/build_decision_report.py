from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit


ASSETS = (
    "operator-metrics.js",
    "operator-crossmodel.js",
    "operator-decision.js",
    "operator-review.js",
    "operator-review.css",
)
EXISTING_BLOCKS = (
    "operator-review-contract",
    "operator-review-initial-state",
    "operator-review-manifest",
    "operator-review-previous-manifests",
)
RECEIPT = "decision-build-receipt.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def serialize(value: object) -> bytes:
    return (json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def json_block(html: bytes, name: str) -> bytes:
    pattern = rb'<script\b(?=[^>]*\btype="application/json")(?=[^>]*\bid="' + name.encode() + rb'")[^>]*>(.*?)</script\s*>'
    matches = re.findall(pattern, html, re.DOTALL)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one JSON block {name}")
    return matches[0]


def normalize_performance(raw: bytes, rule: dict) -> dict:
    performance = json.loads(raw)
    aliases = rule["aliases"]
    allowed = set(rule["candidates"])
    rows = []
    lists = ["rows", "reviewed17_extension_rows"]
    for source in lists:
        for row in performance[source]:
            model = aliases.get(row["model"], row["model"])
            if model not in allowed:
                continue
            seconds = row.get("summed_stage_seconds")
            if not isinstance(seconds, (int, float)) or not row.get("profile_sha256"):
                continue
            rows.append({
                "physical_model_id": model,
                "image_id": row["image_id"],
                "E": bool(row["E"]),
                "W": bool(row["W"]),
                "profile_sha256": row["profile_sha256"],
                "summed_stage_seconds": seconds,
                "response_sha256": row.get("response_sha256"),
                "source_list": source,
            })
    rows.sort(key=lambda row: (
        row["physical_model_id"], row["image_id"], row["E"], row["W"],
        row["profile_sha256"], row["summed_stage_seconds"], row["source_list"],
    ))
    return {
        "schema": "description-model-perf/v1",
        "source": {"file": "gpu-performance.json", "sha256": sha(raw), "lists": lists},
        "timing_contract": performance["timing_contract"],
        "aliases": aliases,
        "rows": rows,
    }


def counts(manifest: dict, rule: dict, performance: dict) -> dict:
    cells = [cell for cell in manifest["cells"]
             if all(cell.get(key) == value for key, value in rule["filter"].items())]
    indexed = {}
    for row in performance["rows"]:
        key = (row["physical_model_id"], row["image_id"], row["E"], row["W"])
        indexed.setdefault(key, []).append(row)
    joined = 0
    for cell in cells:
        key = (cell["physical_model_id"], cell["image_id"],
               rule["filter"]["extraction_lexicon"], rule["filter"]["writing_lexicon"])
        rows = indexed.get(key, [])
        if len(rows) == 1 and (
            not cell.get("response_sha256")
            or cell["response_sha256"] == rows[0]["response_sha256"]
        ):
            joined += 1
    return {"decision_cells": len(cells), "perf_rows": len(performance["rows"]),
            "timing_joins": joined}


class LocalLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paths: set[Path] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in ("src", "href") or not value:
                continue
            url = urlsplit(value)
            path = Path(unquote(url.path))
            if (url.scheme or url.netloc or not url.path or path.is_absolute()
                    or ".." in path.parts):
                continue
            self.paths.add(path)


def copy_siblings(source: Path, out: Path, html: bytes, protected: set[str]) -> None:
    links = LocalLinks()
    links.feed(html.decode("utf-8"))
    paths = set(links.paths)
    images = source / "images"
    if images.is_dir():
        paths.update(path.relative_to(source) for path in images.rglob("*") if path.is_file())
    for relative in sorted(paths):
        target = out / relative
        original = source / relative
        if relative.as_posix() in protected or target.exists() or not original.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)


def build(args: argparse.Namespace) -> None:
    source = args.source.read_bytes()
    rule_raw = args.rule.read_bytes()
    rule = json.loads(rule_raw)
    blocks = {name: json_block(source, name) for name in EXISTING_BLOCKS}
    manifest = json.loads(blocks["operator-review-manifest"])
    for field in ("dataset_id", "manifest_sha256", "rubric_version"):
        if manifest.get(field) != rule.get(field) or field not in manifest or field not in rule:
            raise ValueError(f"manifest/rule {field} mismatch")
    for name in ("operator-decision-rule", "operator-decision-performance"):
        if re.search(rb'\bid="' + name.encode() + rb'"', source):
            raise ValueError(f"source already contains {name}")
    raw_performance = args.gpu_performance.read_bytes()
    performance = normalize_performance(raw_performance, rule)
    blocks["operator-decision-rule"] = rule_raw.replace(b"</", b"<\\/")
    blocks["operator-decision-performance"] = serialize(performance).replace(b"</", b"<\\/")

    assets = {name: (args.assets / name).read_bytes() for name in ASSETS}
    filenames = {}
    outputs = {}
    for name, data in assets.items():
        stem, extension = name.rsplit(".", 1)
        hashed = f"{stem}.{sha(data)[:12]}.{extension}"
        filenames[name] = hashed
        outputs[hashed] = data

    html = source
    for name in ("operator-metrics.js", "operator-review.js", "operator-review.css"):
        stem, extension = name.rsplit(".", 1)
        asset_pattern = re.escape(stem.encode()) + rb'(?:\.[0-9a-f]+)?\.' + extension.encode()
        if extension == "js":
            pattern = rb'<script\b[^>]*\bsrc="' + asset_pattern + rb'"[^>]*>\s*</script>'
            replacement = f'<script defer src="{filenames[name]}"></script>'.encode()
        else:
            pattern = rb'<link\b[^>]*\bhref="' + asset_pattern + rb'"[^>]*>'
            replacement = f'<link rel="stylesheet" href="{filenames[name]}">'.encode()
        html, replaced = re.subn(pattern, lambda match: replacement, html)
        if replaced != 1:
            raise ValueError(f"expected exactly one existing asset tag for {name}")

    inserted = b""
    for name in ("operator-decision-rule", "operator-decision-performance"):
        inserted += f'<script type="application/json" id="{name}">'.encode() + blocks[name] + b"</script>\n"
    for name in ("operator-crossmodel.js", "operator-decision.js"):
        inserted += f'<script defer src="{filenames[name]}"></script>\n'.encode()
    anchor = f'<script defer src="{filenames["operator-review.js"]}"></script>'.encode()
    html = html.replace(anchor, inserted + anchor, 1)
    outputs["index.html"] = html

    receipt = {
        "schema": "description-model-decision-build/v1",
        "inputs": {"source": sha(source), "gpu_performance": sha(raw_performance),
                   "rule": sha(rule_raw), "assets": {name: sha(data) for name, data in assets.items()}},
        "blocks": {name: sha(data) for name, data in blocks.items()},
        "counts": counts(manifest, rule, performance),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        (args.out / name).write_bytes(data)
    if args.copy_from is not None:
        copy_siblings(args.copy_from, args.out, html, set(outputs) | {RECEIPT})
    receipt["outputs"] = {
        path.relative_to(args.out).as_posix(): sha(path.read_bytes())
        for path in sorted(args.out.rglob("*")) if path.is_file() and path != args.out / RECEIPT
    }
    (args.out / RECEIPT).write_bytes(serialize(receipt))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic description-model decision report.")
    for flag in ("source", "gpu-performance", "rule", "assets", "out"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--copy-from", type=Path)
    args = parser.parse_args(argv)
    try:
        build(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"build_decision_report: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
