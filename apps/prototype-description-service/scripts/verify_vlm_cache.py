"""Fail-closed VLM cache integrity gate for the runtime-vlm image boot path.

Invoked as ``python -m scripts.verify_vlm_cache`` with no required arguments
(docker-entrypoint runs this when ``ACX_IMAGE_VARIANT`` is the VLM image).

When the gate runs, exit 0 only when the pinned HF snapshot under HF_HOME
matches its integrity manifest exactly **and** trust_remote_code modeling
``*.py`` files are present. Skipping is the narrow case: recognition image
with a non-LOCAL_CPU profile (no VLM weights expected). On the VLM image the
gate always verifies — if the active profile is not LOCAL_CPU it still checks
the default Florence pin (``florence_small``), so a boot with the default
``seeded`` adapter cannot silently skip an empty weight mount.

Manifest location (choice, load-bearing)
----------------------------------------
The manifest lives **inside the snapshot directory** as
``acx-vlm-cache.manifest.json`` (JSON object: relative_path -> sha256 hex).

Rationale: the real weight digests are not known at repo commit time and must
not be invented. Seeding (``scripts.seed_vlm_cache``) and ``--write-manifest``
both write this file next to the weights they just certified. The gate treats
the manifest itself as metadata and excludes it from the hashed file set.

TRUST-ESTABLISHING act (sr-001 / RLSE-02)
-----------------------------------------
``--write-manifest`` certifies whatever is on disk at that moment. Run it only
against a freshly downloaded, out-of-band-verified snapshot — never to "fix"
a failing gate. A gate an operator can silence by re-running the writer is not
a gate.

Failure modes (each yields a distinct non-zero message)
-------------------------------------------------------
snapshot directory missing; directory empty; manifest missing; listed file
missing; sha256 mismatch; extra unlisted file present in the snapshot;
no trust_remote_code ``*.py`` modeling files (safetensors-only seed).
The extra-file case is the RB-02 attack surface: an attacker ADDS a .py
without modifying an existing entry.

Image variant constants (sr-007)
--------------------------------
``ImageVariant`` / ``IMAGE_VARIANT_ENV`` are the single importable source of
truth for the recognition vs VLM labels. Dockerfile ``ENV ACX_IMAGE_VARIANT=...``
and the entrypoint shell check must use these same string values; the API
reads the env via ``resolve_image_variant_label`` (rg-015: report what is set).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from enum import StrEnum
from pathlib import Path

# Stored inside the HF snapshot dir; excluded from the hashed payload set.
MANIFEST_FILENAME = "acx-vlm-cache.manifest.json"
_HASH_CHUNK = 1024 * 1024  # 1 MiB — never load multi-GB shards whole.

# Operator-facing seed command named in every fail-closed message (rg-006).
SEED_COMMAND = (
    "uv run --extra vlm python -m scripts.seed_vlm_cache "
    "--hf-home /data/cache/huggingface_cache"
)

EXIT_OK = 0
EXIT_FAIL = 1


class ImageVariant(StrEnum):
    """Canonical Docker image variant labels (sr-007).

    Baked into each runtime stage as ``ENV ACX_IMAGE_VARIANT=...``. Do not
    scatter the string literals elsewhere in Python — import these members.
    """

    RECOGNITION = "recognition"
    VLM = "vlm"


IMAGE_VARIANT_ENV = "ACX_IMAGE_VARIANT"
DEFAULT_IMAGE_VARIANT = ImageVariant.RECOGNITION

# Default LOCAL_CPU pin verified on the VLM image when the active profile is
# not itself LOCAL_CPU (so seeded/default boot still fails closed on empty cache).
DEFAULT_VLM_VERIFY_PROFILE = "florence_small"


class CacheIntegrityError(RuntimeError):
    """Actionable integrity failure; message is printed and mapped to EXIT_FAIL."""


def resolve_image_variant_label() -> str:
    """Return the image variant the running process actually has (rg-015).

    Reads ``ACX_IMAGE_VARIANT`` from the environment. Unset/blank falls back
    to the recognition default (matches Dockerfile ``runtime`` stage ENV).
    Unknown non-empty values are returned as-is so operators see the truth,
    not a guessed member of ``ImageVariant``.
    """
    raw = os.environ.get(IMAGE_VARIANT_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_IMAGE_VARIANT.value
    return str(raw).strip()


def resolve_hf_hub_cache() -> Path:
    """Resolve the HF hub cache root the same way the offline runtime expects it.

    Prefer ``HF_HUB_CACHE`` when set (Dockerfile pins both HF_HOME and
    HF_HUB_CACHE to ``/data/cache/huggingface_cache``); otherwise
    ``$HF_HOME/hub`` (HF default layout).
    """
    hub = os.environ.get("HF_HUB_CACHE")
    if hub:
        return Path(hub)
    home = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(home) / "hub"


def model_cache_dirname(model_id: str) -> str:
    """``microsoft/Florence-2-base-ft`` -> ``models--microsoft--Florence-2-base-ft``."""
    return "models--" + model_id.replace("/", "--")


def resolve_snapshot_dir(model_id: str, model_revision: str, *, hub_cache: Path | None = None) -> Path:
    root = hub_cache if hub_cache is not None else resolve_hf_hub_cache()
    return root / model_cache_dirname(model_id) / "snapshots" / model_revision


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def list_snapshot_files(snapshot_dir: Path) -> dict[str, Path]:
    """Map relative POSIX paths -> absolute paths for every file under the snapshot.

    The integrity manifest itself is excluded so it is not self-referential.
    Symlinks are followed (HF hub may use them); only regular files after
    resolve are included.
    """
    files: dict[str, Path] = {}
    if not snapshot_dir.is_dir():
        return files
    for path in sorted(snapshot_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(snapshot_dir).as_posix()
        if rel == MANIFEST_FILENAME:
            continue
        files[rel] = path
    return files


def write_manifest(snapshot_dir: Path, *, manifest_path: Path | None = None) -> Path:
    """Walk ``snapshot_dir``, hash every file, write the integrity manifest.

    TRUST-ESTABLISHING: this certifies the current on-disk contents. Do not run
    it to silence a failing gate — only against a freshly seeded, verified tree.
    """
    if not snapshot_dir.is_dir():
        raise CacheIntegrityError(
            f"cannot write manifest: snapshot directory missing: {snapshot_dir}"
        )
    files = list_snapshot_files(snapshot_dir)
    if not files:
        raise CacheIntegrityError(
            f"cannot write manifest: snapshot directory is empty: {snapshot_dir}"
        )
    payload = {rel: sha256_file(path) for rel, path in files.items()}
    out = manifest_path if manifest_path is not None else snapshot_dir / MANIFEST_FILENAME
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _seed_hint() -> str:
    return f"Fix: seed outside the offline runtime-vlm image with `{SEED_COMMAND}`."


def assert_remote_code_present(snapshot_dir: Path, on_disk: dict[str, Path]) -> None:
    """Florence-2 loads via trust_remote_code; safetensors alone still fail at load.

    Require at least one HF remote-code module (``modeling_*.py``, ``processing_*.py``,
    or ``configuration_*.py``) so a weights-only copy cannot pass the gate. Full
    Florence snapshots from the seeder include the full set; the gate only needs
    proof that remote code is present, not a second inventory of every module.
    """
    names = list(on_disk)
    remote_code = [
        n
        for n in names
        if n.endswith(".py")
        and (
            Path(n).name.startswith("modeling_")
            or Path(n).name.startswith("processing_")
            or Path(n).name.startswith("configuration_")
        )
    ]
    if not remote_code:
        raise CacheIntegrityError(
            f"VLM cache gate failed: trust_remote_code remote modules missing under "
            f"{snapshot_dir} (expected modeling_*.py / processing_*.py / "
            "configuration_*.py). Florence-2 offline load execs these .py files; "
            f"copying only safetensors is not enough. {_seed_hint()}"
        )


def verify_snapshot(snapshot_dir: Path, *, manifest_path: Path | None = None) -> None:
    """Fail closed if the snapshot does not match its manifest exactly.

    Raises ``CacheIntegrityError`` with a distinct message per failure mode.
    """
    if not snapshot_dir.is_dir():
        raise CacheIntegrityError(
            f"VLM cache gate failed: snapshot directory missing: {snapshot_dir}. "
            f"{_seed_hint()}"
        )

    on_disk = list_snapshot_files(snapshot_dir)
    manifest_file = manifest_path if manifest_path is not None else snapshot_dir / MANIFEST_FILENAME

    # Empty before/without manifest is its own signal (RB-05 half-seeded volume).
    if not on_disk and not manifest_file.is_file():
        raise CacheIntegrityError(
            f"VLM cache gate failed: snapshot directory is empty: {snapshot_dir}. "
            f"Seed weights + remote-code *.py files, then write the integrity manifest. "
            f"{_seed_hint()}"
        )

    if not manifest_file.is_file():
        raise CacheIntegrityError(
            f"VLM cache gate failed: manifest missing: {manifest_file}. "
            "After seeding a verified snapshot, run "
            "`python -m scripts.verify_vlm_cache --write-manifest` once "
            f"(trust-establishing; never re-run to silence a failing gate). {_seed_hint()}"
        )

    try:
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: manifest is not valid JSON: {manifest_file}: {exc}. "
            f"{_seed_hint()}"
        ) from exc

    if not isinstance(raw, dict) or not raw:
        raise CacheIntegrityError(
            f"VLM cache gate failed: manifest is empty or not an object: {manifest_file}. "
            f"{_seed_hint()}"
        )

    expected: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CacheIntegrityError(
                f"VLM cache gate failed: manifest entries must be string path -> sha256; "
                f"bad entry {key!r}: {value!r}"
            )
        expected[key] = value.lower()

    # Missing listed files.
    for rel in sorted(expected):
        if rel not in on_disk:
            raise CacheIntegrityError(
                f"VLM cache gate failed: file listed in manifest is missing: {rel} "
                f"(under {snapshot_dir}). {_seed_hint()}"
            )

    # Extra unlisted files (RB-02: attacker ADDS modeling .py / payload).
    extras = sorted(set(on_disk) - set(expected))
    if extras:
        preview = ", ".join(extras[:5])
        more = f" (+{len(extras) - 5} more)" if len(extras) > 5 else ""
        raise CacheIntegrityError(
            f"VLM cache gate failed: unlisted file(s) present in snapshot "
            f"(integrity set mismatch / possible cache tamper): {preview}{more}. "
            f"Do not re-run --write-manifest to silence this; re-seed. {_seed_hint()}"
        )

    # Digest mismatches.
    for rel in sorted(expected):
        actual = sha256_file(on_disk[rel])
        if actual != expected[rel]:
            raise CacheIntegrityError(
                f"VLM cache gate failed: sha256 mismatch for {rel}: "
                f"expected {expected[rel]}, got {actual}. "
                f"Cache contents differ from the certified manifest; do not rewrite the manifest. "
                f"{_seed_hint()}"
            )

    # Defense in depth: even a manifest of weights-only must not pass (Florence remote code).
    assert_remote_code_present(snapshot_dir, on_disk)


def resolve_verify_spec():
    """Resolve which ProfileSpec the gate must verify, or (None, skip_reason).

    Order:
    1. Active profile is LOCAL_CPU → verify that pin.
    2. Image variant is VLM → verify the default Florence pin even when the
       active adapter is seeded/remote (boot must still fail closed on empty cache).
    3. Else skip (narrow case: recognition image, no VLM weights expected).
    """
    from scene.config.profiles import DescriptionProfile, get_profile_spec
    from scene.config.settings import DescriptionSettings
    from scene.domain.description import DescriptionAdapterKind

    settings = DescriptionSettings()
    spec = get_profile_spec(settings.profile)
    if spec.adapter_kind is DescriptionAdapterKind.LOCAL_CPU:
        return spec, None

    variant = resolve_image_variant_label()
    if variant == ImageVariant.VLM.value:
        default_spec = get_profile_spec(DescriptionProfile(DEFAULT_VLM_VERIFY_PROFILE))
        return default_spec, None

    return None, (
        f"VLM cache gate skipped: profile={settings.profile.value!r} "
        f"adapter_kind={spec.adapter_kind.value!r} is not LOCAL_CPU "
        f"and image_variant={variant!r} is not {ImageVariant.VLM.value!r}"
    )


def run_gate(*, write_manifest_mode: bool = False, hub_cache: Path | None = None) -> int:
    """CLI body: verify (or write-manifest) unless the narrow skip case applies."""
    try:
        spec, skip_reason = resolve_verify_spec()
    except Exception as exc:  # noqa: BLE001 - gate must fail closed on config errors
        print(f"VLM cache gate failed: could not resolve description profile: {exc}", file=sys.stderr)
        return EXIT_FAIL

    if skip_reason is not None:
        print(skip_reason)
        return EXIT_OK

    if spec is None:  # pragma: no cover - paired with skip_reason
        print("VLM cache gate failed: internal profile resolution error", file=sys.stderr)
        return EXIT_FAIL
    if not spec.model_id or not spec.model_revision:
        print(
            f"VLM cache gate failed: profile {spec.profile.value!r} "
            "lacks pinned model_id/model_revision; cannot verify cache. "
            f"{_seed_hint()}",
            file=sys.stderr,
        )
        return EXIT_FAIL

    snapshot = resolve_snapshot_dir(spec.model_id, spec.model_revision, hub_cache=hub_cache)
    try:
        if write_manifest_mode:
            print(
                "WARNING: --write-manifest is a TRUST-ESTABLISHING act. "
                "It certifies whatever is on disk now. Run only on a freshly "
                "downloaded, out-of-band-verified snapshot — never to fix a failing gate.",
                file=sys.stderr,
            )
            out = write_manifest(snapshot)
            print(f"Wrote integrity manifest: {out} ({len(json.loads(out.read_text()))} files)")
            return EXIT_OK
        verify_snapshot(snapshot)
    except CacheIntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL

    print(
        f"VLM cache gate ok: {snapshot} "
        f"(profile={spec.profile.value} image_variant={resolve_image_variant_label()})"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed integrity gate for the Florence LOCAL_CPU snapshot under HF_HOME. "
            "On the VLM image, always verifies (default florence_small pin when profile "
            "is not LOCAL_CPU). No args: verify. --write-manifest: certify current disk "
            "contents (trust-establishing)."
        )
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help=(
            "Walk the pinned snapshot, compute sha256 digests, write "
            f"{MANIFEST_FILENAME}. TRUST-ESTABLISHING — not a repair tool."
        ),
    )
    parser.add_argument(
        "--hub-cache",
        default=None,
        help="Override HF hub cache root (default: HF_HUB_CACHE or $HF_HOME/hub).",
    )
    args = parser.parse_args(argv)
    hub = Path(args.hub_cache) if args.hub_cache else None
    return run_gate(write_manifest_mode=args.write_manifest, hub_cache=hub)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
