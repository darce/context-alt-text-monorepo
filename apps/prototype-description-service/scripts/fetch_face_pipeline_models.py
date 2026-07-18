#!/usr/bin/env python3
"""Fetch and hash-verify YuNet + SFace ONNX models into face_pipeline/models/.

Downloads from the opencv_zoo commit pinned in
``recognition.infrastructure.face_pipeline.provenance`` (not a floating branch).

Usage (from apps/prototype-description-service):

    uv run python scripts/fetch_face_pipeline_models.py
    uv run python scripts/fetch_face_pipeline_models.py --models yunet
    uv run python scripts/fetch_face_pipeline_models.py --dest /tmp/models

ONNX files are gitignored; LICENSE files are committed for audit trail.

Publish-after-verify: bytes land at the final path only after size+sha256
checks pass on the ``.partial`` download. A crash mid-download leaves at most
a ``.partial`` (never an unverified final ONNX). Failure cleanup never unlinks
git-tracked license files.
"""

from __future__ import annotations

import argparse
import contextlib  # noqa: E402  (stdlib; placed with imports)
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

# Stream cap slack over manifest size_bytes (BR-09).
_SIZE_SLACK_RATIO = 1.10
# Licenses are small text; hard cap if no size pin.
_DEFAULT_LICENSE_MAX_BYTES = 1_000_000
_CHUNK_SIZE = 64 * 1024


class ModelFetchError(Exception):
    """Raised when a model or license download/verify step fails (fail-closed)."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _unlink_quiet(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _partial_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".partial")


def _max_bytes_for_model(entry: ModelProvenance) -> int:
    if entry.size_bytes > 0:
        return int(entry.size_bytes * _SIZE_SLACK_RATIO) + 1
    return _DEFAULT_LICENSE_MAX_BYTES


def download_file(
    url: str,
    dest: Path,
    *,
    timeout_s: float = 120.0,
    max_bytes: int | None = None,
) -> None:
    """Stream ``url`` to ``dest`` via a ``.partial`` sibling (no hash check).

    Prefer :func:`download_verified` for production fetches. This lower-level
    helper is retained for tests that monkeypatch the download surface.

    Raises ``ModelFetchError`` on I/O failure or over-cap. Always unlinks the
    ``.partial`` on failure; successful path replaces to ``dest``.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(dest)
    cap = max_bytes if max_bytes is not None else _DEFAULT_LICENSE_MAX_BYTES
    written = 0
    try:
        try:
            with (
                urllib.request.urlopen(url, timeout=timeout_s) as resp,  # noqa: S310
                partial.open("wb") as fh,
            ):
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > cap:
                        raise ModelFetchError(f"download exceeded cap of {cap} bytes for {url}")
                    fh.write(chunk)
        except ModelFetchError:
            raise
        except urllib.error.HTTPError as exc:
            raise ModelFetchError(f"download failed: HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise ModelFetchError(f"download failed: {exc.reason} for {url}") from exc
        except TimeoutError as exc:
            raise ModelFetchError(f"download failed: timeout for {url}") from exc
        except OSError as exc:
            raise ModelFetchError(f"download failed: {exc} for {url}") from exc

        try:
            partial.replace(dest)
        except OSError as exc:
            raise ModelFetchError(f"write failed for {dest}: {exc}") from exc
    finally:
        _unlink_quiet(partial)


def download_verified(
    url: str,
    dest: Path,
    *,
    expected_sha256: str,
    expected_size: int | None = None,
    max_bytes: int,
    label: str,
    timeout_s: float = 120.0,
) -> None:
    """Stream to ``.partial``, hash+size-check, then publish via ``replace``.

    Fail-closed: the final ``dest`` is only written after verification passes.
    ``.partial`` is always unlinked in ``finally`` (missing_ok after replace).
    """
    if expected_sha256 == PENDING_OPERATOR_FETCH:
        raise ModelFetchError(f"{label}: manifest still {PENDING_OPERATOR_FETCH}; cannot verify {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(dest)
    written = 0
    try:
        try:
            with (
                urllib.request.urlopen(url, timeout=timeout_s) as resp,  # noqa: S310
                partial.open("wb") as fh,
            ):
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ModelFetchError(f"{label}: download exceeded cap of {max_bytes} bytes for {url}")
                    fh.write(chunk)
        except ModelFetchError:
            raise
        except urllib.error.HTTPError as exc:
            raise ModelFetchError(f"download failed: HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise ModelFetchError(f"download failed: {exc.reason} for {url}") from exc
        except TimeoutError as exc:
            raise ModelFetchError(f"download failed: timeout for {url}") from exc
        except OSError as exc:
            raise ModelFetchError(f"download failed: {exc} for {url}") from exc

        if not partial.is_file():
            raise ModelFetchError(f"{label}: missing after download: {partial}")

        actual_size = partial.stat().st_size
        if expected_size is not None and expected_size > 0 and actual_size != expected_size:
            raise ModelFetchError(
                f"{label}: size mismatch for {partial.name}: expected {expected_size}, got {actual_size}"
            )

        actual = _file_sha256(partial)
        if actual != expected_sha256:
            raise ModelFetchError(
                f"{label}: sha256 mismatch for {partial.name}: expected {expected_sha256}, got {actual}"
            )

        try:
            partial.replace(dest)
        except OSError as exc:
            raise ModelFetchError(f"write failed for {dest}: {exc}") from exc
    finally:
        _unlink_quiet(partial)


def fetch_one(name: str, *, dest_dir: Path) -> Path:
    """Download model + license for ``name`` into ``dest_dir``; verify hashes.

    Failure cleanup removes only the model ONNX written this run (and any
    ``.partial`` via :func:`download_verified`). Pre-existing / git-tracked
    license files are never unlinked.
    """
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

    try:
        download_verified(
            entry.source_url,
            model_path,
            expected_sha256=entry.sha256,
            expected_size=entry.size_bytes,
            max_bytes=_max_bytes_for_model(entry),
            label=f"model {name!r}",
        )

        license_url = LICENSE_SOURCE_URLS.get(name)
        if license_url is None:
            raise ModelFetchError(f"no license source URL for {name!r}")
        print(f"fetching {name} license → {license_path}")
        download_verified(
            license_url,
            license_path,
            expected_sha256=entry.license_sha256,
            expected_size=None,
            max_bytes=_DEFAULT_LICENSE_MAX_BYTES,
            label=f"license {name!r}",
        )

        # Final gate: loader path (same verification production will use).
        verified = load_verified_model(name, models_dir=dest_dir)
    except (ModelFetchError, ModelIntegrityError):
        # Fail-closed for model weights only — never unlink license_file
        # (LICENSE.yunet / LICENSE.sface are git-tracked audit artifacts).
        _unlink_quiet(model_path)
        _unlink_quiet(_partial_path(model_path))
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
    parser = argparse.ArgumentParser(description="Fetch YuNet + SFace ONNX models with sha256 verification.")
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
