"""
Shared pytest fixtures for the backend test suite.

Network guard
-------------
The autouse fixture below patches the *methods* on httpx's real transport
classes so any genuine TCP connection attempt raises RuntimeError.  This
prevents tests from accidentally consuming the Jev or Groq API quota.

Why patch the method, not the class:
- httpx.get() / httpx.post() create an HTTPTransport internally.
  Replacing the class constructor (patch("httpx.HTTPTransport", ...))
  doesn't affect calls that import the class before the patch is applied,
  and it doesn't stop already-created instances.
- monkeypatch.setattr on the *method* mutates the class object itself, so
  every instance – no matter when or how it was created – will raise.

What is NOT affected:
- Tests that patch("app.decision.provider.httpx.post", return_value=...)
  replace the entire function, so the transport is never called.
- FastAPI's TestClient uses httpx.ASGITransport (not HTTPTransport), so
  it routes requests directly to the ASGI app without any TCP socket.
"""

from __future__ import annotations

import httpx
import pytest


# ---------------------------------------------------------------------------
# Network guard – blocks all real httpx TCP connections in every test
# ---------------------------------------------------------------------------


def _raiser(self, request):  # type: ignore[no-untyped-def]
    """Raise RuntimeError for any real network send attempt."""
    raise RuntimeError(
        f"real network call in test: {request.method} {request.url}"
    )


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch handle_request / handle_async_request on the transport classes.

    monkeypatch restores the original methods automatically after each test,
    so there is no risk of leaking the patch between tests.
    """
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _raiser)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _raiser
    )
