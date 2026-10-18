"""S2R5-24: named TestClient bound must fire when socketpair never returns."""

from __future__ import annotations

import socket
import threading

import pytest

from scene.tests.test_context_pack import (
    CapturingAdapter,
    DescribeClientDidNotFinish,
    _post_describe_bounded,
    _scene_describe_app,
)


def test_r6e3_bounded_testclient_names_socketpair_block():
    """A blocked asyncio self-pipe must not hang the suite anonymously."""
    real_socketpair = socket.socketpair
    release = threading.Event()

    def _blocked_socketpair(*args, **kwargs):
        if not release.wait(timeout=30):
            raise TimeoutError("test fixture socketpair block was not released")
        return real_socketpair(*args, **kwargs)

    socket.socketpair = _blocked_socketpair
    try:
        with pytest.raises(DescribeClientDidNotFinish, match="socketpair") as caught:
            _post_describe_bounded(_scene_describe_app(CapturingAdapter()), timeout_s=1.0)
        message = str(caught.value)
        assert "_TestClientTransport" in message
        assert "starlette#1108" in message
    finally:
        release.set()
        socket.socketpair = real_socketpair
