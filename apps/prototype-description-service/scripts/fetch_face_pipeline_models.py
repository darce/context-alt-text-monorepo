#!/usr/bin/env python3
"""Fetch and hash-verify YuNet + SFace ONNX models into face_pipeline/models/.

Downloads from the opencv_zoo commit pinned in
``recognition.infrastructure.face_pipeline.provenance`` (not a floating branch).

Usage (from apps/prototype-description-service):

    uv run python scripts/fetch_face_pipeline_models.py
    uv run python scripts/fetch_face_pipeline_models.py --models yunet
    uv run python scripts/fetch_face_pipeline_models.py --dest /tmp/models

ONNX files are gitignored; LICENSE files are committed for audit trail.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Allow running as a script without installing the package on PYTHONPATH.
_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from recognition.infrastructure.face_pipeline.provenance import (  # noqa: E402
    DEFAULT_MODELS_DIR,
    LICENSE_SOURCE_URLS,
    MODEL_MANIFEST,
    PENDING_OPERATOR_FETCH,
    ModelIntegrityError,
    ModelProvenance,
    load_verified_model,
)


class ModelFetchError(Exception):
    """Raised when a model or license download/verify step fails (fail-closed)."""


def download_file(url: str, dest: Path, *, timeout_s: float = 120.0) -> None:
    """Download ``url`` to ``dest``. Raises ``ModelFetchError`` on any I/O failure."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310
            data = resp.read()
    except urllib.error.HTTPError as exc:
        raise ModelFetchError(
            f"download failed: HTTP {exc.code} for {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ModelFetchError(f"download failed: {exc.reason} for {url}") from exc
    except TimeoutError as exc:
        raise ModelFetchError(f"download failed: timeout for {url}") from exc
    except OSError as exc:
        raise ModelFetchError(f"download failed: {exc} for {url}") from exc

    tmp = dest.with_suffix(dest.suffix + ".partial")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except OSError as exc:
        raise ModelFetchError(f"write failed for {dest}: {exc}") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_file(path: Path, expected_sha256: str, *, label: str) -> None:
    if expected_sha256 == PENDING_OPERATOR_FETCH:
        raise ModelFetchError(
            f"{label}: manifest still {PENDING_OPERATOR_FETCH}; cannot verify {path}"
        )
    if not path.is_file():
        raise ModelFetchError(f"{label}: missing after download: {path}")
    actual = _sha256_bytes(path.read_bytes())
    if actual != expected_sha256:
        raise ModelFetchError(
            f"{label}: sha256 mismatch for {path.name}: "
            f"expected {expected_sha256}, got {actual}"
        )


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def fetch_one(name: str, *, dest_dir: Path) -> Path:
    """Download model + license for ``name`` into ``dest_dir``; verify hashes."""
    entry: ModelProvenance | None = MODEL_MANIFEST.get(name)
    if entry is None:
        raise ModelFetchError(f"unknown model name: {name!r}")
    if entry.sha256 == PENDING_OPERATOR_FETCH:
        raise ModelFetchError(
            f"model {name!r} still has {PENDING_OPERATOR_FETCH} hash; "
            f"operator must supply real sha256 before fetch verification "
            f"(source: {entry.source_url} @ {entry.source_ref})"
        )

    model_path = dest_dir / entry.file_name
    license_path = dest_dir / entry.license_file
    print(f"fetching {name} model → {model_path}")
    download_file(entry.source_url, model_path)

    try:
        if entry.size_bytes > 0 and model_path.stat().st_size != entry.size_bytes:
            raise ModelFetchError(
                f"model {name!r}: size mismatch: expected {entry.size_bytes}, "
                f"got {model_path.stat().st_size}"
            )
        _verify_file(model_path, entry.sha256, label=f"model {name!r}")

        license_url = LICENSE_SOURCE_URLS.get(name)
        if license_url is None:
            raise ModelFetchError(f"no license source URL for {name!r}")
        print(f"fetching {name} license → {license_path}")
        download_file(license_url, license_path)
        _verify_file(license_path, entry.license_sha256, label=f"license {name!r}")

        # Final gate: loader path (same verification production will use).
        verified = load_verified_model(name, models_dir=dest_dir)
    except (ModelFetchError, ModelIntegrityError):
        # Fail-closed: never leave unverified model/license bytes in place.
        _unlink_quiet(model_path)
        _unlink_quiet(license_path)
        raise

    print(f"verified {name}: {verified} sha256={entry.sha256[:12]}…")
    return verified


def fetch_all(
    *,
    dest_dir: Path | None = None,
    models: tuple[str, ...] | None = None,
) -> list[Path]:
    """Fetch and verify the requested models (default: all in the manifest)."""
    root = Path(dest_dir) if dest_dir is not None else DEFAULT_MODELS_DIR
    root.mkdir(parents=True, exist_ok=True)
    names = models if models is not None else tuple(MODEL_MANIFEST.keys())
    paths: list[Path] = []
    for name in names:
        paths.append(fetch_one(name, dest_dir=root))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch YuNet + SFace ONNX models with sha256 verification."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"Destination directory (default: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODEL_MANIFEST.keys()),
        default=None,
        help="Subset of models to fetch (default: all)",
    )
    args = parser.parse_args(argv)
    try:
        paths = fetch_all(
            dest_dir=args.dest,
            models=tuple(args.models) if args.models else None,
        )
    except (ModelFetchError, ModelIntegrityError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"ok: fetched {len(paths)} model(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
