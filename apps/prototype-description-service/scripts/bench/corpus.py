"""Manifest load, media resolve (local-then-remote + pin), items.jsonl store."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
import time
from http.client import HTTPSConnection
from io import BytesIO, DEFAULT_BUFFER_SIZE, BufferedReader, BufferedRWPair, BufferedWriter, TextIOWrapper
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from scripts.bench.stack_pair import BenchError
from scripts.eval_harness._pathtext import _printable_message, _printable_path
from scripts.eval_harness.manifest import (
    GoldenEntry,
    GoldenManifest,
    ManifestError,
    load_manifest,
    resolve_image_path,
)

Resolver = Callable[[str], list[str]]
Fetcher = Callable[[str, set[str]], bytes]

_PINNED_HOSTS: dict[str, set[str]] = {}

# Conservative remote-image cap. Golden-corpus photos and WordPress-scaled
# JPEGs are typically well under 5 MiB; 8 MiB leaves headroom for high-res
# originals without allowing unbounded socket reads ([DATA-13] [RES-02]).
REMOTE_FETCH_MAX_BYTES = 8 * 1024 * 1024
# One absolute budget for the whole redirect chain, including connect/TLS/
# request/headers/body. Matches the previous per-phase 30s socket timeout but
# does not reset on hops ([API-04] [RES-02]).
REMOTE_FETCH_DEADLINE_S = 30.0


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
    metadata_only: bool = False,
    hash_skip_reason: str | None = None,
) -> GoldenManifest:
    images = None if images_dir is None else str(images_dir)
    # Do not infer metadata_only from skip + images_dir=None (rg-015).
    # Callers that never open image bytes must pass metadata_only=True
    # and a hash_skip_reason; pixel paths leave both at defaults.
    manifest = load_manifest(
        str(path),
        images_dir=images,
        skip_hash_verification=skip_hash_verification,
        hash_skip_reason=hash_skip_reason,
        metadata_only=metadata_only,
    )
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
        try:
            local = resolve_image_path(images_dir, entry.path)
        except ManifestError as exc:
            raise BenchError("media_unresolvable", str(exc)) from exc
        if local is not None:
            try:
                data = local.read_bytes()
            except OSError as exc:
                raise BenchError(
                    "media_resource_failed",
                    f"could not read local media {_printable_path(entry.path)}: {exc}",
                ) from exc
            return _verify_media_bytes(data, entry.sha256, source="local", path=entry.path)

    url = _remote_url(entry, url_map_path)
    if url:
        data = _fetch_remote(
            url,
            allow_private_source=allow_private_source,
            resolver=resolver,
            fetcher=fetcher,
        )
        return _verify_media_bytes(data, entry.sha256, source="remote", path=entry.path)
    raise BenchError(
        "media_unresolvable",
        f"no local file or remote URL for {_printable_path(entry.path)}",
    )


def _verify_media_bytes(data: object, expected_sha256: str, *, source: str, path: str) -> bytes:
    """Validate the resolver's byte contract and the manifest content pin.

    The hash check is deliberately immediately before the caller can decode or
    upload the payload. That keeps a source failure a typed ingest failure and
    makes the content pin effective for both local and remote resolution
    ([RES-03] slow/failed integration points must not become success signals).
    """
    if not isinstance(data, bytes):
        raise BenchError(
            "media_resource_failed",
            f"{source} media resolver returned {type(data).__name__}, expected bytes "
            f"for {_printable_path(path)}",
        )
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        qualifier = "remote" if source == "remote" else "local"
        raise BenchError(
            "media_unresolvable",
            f"sha256 mismatch for {qualifier} {_printable_path(path)}",
        )
    return data


def _remote_url(entry: GoldenEntry, url_map_path: str | Path | None) -> str | None:
    if entry.provenance is not None and entry.provenance.url:
        return entry.provenance.url
    if url_map_path is None:
        return None
    try:
        raw = json.loads(Path(url_map_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise BenchError(
            "media_resource_failed",
            f"could not read media URL map {_printable_path(url_map_path)}: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise BenchError(
            "media_resource_failed",
            f"media URL map {_printable_path(url_map_path)} must be a JSON object",
        )
    for key in (entry.path, str(entry.media_id), str(entry.sha256)):
        if key in raw:
            value = raw[key]
            if not isinstance(value, str) or not value.strip():
                raise BenchError(
                    "media_resource_failed",
                    f"media URL map {_printable_path(url_map_path)} has an invalid URL "
                    f"for {_printable_path(entry.path)}",
                )
            return value
    return None


def _fetch_remote(
    url: str,
    *,
    allow_private_source: bool,
    resolver: Resolver | None,
    fetcher: Fetcher | None,
    hops: int = 0,
    deadline_at: float | None = None,
) -> bytes:
    deadline_at = _absolute_deadline(deadline_at)
    _remaining_timeout(deadline_at)
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except (TypeError, ValueError) as exc:
        raise BenchError(
            "media_unresolvable",
            f"remote URL is malformed: {_printable_message(url)}",
        ) from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise BenchError(
            "media_unresolvable",
            f"remote URL must be https: {_printable_message(url)}",
        )
    try:
        addresses = set((resolver or _default_resolve)(host))
    except BenchError:
        raise
    except Exception as exc:  # noqa: BLE001 — DNS implementations vary by platform
        raise BenchError(
            "media_resource_failed",
            f"could not resolve media host {host}: {exc}",
        ) from exc
    if not addresses:
        raise BenchError("media_resource_failed", f"media host {host} returned no addresses")
    if not all(isinstance(address, str) for address in addresses):
        raise BenchError(
            "media_resource_failed",
            f"media host {host} returned a non-text address",
        )
    try:
        pinned = pin_media_hosts(host, addresses)
        if addresses != pinned and not addresses.issubset(pinned):
            raise BenchError(
                "media_unresolvable",
                f"DNS pin mismatch for {host}: {addresses} vs {pinned}",
            )
        use_addrs = pinned
        if not use_addrs:
            raise BenchError("media_resource_failed", f"media host {host} has no pinned addresses")
        if not allow_private_source:
            for addr in use_addrs:
                if _is_non_public(addr):
                    raise BenchError(
                        "media_unresolvable",
                        f"refusing non-public-unicast address {addr} for {host}",
                    )
    except BenchError:
        raise
    except Exception as exc:  # noqa: BLE001 — pin/address implementations vary
        raise BenchError(
            "media_resource_failed",
            f"could not validate pinned media host {host}: {exc}",
        ) from exc
    if fetcher is not None:
        try:
            data = fetcher(url, use_addrs)
        except BenchError:
            raise
        except Exception as exc:  # noqa: BLE001 — injected/HTTP transports vary
            raise BenchError(
                "media_resource_failed",
                f"remote media fetch failed for {_printable_message(url)}: {exc}",
            ) from exc
        if not isinstance(data, bytes):
            raise BenchError(
                "media_resource_failed",
                f"remote media fetch returned {type(data).__name__}, expected bytes",
            )
        return data
    try:
        # [RES-02][RES-03] Keep the socket connect/read bounded and turn slow or
        # broken integration points into explicit resource failures.
        return _http_fetch_pinned(
            url,
            use_addrs,
            allow_private_source=allow_private_source,
            resolver=resolver,
            hops=hops,
            deadline_at=deadline_at,
        )
    except BenchError:
        raise
    except Exception as exc:  # noqa: BLE001 — socket/TLS errors are resource failures
        raise BenchError(
            "media_resource_failed",
            f"remote media fetch failed for {_printable_message(url)}: {exc}",
        ) from exc


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
    deadline_at: float | None = None,
) -> bytes:
    deadline_at = _absolute_deadline(deadline_at)
    _remaining_timeout(deadline_at)
    if hops > 5:
        raise BenchError(
            "media_unresolvable",
            f"too many redirects fetching {_printable_message(url)}",
        )
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except (TypeError, ValueError) as exc:
        raise BenchError(
            "media_unresolvable",
            f"remote URL is malformed: {_printable_message(url)}",
        ) from exc
    if parsed.scheme != "https" or not hostname:
        raise BenchError(
            "media_unresolvable",
            f"remote URL must be https: {_printable_message(url)}",
        )
    if not pinned_addrs:
        raise BenchError("media_resource_failed", "remote media has no pinned address")
    target = sorted(pinned_addrs)[0]
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise BenchError(
            "media_unresolvable",
            f"remote URL has an invalid port: {_printable_message(url)}",
        ) from exc
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    status, headers, body = _https_get_pinned(
        hostname, port, path, target, deadline_at=deadline_at
    )
    if status in {301, 302, 303, 307, 308}:
        location = headers.get("location")
        if not location:
            raise BenchError(
                "media_unresolvable",
                f"redirect from {_printable_message(url)} missing Location",
            )
        return _fetch_remote(
            _absolute_https_redirect(url, location),
            allow_private_source=allow_private_source,
            resolver=resolver,
            fetcher=None,
            hops=hops + 1,
            deadline_at=deadline_at,
        )
    if status >= 400:
        raise BenchError(
            "media_unresolvable",
            f"GET {_printable_message(url)} returned {status}",
        )
    return body


def _absolute_https_redirect(base_url: str, location: str) -> str:
    try:
        resolved = urljoin(base_url, location.strip())
        parsed = urlparse(resolved)
        hostname = parsed.hostname
    except (AttributeError, TypeError, ValueError) as exc:
        raise BenchError(
            "media_unresolvable",
            f"redirect URL is malformed: {_printable_message(location)}",
        ) from exc
    if parsed.scheme != "https" or not hostname:
        raise BenchError(
            "media_unresolvable",
            f"redirect is not https: {_printable_message(resolved)}",
        )
    return resolved


def _absolute_deadline(deadline_at: float | None) -> float:
    if deadline_at is None:
        return time.monotonic() + REMOTE_FETCH_DEADLINE_S
    return deadline_at


def _remaining_timeout(deadline_at: float) -> float:
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        raise BenchError("media_resource_failed", "remote media fetch deadline exceeded")
    return remaining


def _apply_sock_timeout(sock: object, timeout: float) -> None:
    setter = getattr(sock, "settimeout", None)
    if callable(setter):
        setter(timeout)


def _deadline_exceeded(exc: BaseException | None = None) -> BenchError:
    error = BenchError("media_resource_failed", "remote media fetch deadline exceeded")
    if exc is not None:
        raise error from exc
    raise error


class _DeadlineSocket:
    """Socket stand-in that refreshes the remaining wall-clock budget per I/O.

    HTTPResponse parses status/headers via makefile readline before
    getresponse returns, and Connection: close detaches conn.sock. The
    makefile must use this object's recv so the absolute deadline survives
    that detach ([API-04] Latency, [RES-02]).
    """

    def __init__(self, sock: object, deadline_at: float) -> None:
        self._sock = sock
        self._deadline_at = deadline_at
        self._io_refs = 0
        self._closed = False

    def _refresh(self) -> None:
        _apply_sock_timeout(self._sock, _remaining_timeout(self._deadline_at))

    def _call(self, orig_name: str, *args: Any, **kwargs: Any) -> Any:
        orig = getattr(self._sock, orig_name)
        self._refresh()
        try:
            return orig(*args, **kwargs)
        except (TimeoutError, socket.timeout) as exc:
            raise _deadline_exceeded(exc)

    def recv(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("recv", *args, **kwargs)

    def recv_into(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("recv_into", *args, **kwargs)

    def send(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("send", *args, **kwargs)

    def sendall(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("sendall", *args, **kwargs)

    def settimeout(self, timeout: object) -> None:
        if timeout is not None:
            _apply_sock_timeout(self._sock, float(timeout))

    def gettimeout(self) -> object:
        getter = getattr(self._sock, "gettimeout", None)
        if callable(getter):
            return getter()
        return None

    def makefile(
        self,
        mode: str = "r",
        buffering: int | None = None,
        *,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> Any:
        if not set(mode) <= {"r", "w", "b"}:
            raise ValueError(f"invalid mode {mode!r}")
        writing = "w" in mode
        reading = "r" in mode or not writing
        binary = "b" in mode
        rawmode = ("r" if reading else "") + ("w" if writing else "")
        raw = socket.SocketIO(self, rawmode)  # type: ignore[arg-type]
        self._io_refs += 1
        if buffering is None:
            buffering = -1
        if buffering < 0:
            buffering = DEFAULT_BUFFER_SIZE
        if buffering == 0:
            if not binary:
                raise ValueError("unbuffered streams must be binary")
            return raw
        if reading and writing:
            buffer: Any = BufferedRWPair(raw, raw, buffering)
        elif reading:
            buffer = BufferedReader(raw, buffering)
        else:
            buffer = BufferedWriter(raw, buffering)
        if binary:
            return buffer
        text = TextIOWrapper(buffer, encoding, errors, newline)
        text.mode = mode
        return text

    def fileno(self) -> int:
        return self._sock.fileno()  # type: ignore[attr-defined,no-any-return]

    def close(self) -> None:
        self._closed = True
        if self._io_refs <= 0:
            closer = getattr(self._sock, "close", None)
            if callable(closer):
                closer()

    def _decref_socketios(self) -> None:
        if self._io_refs > 0:
            self._io_refs -= 1
        if self._closed and self._io_refs <= 0:
            closer = getattr(self._sock, "close", None)
            if callable(closer):
                closer()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)


def _declared_content_length(hdrs: dict[str, str]) -> int | None:
    raw = hdrs.get("content-length")
    if raw is None or raw == "":
        return None
    try:
        declared = int(raw)
    except ValueError as exc:
        raise BenchError(
            "media_resource_failed",
            f"remote media Content-Length is not an integer: {raw}",
        ) from exc
    if declared < 0:
        raise BenchError(
            "media_resource_failed",
            f"remote media Content-Length {declared} is negative",
        )
    return declared


def _read_response_body(response: object, *, conn: HTTPSConnection, max_bytes: int, deadline_at: float) -> bytes:
    buf = bytearray()
    read1 = getattr(response, "read1", None)
    while True:
        timeout = _remaining_timeout(deadline_at)
        _apply_sock_timeout(getattr(conn, "sock", None), timeout)
        remaining_cap = max_bytes - len(buf) + 1
        if remaining_cap <= 0:
            raise BenchError(
                "media_resource_failed",
                f"remote media body exceeds max {max_bytes} bytes",
            )
        chunk_size = min(65536, remaining_cap)
        try:
            if callable(read1):
                chunk = read1(chunk_size)
            else:
                chunk = response.read(chunk_size)  # type: ignore[attr-defined]
        except (TimeoutError, socket.timeout) as exc:
            raise BenchError("media_resource_failed", "remote media fetch deadline exceeded") from exc
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise BenchError(
                "media_resource_failed",
                f"remote media body exceeds max {max_bytes} bytes",
            )
    return bytes(buf)


def _https_get_pinned(
    host: str,
    port: int,
    path: str,
    pinned_ip: str,
    *,
    deadline_at: float | None = None,
    max_bytes: int | None = None,
) -> tuple[int, dict[str, str], bytes]:
    deadline_at = _absolute_deadline(deadline_at)
    max_bytes = REMOTE_FETCH_MAX_BYTES if max_bytes is None else max_bytes
    remaining = _remaining_timeout(deadline_at)
    context = ssl.create_default_context()
    conn = HTTPSConnection(host, port=port, timeout=remaining, context=context)

    def _connect() -> None:
        timeout = _remaining_timeout(deadline_at)
        try:
            sock = socket.create_connection((pinned_ip, port), timeout)
        except (TimeoutError, socket.timeout) as exc:
            raise _deadline_exceeded(exc)
        try:
            timeout = _remaining_timeout(deadline_at)
            _apply_sock_timeout(sock, timeout)
            try:
                # [GRPH-32][GRPH-33] Close the raw socket if TLS wrapping fails
                # before HTTPSConnection owns it. SNI stays the original hostname.
                tls_sock = context.wrap_socket(sock, server_hostname=host)
            except (TimeoutError, socket.timeout) as exc:
                raise _deadline_exceeded(exc)
        except BaseException:
            sock.close()
            raise
        try:
            timeout = _remaining_timeout(deadline_at)
            _apply_sock_timeout(tls_sock, timeout)
            conn.sock = _DeadlineSocket(tls_sock, deadline_at)
        except BaseException:
            tls_sock.close()
            raise

    conn.connect = _connect  # type: ignore[method-assign]
    response = None
    try:
        timeout = _remaining_timeout(deadline_at)
        conn.timeout = timeout
        try:
            conn.request("GET", path, headers={"Host": host})
            timeout = _remaining_timeout(deadline_at)
            _apply_sock_timeout(getattr(conn, "sock", None), timeout)
            response = conn.getresponse()
        except (TimeoutError, socket.timeout) as exc:
            raise _deadline_exceeded(exc)
        try:
            hdrs = {k.lower(): v for k, v in response.getheaders()}
            declared = _declared_content_length(hdrs)
            if declared is not None and declared > max_bytes:
                raise BenchError(
                    "media_resource_failed",
                    f"remote media Content-Length {declared} exceeds max {max_bytes} bytes",
                )
            payload = _read_response_body(
                response, conn=conn, max_bytes=max_bytes, deadline_at=deadline_at
            )
            return response.status, hdrs, payload
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
    finally:
        conn.close()


def _validate_record_dimensions(record: dict[str, Any]) -> None:
    if record.get("outcome") != "ok":
        return
    for key in ("image_width", "image_height"):
        value = record.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise BenchError("image_dimensions_missing", f"{key} missing/non-positive on ok record")
