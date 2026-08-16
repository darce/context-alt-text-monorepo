"""Manifest load, media resolve (local-then-remote + pin), items.jsonl store."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
from http.client import HTTPSConnection
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest, load_manifest

Resolver = Callable[[str], list[str]]
Fetcher = Callable[[str, set[str]], bytes]

_PINNED_HOSTS: dict[str, set[str]] = {}


class ItemOutcomeStore:
    """Append-only legs/<stack_id>/items.jsonl writer/reader."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.path.exists():
            return records
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            _validate_record_dimensions(record)
            records.append(record)
        return records

    def latest(self, manifest_media_id: int, phase: str) -> dict[str, Any] | None:
        found: dict[str, Any] | None = None
        for record in self.read_all():
            if record.get("manifest_media_id") == manifest_media_id and record.get("phase") == phase:
                found = record
        return found

    def roster_ids(self) -> set[int]:
        return {int(r["manifest_media_id"]) for r in self.read_all() if "manifest_media_id" in r}

    def latest_analyze_by_media(self) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for record in self.read_all():
            if record.get("phase") == "analyze":
                out[int(record["manifest_media_id"])] = record
        return out


def decode_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            transposed = ImageOps.exif_transpose(image)
            width, height = transposed.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise BenchError("image_decode_failed", f"Pillow could not decode image: {exc}") from exc
    if width <= 0 or height <= 0:
        raise BenchError("image_dimensions_missing", "decoded dimensions are not positive")
    return int(width), int(height)


def load_bench_manifest(
    path: str | Path,
    images_dir: str | Path | None = None,
    require_detection_exhaustiveness: bool = False,
    *,
    skip_hash_verification: bool = False,
) -> GoldenManifest:
    images = None if images_dir is None else str(images_dir)
    manifest = load_manifest(str(path), images_dir=images, skip_hash_verification=skip_hash_verification)
    non_exhaustive: list[int] = []
    for entry in manifest.entries:
        exhaustive = bool(entry.face_boxes) and entry.face_count == len(entry.face_boxes)
        if not exhaustive:
            if require_detection_exhaustiveness:
                raise BenchError(
                    "gt_box_count_mismatch",
                    f"media_id={entry.media_id} face_count={entry.face_count} "
                    f"!= len(face_boxes)={len(entry.face_boxes)}",
                )
            non_exhaustive.append(entry.media_id)
    object.__setattr__(manifest, "_non_exhaustive_ids", frozenset(non_exhaustive))
    return manifest


def is_detection_exhaustive(entry: GoldenEntry) -> bool:
    return bool(entry.face_boxes) and entry.face_count == len(entry.face_boxes)


def non_exhaustive_ids(manifest: GoldenManifest) -> frozenset[int]:
    return frozenset(getattr(manifest, "_non_exhaustive_ids", ()))


def assert_baseline_superset(manifest_ids: set[int] | frozenset[int], baseline_ids: set[int] | frozenset[int]) -> None:
    missing = set(manifest_ids) - set(baseline_ids)
    if missing:
        raise BenchError(
            "baseline_not_superset",
            f"baseline is not a superset of the manifest; missing {sorted(missing)}",
        )


def assert_floor_fits_corpus(accepted_set_floor: float | int, n_entries: int) -> None:
    if isinstance(accepted_set_floor, int) and not isinstance(accepted_set_floor, bool) and accepted_set_floor > n_entries:
        raise BenchError(
            "accepted_set_floor_exceeds_corpus",
            f"integer accepted_set_floor {accepted_set_floor} > |manifest entries| {n_entries}",
        )


def pin_media_hosts(host: str, addresses: set[str]) -> set[str]:
    """First-wins per-host address-set pin for the process lifetime.

    Key is ``host.lower()`` only — trailing-dot and IDN forms are distinct
    keys. The cached value is the full address set from the first successful
    resolve (a multi-A answer pins every member); later resolves for the
    same key are ignored. HTTP fetch then selects ``sorted(pinned)[0]``.
    There is no production caller of ``reset_media_host_pins``; pins persist
    across run-dirs until process exit. Public-unicast checks and required
    sha256 still refuse a private rebind on the pinned set.
    """
    key = host.lower()
    existing = _PINNED_HOSTS.get(key)
    if existing is None:
        _PINNED_HOSTS[key] = set(addresses)
        return _PINNED_HOSTS[key]
    return existing


def reset_media_host_pins() -> None:
    """Test-only: clear the process pin cache. Unused on the production path."""
    _PINNED_HOSTS.clear()


