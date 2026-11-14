import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add cli/ to the front of sys.path so that `from systemiq import load_input`
# resolves to cli/systemiq.py regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _clear_systemiq_env(monkeypatch):
    """Keep existing tests independent of real SYSTEMIQ_* values in the environment."""
    monkeypatch.delenv("SYSTEMIQ_API_URL", raising=False)
    monkeypatch.delenv("SYSTEMIQ_ACCESS_CODE", raising=False)


@pytest.fixture(autouse=True)
def _default_healthz(monkeypatch):
    """
    main() now checks server mode via GET /healthz before sending (see
    hosted_client.detect_mode), even for the plain local flow. Default every
    test to a reachable, non-hosted response so the existing local-flow
    tests -- which only mock systemiq.httpx.post -- keep working unchanged.
    Tests for the hosted flow override this via monkeypatch as needed.
    """
    import hosted_client

    def _fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": "ok", "hosted": False, "max_idea_chars": 20000}
        return resp

    monkeypatch.setattr(hosted_client.httpx, "get", _fake_get)
