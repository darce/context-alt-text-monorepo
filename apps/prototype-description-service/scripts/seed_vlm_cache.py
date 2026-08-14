"""Seed the pinned Florence LOCAL_CPU snapshot into a target HF_HOME (RA-04).

Run this OUTSIDE the offline runtime-vlm image. The runtime image bakes
``HF_HUB_OFFLINE=1`` / ``TRANSFORMERS_OFFLINE=1`` and cannot populate its own
cache. Operators seed a host path (or a volume) then mount it read-only at
``/data/cache``.

After download, this script invokes the integrity manifest writer so seeding
and verification share one operator gesture. Writing the manifest is a
TRUST-ESTABLISHING act: it certifies the just-downloaded tree. Do not re-run
the writer later to silence a failing boot gate.

Usage (from apps/prototype-description-service on the **host**, with the [vlm]
extra installed — not inside the offline runtime-vlm image):

    uv run --extra vlm python -m scripts.seed_vlm_cache \\
        --hf-home <ACX_MODELS_PATH>/huggingface_cache

``ACX_MODELS_PATH`` is the host models directory (e.g. ``/opt/acx-backend/prod``
on the VM). Then mount that cache read-only into the runtime-vlm container and
bake the printed ``ACX_VLM_MANIFEST_SHA256`` pin into the image (see
infra/oci/README.md § VLM weight cache).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _require_huggingface_hub():
    """Lazy import so recognition-only installs can still import this module."""
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "scripts.seed_vlm_cache requires the '[vlm]' extra (huggingface_hub via "
            "transformers). Install with `uv sync --extra vlm` (or "
            "`uv run --extra vlm python -m scripts.seed_vlm_cache ...`) and re-run. "
            f"Import error: {exc}"
        ) from exc
    return snapshot_download


def resolve_seed_target(
    *,
    profile_name: str | None = None,
) -> tuple[str, str, str]:
    """Return (profile_value, model_id, model_revision) for the LOCAL_CPU pin."""
    from scene.config.profiles import DescriptionProfile, get_profile_spec
    from scene.domain.description import DescriptionAdapterKind

    if profile_name:
        profile = DescriptionProfile(profile_name)
    else:
        from scene.config.settings import DescriptionSettings

        profile = DescriptionSettings().profile

    spec = get_profile_spec(profile)
    if spec.adapter_kind is not DescriptionAdapterKind.LOCAL_CPU:
        raise SystemExit(
            f"seed_vlm_cache: profile {profile.value!r} is not LOCAL_CPU "
            f"(adapter_kind={spec.adapter_kind.value!r}); nothing to seed."
        )
    if not spec.model_id or not spec.model_revision:
        raise SystemExit(
            f"seed_vlm_cache: profile {profile.value!r} lacks pinned model_id/model_revision."
        )
    # Refuse branch-name pins: integrity requires an immutable revision id.
    revision = spec.model_revision
    if revision in {"main", "master", "HEAD"} or revision.startswith("refs/"):
        raise SystemExit(
            f"seed_vlm_cache: refusing mutable revision {revision!r}; pin a commit SHA."
        )
    return profile.value, spec.model_id, revision


def seed_snapshot(
    *,
    hf_home: Path,
    model_id: str,
    model_revision: str,
    write_manifest: bool = True,
) -> Path:
    """Download the pinned snapshot into ``hf_home`` and optionally write the manifest.

    Pulls the full snapshot (weights + trust_remote_code ``*.py`` modeling files).
    An operator who copies only safetensors still fails the boot gate.
    """
    snapshot_download = _require_huggingface_hub()

    hf_home = hf_home.resolve()
    hf_home.mkdir(parents=True, exist_ok=True)

    # Align with runtime ENV: HF_HOME == HF_HUB_CACHE == /data/cache/huggingface_cache
    # so hub layout is $HF_HOME/models--... (not $HF_HOME/hub/models--...).
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(hf_home)

    print(
        f"Downloading {model_id}@{model_revision} into {hf_home} "
        "(includes remote-code *.py and weight shards)...",
        flush=True,
    )
    # No allow_patterns filter: Florence needs modeling_*.py / processing_*.py
    # as well as weight shards for trust_remote_code offline load.
    local_path = snapshot_download(
        repo_id=model_id,
        revision=model_revision,
        cache_dir=str(hf_home),
    )
    snapshot_dir = Path(local_path)
    print(f"Snapshot at {snapshot_dir}", flush=True)

    if write_manifest:
        from scripts.verify_vlm_cache import (
            MANIFEST_SHA256_ENV,
            MANIFEST_SHA256_FILE,
            manifest_content_sha256,
            write_manifest as write_integrity_manifest,
        )

        print(
            "Writing integrity manifest (TRUST-ESTABLISHING — certifies this download)...",
            flush=True,
        )
        manifest = write_integrity_manifest(snapshot_dir)
        pin = manifest_content_sha256(manifest)
        print(f"Manifest: {manifest}", flush=True)
        print(
            f"Detached trust pin (bake into the runtime-vlm image, outside the volume): "
            f"{MANIFEST_SHA256_ENV}={pin} or printf '%s\\n' '{pin}' > {MANIFEST_SHA256_FILE}",
            flush=True,
        )

    return snapshot_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Download the pinned LOCAL_CPU Florence snapshot into HF_HOME and "
            "write the integrity manifest. Run outside the offline runtime-vlm image."
        )
    )
    parser.add_argument(
        "--hf-home",
        required=True,
        help="Target HF cache root (e.g. /data/cache/huggingface_cache). Mount this read-only at runtime.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Description profile to seed (default: ACX_DESCRIPTION_ADAPTER / florence_small pin).",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Skip manifest write (not recommended; gate will fail closed without one).",
    )
    args = parser.parse_args(argv)

    profile_value, model_id, model_revision = resolve_seed_target(profile_name=args.profile)
    print(f"Seeding profile={profile_value} model={model_id} revision={model_revision}")

    try:
        seed_snapshot(
            hf_home=Path(args.hf_home),
            model_id=model_id,
            model_revision=model_revision,
            write_manifest=not args.no_manifest,
        )
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - operator-facing CLI
        print(f"seed_vlm_cache failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "Seed complete. Mount the cache read-only into the acx-backend-vlm image; "
        "python -m scripts.verify_vlm_cache must exit 0 on the VLM boot path."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