def resolve_media_bytes(
    entry: GoldenEntry,
    images_dir: str | Path | None,
    *,
    url_map_path: str | Path | None = None,
    allow_private_source: bool = False,
    resolver: Resolver | None = None,
    fetcher: Fetcher | None = None,
) -> bytes:
    if images_dir is not None:
        local = Path(images_dir) / entry.path
        if local.is_file():
            data = local.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if entry.sha256 and digest != entry.sha256:
                raise BenchError("media_unresolvable", f"sha256 mismatch for {entry.path}")
            return data

    url = _remote_url(entry, url_map_path)
    if url:
        data = _fetch_remote(
            url,
            allow_private_source=allow_private_source,
            resolver=resolver,
            fetcher=fetcher,
        )
        if entry.sha256:
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry.sha256:
                raise BenchError("media_unresolvable", f"sha256 mismatch for remote {entry.path}")
        return data
    raise BenchError("media_unresolvable", f"no local file or remote URL for {entry.path}")


def _remote_url(entry: GoldenEntry, url_map_path: str | Path | None) -> str | None:
    if entry.provenance is not None and entry.provenance.url:
        return entry.provenance.url
    if url_map_path is None:
        return None
    raw = json.loads(Path(url_map_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    for key in (entry.path, str(entry.media_id), str(entry.sha256)):
        if key in raw:
            return str(raw[key])
    return None


def _fetch_remote(
    url: str,
    *,
    allow_private_source: bool,
    resolver: Resolver | None,
    fetcher: Fetcher | None,
    hops: int = 0,
) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BenchError("media_unresolvable", f"remote URL must be https: {url}")
    host = parsed.hostname
    addresses = set((resolver or _default_resolve)(host))
    pinned = pin_media_hosts(host, addresses)
    if addresses != pinned and not addresses.issubset(pinned):
        raise BenchError("media_unresolvable", f"DNS pin mismatch for {host}: {addresses} vs {pinned}")
    use_addrs = pinned
    if not allow_private_source:
        for addr in use_addrs:
            if _is_non_public(addr):
                raise BenchError("media_unresolvable", f"refusing non-public-unicast address {addr} for {host}")
    if fetcher is not None:
        return fetcher(url, use_addrs)
    return _http_fetch_pinned(
        url,
        use_addrs,
        allow_private_source=allow_private_source,
        resolver=resolver,
        hops=hops,
    )


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addrs: list[str] = []
    for info in infos:
        addrs.append(info[4][0])
    return addrs


_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _is_non_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    if ip.version == 4 and ip in _CGNAT:
        return True
    if ip.version == 6 and ip in _NAT64:
        return True
    if ip.is_unspecified or not ip.is_global:
        return True
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


def _http_fetch_pinned(
    url: str,
    pinned_addrs: set[str],
    *,
    allow_private_source: bool,
    resolver: Resolver | None,
    hops: int,
) -> bytes:
    if hops > 5:
        raise BenchError("media_unresolvable", f"too many redirects fetching {url}")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BenchError("media_unresolvable", f"remote URL must be https: {url}")
    target = sorted(pinned_addrs)[0]
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    status, headers, body = _https_get_pinned(parsed.hostname, port, path, target)
    if status in {301, 302, 303, 307, 308}:
        location = headers.get("location")
        if not location:
            raise BenchError("media_unresolvable", f"redirect from {url} missing Location")
        return _fetch_remote(
            _absolute_https_redirect(url, location),
            allow_private_source=allow_private_source,
            resolver=resolver,
            fetcher=None,
            hops=hops + 1,
        )
    if status >= 400:
        raise BenchError("media_unresolvable", f"GET {url} returned {status}")
    return body


def _absolute_https_redirect(base_url: str, location: str) -> str:
    resolved = urljoin(base_url, location.strip())
    parsed = urlparse(resolved)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BenchError("media_unresolvable", f"redirect is not https: {resolved}")
    return resolved


def _https_get_pinned(host: str, port: int, path: str, pinned_ip: str) -> tuple[int, dict[str, str], bytes]:
    context = ssl.create_default_context()
    conn = HTTPSConnection(host, port=port, timeout=30.0, context=context)

    def _connect() -> None:
        sock = socket.create_connection((pinned_ip, port), 30.0)
        conn.sock = context.wrap_socket(sock, server_hostname=host)

    conn.connect = _connect  # type: ignore[method-assign]
    conn.request("GET", path, headers={"Host": host})
    response = conn.getresponse()
    payload = response.read()
    hdrs = {k.lower(): v for k, v in response.getheaders()}
    status = response.status
    conn.close()
    return status, hdrs, payload


def _validate_record_dimensions(record: dict[str, Any]) -> None:
    if record.get("outcome") != "ok":
        return
    for key in ("image_width", "image_height"):
        value = record.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise BenchError("image_dimensions_missing", f"{key} missing/non-positive on ok record")
