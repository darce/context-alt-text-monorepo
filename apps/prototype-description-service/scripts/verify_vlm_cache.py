"""Fail-closed VLM cache integrity gate for the runtime-vlm image boot path.

Invoked as ``python -m scripts.verify_vlm_cache`` with no required arguments
(docker-entrypoint runs this when the baked image variant is VLM).

When the gate runs a LOCAL_CPU profile, exit 0 only when the pinned HF snapshot
under HF_HOME matches its integrity manifest exactly, the on-disk manifest's
own sha256 matches the image-baked root of trust (when present),
trust_remote_code modeling ``*.py`` files are present, **and** the HuggingFace
module cache (``HF_MODULES_CACHE``) is present and writable.

Non-LOCAL_CPU profiles (``seeded``, ``gpu_qwen30b``, …) skip the Florence pin
so they can boot under ``set -eu``. On a VLM image with an explicit HF cache
env, a weaker check still requires the mounted hub root to be non-empty, and
verifies any present pinned Florence snapshot against its manifest.

Manifest + root of trust
------------------------
The inventory manifest (``acx-vlm-cache.manifest.json``) lives next to the
weights so the seeder can write it in one gesture. That file alone is
self-referential inside the mutable volume — an attacker who rewrites weights
and re-runs ``--write-manifest`` would pass. The **root of trust** is therefore
detached from the volume:

* env ``ACX_VLM_MANIFEST_SHA256`` (preferred; Dockerfile ARG→ENV), or
* file ``/app/acx-vlm-cache.manifest.sha256`` (build-baked, chmod 0444)

holding the sha256 of the manifest bytes. When either pin is present the gate
requires a match before trusting the inventory. When absent (local unit tests,
unpinned dev), inventory-vs-tree checks still run.

TRUST-ESTABLISHING act (sr-001 / RLSE-02)
-----------------------------------------
``--write-manifest`` certifies whatever is on disk at that moment. Run it only
against a freshly downloaded, out-of-band-verified snapshot — never to "fix"
a failing gate. After seeding, bake the printed manifest sha256 into the image.

Image variant constants (sr-007)
--------------------------------
``ImageVariant`` / ``IMAGE_VARIANT_ENV`` are the single importable source of
truth for the recognition vs VLM labels. Resolution prefers the build-immutable
artifact ``/app/.image-variant`` (same fail-closed mismatch rule as
``api.main._resolve_image_variant``); ENV alone is non-authoritative under
compose ``env_file`` overrides.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from shared.image_variant import (
    DEFAULT_IMAGE_VARIANT,
    IMAGE_VARIANT_ARTIFACT,
    IMAGE_VARIANT_ENV,
    ImageVariant,
)

# Inventory of relative_path -> sha256; lives next to weights; excluded from set.
MANIFEST_FILENAME = "acx-vlm-cache.manifest.json"
_HASH_CHUNK = 1024 * 1024  # 1 MiB — never load multi-GB shards whole.

# Detached root of trust for the manifest itself (outside the mounted volume).
MANIFEST_SHA256_ENV = "ACX_VLM_MANIFEST_SHA256"
# Module-level so tests can monkeypatch; production path is fixed.
MANIFEST_SHA256_FILE = Path("/app/acx-vlm-cache.manifest.sha256")

# Operator-facing seed hint — path-agnostic (rg-006). Host models dir varies
# (/opt/acx-backend/prod/... on the VM; never hardcode a container-only path).
SEED_COMMAND = "uv run --extra vlm python -m scripts.seed_vlm_cache --hf-home <ACX_MODELS_PATH>/huggingface_cache"
SEED_HINT_NOTE = "Run on the host from apps/prototype-description-service (not inside the offline runtime-vlm image)."

EXIT_OK = 0
EXIT_FAIL = 1

# Opt-in full Florence pin verify even for non-LOCAL_CPU profiles.
REQUIRE_VLM_CACHE_ENV = "ACX_REQUIRE_VLM_CACHE"


# Env key for the HF trust_remote_code module cache (Lane A sets this in-image).
# Never hardcode the path — read it from the environment so the gate stays
# aligned with the runtime layout (private writable tmpfs vs read-only weights).
HF_MODULES_CACHE_ENV = "HF_MODULES_CACHE"


class CacheIntegrityError(RuntimeError):
    """Actionable integrity failure; message is printed and mapped to EXIT_FAIL."""


def resolve_image_variant_label() -> str:
    """Return the image variant the running process actually has (rg-015).

    Prefers the build-immutable bake at ``IMAGE_VARIANT_ARTIFACT``
    (``/app/.image-variant``). Compose ``env_file`` can override
    ``ACX_IMAGE_VARIANT`` ENV, so ENV alone fails open. Same fail-closed
    mismatch rule as ``api.main._resolve_image_variant``:

    * bake present + valid → return bake; non-empty env that disagrees raises
    * bake present + invalid / unreadable → raise (never report recognition)
    * bake absent (local dev / unit tests) → env claim or recognition default
    """
    env_claim = (os.environ.get(IMAGE_VARIANT_ENV) or "").strip()
    baked = ""
    try:
        if IMAGE_VARIANT_ARTIFACT.is_file():
            baked = IMAGE_VARIANT_ARTIFACT.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: cannot read baked image variant at {IMAGE_VARIANT_ARTIFACT}: {exc}"
        ) from exc
    if baked:
        if baked not in {ImageVariant.RECOGNITION.value, ImageVariant.VLM.value}:
            raise CacheIntegrityError(
                f"VLM cache gate failed: invalid baked image variant {baked!r} at {IMAGE_VARIANT_ARTIFACT}"
            )
        if env_claim and env_claim != baked:
            raise CacheIntegrityError(
                f"VLM cache gate failed: ACX_IMAGE_VARIANT={env_claim!r} disagrees "
                f"with baked {baked!r} at {IMAGE_VARIANT_ARTIFACT}"
            )
        return baked
    return env_claim or DEFAULT_IMAGE_VARIANT.value


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


def hf_cache_explicitly_configured() -> bool:
    """True when HF_HUB_CACHE or HF_HOME is set (mounted-cache intent)."""
    return bool((os.environ.get("HF_HUB_CACHE") or "").strip() or (os.environ.get("HF_HOME") or "").strip())


def model_cache_dirname(model_id: str) -> str:
    """``microsoft/Florence-2-base-ft`` -> ``models--microsoft--Florence-2-base-ft``."""
    return "models--" + model_id.replace("/", "--")


def resolve_snapshot_dir(model_id: str, model_revision: str, *, hub_cache: Path | None = None) -> Path:
    root = hub_cache if hub_cache is not None else resolve_hf_hub_cache()
    return root / model_cache_dirname(model_id) / "snapshots" / model_revision


def resolve_modules_cache() -> Path | None:
    """Return the configured HF modules cache path, or None when unset/blank."""
    raw = os.environ.get(HF_MODULES_CACHE_ENV)
    if raw is None or not str(raw).strip():
        return None
    return Path(str(raw).strip())


def resolve_manifest_trust_pin() -> str | None:
    """Return the detached expected sha256 of the inventory manifest, or None.

    Root of trust lives outside the mounted weight volume (A-03 / V-04):
    env ``ACX_VLM_MANIFEST_SHA256`` first, then ``/app/acx-vlm-cache.manifest.sha256``.
    """
    env_pin = (os.environ.get(MANIFEST_SHA256_ENV) or "").strip().lower()
    if env_pin:
        return env_pin
    try:
        if MANIFEST_SHA256_FILE.is_file():
            return MANIFEST_SHA256_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: cannot read manifest trust pin at {MANIFEST_SHA256_FILE}: {exc}"
        ) from exc
    return None


def assert_modules_cache_ready() -> None:
    """Fail closed unless ``HF_MODULES_CACHE`` exists and is writable.

    ``trust_remote_code=True`` imports modeling modules from this cache, not
    from the weight snapshot. A green snapshot check with a missing or
    read-only module cache is the D2 outage: gate says ok, then inference dies.
    Path is always read from the environment — never hardcoded (XL-2 / D2).
    """
    modules = resolve_modules_cache()
    if modules is None:
        raise CacheIntegrityError(
            f"VLM cache gate failed: {HF_MODULES_CACHE_ENV} is unset or blank. "
            "Florence trust_remote_code imports require a writable module cache "
            f"(set {HF_MODULES_CACHE_ENV} in the image/runtime). {_seed_hint()}"
        )
    if not modules.is_dir():
        raise CacheIntegrityError(
            f"VLM cache gate failed: module cache directory missing: {modules} ({HF_MODULES_CACHE_ENV}). {_seed_hint()}"
        )
    probe = modules / ".acx_modules_cache_write_probe"
    try:
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: module cache is not writable: {modules} "
            f"({HF_MODULES_CACHE_ENV}): {exc}. "
            "Weights may be read-only; the module cache must remain writable "
            f"for trust_remote_code imports. {_seed_hint()}"
        ) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _allowed_symlink_root(snapshot_dir: Path) -> Path:
    """HF hub puts blobs next to ``snapshots/``; allow symlink targets under model root."""
    # snapshot_dir = <model>/snapshots/<rev> → model root is parent.parent
    try:
        return snapshot_dir.resolve().parent.parent
    except OSError:
        return snapshot_dir.resolve()


def list_snapshot_files(snapshot_dir: Path) -> dict[str, Path]:
    """Map relative POSIX paths -> paths for every certified file under the snapshot.

    Enumerates with ``os.scandir`` recursion (``follow_symlinks=False``) so
    symlink directories are not silently skipped or followed into attacker trees
    (A-10). Classification:

    * regular file → include (hash later)
    * symlink whose target resolves to a regular file inside the HF model tree
      (``snapshots/../`` including ``blobs/``) → include
    * anything else (dir symlink, out-of-tree symlink, special file) → fail closed

    The integrity manifest itself is excluded so it is not self-referential in
    the inventory set.
    """
    files: dict[str, Path] = {}
    if not snapshot_dir.is_dir():
        return files

    allowed_root = _allowed_symlink_root(snapshot_dir)

    def _visit(current: Path) -> None:
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise CacheIntegrityError(
                f"VLM cache gate failed: cannot enumerate snapshot directory {current}: {exc}. {_seed_hint()}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                rel = path.relative_to(snapshot_dir).as_posix()
            except ValueError:
                raise CacheIntegrityError(f"VLM cache gate failed: snapshot entry escaped tree: {path}") from None
            if entry.is_symlink():
                try:
                    target = path.resolve(strict=True)
                except OSError as exc:
                    raise CacheIntegrityError(
                        f"VLM cache gate failed: broken symlink in snapshot: {rel} ({exc}). {_seed_hint()}"
                    ) from exc
                try:
                    target.relative_to(allowed_root)
                except ValueError as exc:
                    raise CacheIntegrityError(
                        f"VLM cache gate failed: symlink {rel} resolves outside "
                        f"the HF model tree ({target} not under {allowed_root}). "
                        f"{_seed_hint()}"
                    ) from exc
                if not target.is_file():
                    raise CacheIntegrityError(
                        f"VLM cache gate failed: symlink {rel} does not resolve "
                        f"to a regular file ({target}). {_seed_hint()}"
                    )
                if rel == MANIFEST_FILENAME:
                    continue
                files[rel] = path
            elif entry.is_file(follow_symlinks=False):
                if rel == MANIFEST_FILENAME:
                    continue
                files[rel] = path
            elif entry.is_dir(follow_symlinks=False):
                _visit(path)
            else:
                raise CacheIntegrityError(
                    f"VLM cache gate failed: unsupported snapshot entry type: {rel}. {_seed_hint()}"
                )

    _visit(snapshot_dir)
    return dict(sorted(files.items()))


def write_manifest(snapshot_dir: Path, *, manifest_path: Path | None = None) -> Path:
    """Walk ``snapshot_dir``, hash every file, write the integrity manifest.

    TRUST-ESTABLISHING: this certifies the current on-disk contents. Do not run
    it to silence a failing gate — only against a freshly seeded, verified tree.
    Prints the detached trust pin (sha256 of the manifest bytes) for image bake.
    """
    if not snapshot_dir.is_dir():
        raise CacheIntegrityError(f"cannot write manifest: snapshot directory missing: {snapshot_dir}")
    files = list_snapshot_files(snapshot_dir)
    if not files:
        raise CacheIntegrityError(f"cannot write manifest: snapshot directory is empty: {snapshot_dir}")
    payload = {rel: sha256_file(path) for rel, path in files.items()}
    out = manifest_path if manifest_path is not None else snapshot_dir / MANIFEST_FILENAME
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    out.write_text(text, encoding="utf-8")
    return out


def manifest_content_sha256(manifest_path: Path) -> str:
    """sha256 of the manifest file bytes (detached root-of-trust pin value)."""
    return sha256_file(manifest_path)


def _seed_hint() -> str:
    return f"Fix: {SEED_HINT_NOTE} `{SEED_COMMAND}`."


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


def assert_manifest_trust_pin(manifest_file: Path) -> None:
    """When a detached pin is configured, require the on-disk manifest sha256 match."""
    pin = resolve_manifest_trust_pin()
    if pin is None:
        return
    actual = manifest_content_sha256(manifest_file)
    if actual != pin:
        raise CacheIntegrityError(
            f"VLM cache gate failed: manifest trust pin mismatch for {manifest_file}: "
            f"expected {pin}, got {actual}. The inventory inside the volume does not "
            f"match the image-baked root of trust ({MANIFEST_SHA256_ENV} or "
            f"{MANIFEST_SHA256_FILE}). Re-seed and re-bake the pin; do not rewrite "
            f"the pin to silence this. {_seed_hint()}"
        )


def verify_snapshot(snapshot_dir: Path, *, manifest_path: Path | None = None) -> None:
    """Fail closed if the snapshot does not match its manifest exactly.

    Raises ``CacheIntegrityError`` with a distinct message per failure mode.
    """
    if not snapshot_dir.is_dir():
        raise CacheIntegrityError(f"VLM cache gate failed: snapshot directory missing: {snapshot_dir}. {_seed_hint()}")

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

    # Detached root of trust (A-03 / V-04): pin the manifest itself outside the volume.
    assert_manifest_trust_pin(manifest_file)

    try:
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: manifest is not valid JSON: {manifest_file}: {exc}. {_seed_hint()}"
        ) from exc

    if not isinstance(raw, dict) or not raw:
        raise CacheIntegrityError(
            f"VLM cache gate failed: manifest is empty or not an object: {manifest_file}. {_seed_hint()}"
        )

    expected: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CacheIntegrityError(
                f"VLM cache gate failed: manifest entries must be string path -> sha256; bad entry {key!r}: {value!r}"
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


def _require_vlm_cache_opt_in() -> bool:
    raw = (os.environ.get(REQUIRE_VLM_CACHE_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def assert_vlm_hub_weak(hub_cache: Path, *, florence_spec) -> None:
    """Weaker VLM-image check when the active adapter is not LOCAL_CPU (S3-A-07).

    * Mounted hub root (explicit HF_* env) must be non-empty.
    * If the default Florence snapshot dir exists, it must match its manifest.
    """
    if not hub_cache.is_dir():
        raise CacheIntegrityError(
            f"VLM cache gate failed: VLM image HF hub cache missing: {hub_cache}. "
            f"Mount a seeded host cache or set HF_HUB_CACHE. {_seed_hint()}"
        )
    # Non-empty: any file/dir entry other than '.'
    try:
        next(hub_cache.iterdir())
    except StopIteration as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: VLM image HF hub cache is empty: {hub_cache}. "
            f"Seed weights on the host and mount them read-only. {_seed_hint()}"
        ) from exc
    except OSError as exc:
        raise CacheIntegrityError(
            f"VLM cache gate failed: cannot read VLM HF hub cache {hub_cache}: {exc}. {_seed_hint()}"
        ) from exc

    if florence_spec is not None and florence_spec.model_id and florence_spec.model_revision:
        snap = resolve_snapshot_dir(florence_spec.model_id, florence_spec.model_revision, hub_cache=hub_cache)
        if snap.is_dir():
            verify_snapshot(snap)


def resolve_verify_spec():
    """Resolve which ProfileSpec the gate must verify, or (None, skip_reason).

    Full Florence offline pin (snapshot + modules + optional trust pin):

    1. Active profile is LOCAL_CPU → verify that profile's pin.
    2. ``ACX_REQUIRE_VLM_CACHE=1`` opt-in → same full pin (intent, not image id).
    3. Else non-LOCAL_CPU on a VLM image with explicit HF cache env → weak hub
       check (S3-A-07); may still raise ``CacheIntegrityError``.
    4. Else skip — ``seeded`` / ``gpu_qwen30b`` without a mounted cache must boot.
    """
    from scene.config.profiles import DescriptionProfile, get_profile_spec
    from scene.config.settings import DescriptionSettings
    from scene.domain.description import DescriptionAdapterKind

    settings = DescriptionSettings()
    spec = get_profile_spec(settings.profile)
    if spec.adapter_kind is DescriptionAdapterKind.LOCAL_CPU:
        return spec, None
    if _require_vlm_cache_opt_in():
        # Opt-in forces the default Florence LOCAL_CPU pin regardless of adapter.
        florence = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
        return florence, None

    variant = resolve_image_variant_label()
    if variant == ImageVariant.VLM.value and hf_cache_explicitly_configured():
        # Weak path: raise on empty hub / bad present snapshot; otherwise skip.
        florence = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
        assert_vlm_hub_weak(resolve_hf_hub_cache(), florence_spec=florence)
        return None, (
            f"VLM cache gate: weak hub check ok; full Florence pin skipped "
            f"(profile={settings.profile.value!r} "
            f"adapter_kind={spec.adapter_kind.value!r} image_variant={variant!r})"
        )

    return None, (
        f"VLM cache gate skipped: profile={settings.profile.value!r} "
        f"adapter_kind={spec.adapter_kind.value!r} does not need the Florence "
        f"offline pin (image_variant={variant!r})"
    )


def run_gate(*, write_manifest_mode: bool = False, hub_cache: Path | None = None) -> int:
    """CLI body: verify (or write-manifest) unless the narrow skip case applies."""
    try:
        spec, skip_reason = resolve_verify_spec()
    except CacheIntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL
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
            pin = manifest_content_sha256(out)
            print(f"Wrote integrity manifest: {out} ({len(json.loads(out.read_text()))} files)")
            print(
                f"Detached trust pin (bake into image): {MANIFEST_SHA256_ENV}={pin} "
                f"or write that hex to {MANIFEST_SHA256_FILE}"
            )
            return EXIT_OK
        verify_snapshot(snapshot)
        # Module cache is required for trust_remote_code imports at inference
        # time; check after snapshot integrity so failure modes stay distinct.
        assert_modules_cache_ready()
    except CacheIntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL

    modules = resolve_modules_cache()
    print(
        f"VLM cache gate ok: {snapshot} "
        f"(profile={spec.profile.value} image_variant={resolve_image_variant_label()} "
        f"modules_cache={modules})"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed integrity gate for the Florence LOCAL_CPU snapshot under HF_HOME "
            "and the writable HF_MODULES_CACHE used by trust_remote_code. "
            "Full pin runs when the active profile is LOCAL_CPU (or ACX_REQUIRE_VLM_CACHE=1). "
            "Non-Florence adapters on the VLM image get a weaker non-empty hub check when "
            "HF_HOME/HF_HUB_CACHE is set. No args: verify. --write-manifest: certify current "
            "disk contents (trust-establishing)."
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
