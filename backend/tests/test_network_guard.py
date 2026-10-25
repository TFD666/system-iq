# backend/tests/test_network_guard.py
import httpx
import pytest

def test_guard_blocks_real_calls():
    # ".invalid" can never resolve, so no real traffic is possible either way
    with pytest.raises(RuntimeError, match="real network call"):
        httpx.get("http://example.invalid/")