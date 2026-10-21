"""Bounded public-network image retrieval for tenant-supplied URLs."""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpx


class SafeFetchError(Exception):
    """The image destination or response failed the fetch policy."""


def _require_global(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        raise SafeFetchError("Image destination is not public")


async def fetch_public_image(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout: float,
    max_bytes: int = 25 * 1024 * 1024,
    resolver=None,
) -> bytes:
    """Validate every destination address and stream within a size/deadline budget.

    DNS is checked before httpx connects; connection-time DNS rebinding remains
    a residual risk and requires a separate transport or network egress policy.
    """
    try:
        async with asyncio.timeout(timeout):
            target = httpx.URL(url)
            if target.scheme not in ("http", "https") or not target.host:
                raise SafeFetchError("Image URL requires an HTTP(S) host")
            try:
                ipaddress.ip_address(target.host)
            except ValueError:
                resolve = resolver or asyncio.get_running_loop().getaddrinfo
                addresses = await resolve(
                    target.host, target.port or (443 if target.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
                if not addresses:
                    raise SafeFetchError("Image destination has no addresses")
                for address in addresses:
                    _require_global(address[4][0])
            else:
                _require_global(target.host)
            async with client.stream(
                "GET", target, timeout=timeout, follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise SafeFetchError("Image redirects are forbidden")
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    if len(body) + len(chunk) > max_bytes:
                        raise SafeFetchError("Image exceeds byte limit")
                    body.extend(chunk)
                return bytes(body)
    except SafeFetchError:
        raise
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError, TimeoutError) as exc:
        raise SafeFetchError("Image fetch failed") from exc
