"""Shared fixtures for netatmo_bubendorff tests."""
from __future__ import annotations

import importlib
import socket
import sys
from unittest.mock import MagicMock

import pytest

# `homeassistant.components.cloud` (imported by the integration at module
# level) pulls in the assist pipeline, which needs two native audio packages
# that publish no Windows wheels. They are irrelevant to this integration, so
# stub them out only when they are genuinely not importable (Linux CI has them).
for _native in ("pymicro_vad", "pyspeex_noise"):
    try:
        importlib.import_module(_native)
    except ImportError:
        sys.modules[_native] = MagicMock()


if sys.platform == "win32":
    # Windows asyncio builds its event loop on a loopback socketpair, but
    # pytest-homeassistant-custom-component blocks every non-unix socket (and
    # Windows has no AF_UNIX socketpair), so the loop itself cannot start.
    # Rebuild the pair from the real socket class captured before the guard
    # is installed. Test-only; no test talks to the network (API is mocked).
    _RealSocket = socket.socket

    def _socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        lsock = _RealSocket(family, type, proto)
        try:
            lsock.bind(("127.0.0.1", 0))
            lsock.listen()
            csock = _RealSocket(family, type, proto)
            try:
                csock.setblocking(False)
                try:
                    csock.connect(lsock.getsockname())
                except (BlockingIOError, InterruptedError):
                    pass
                csock.setblocking(True)
                fd, _ = lsock._accept()
                ssock = _RealSocket(family, type, proto, fileno=fd)
                ssock.setblocking(True)
            except BaseException:
                csock.close()
                raise
        finally:
            lsock.close()
        return ssock, csock

    socket.socketpair = _socketpair


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load custom_components in every test."""
    yield
