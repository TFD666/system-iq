import sys
from pathlib import Path

import pytest

# Add cli/ to the front of sys.path so that `from systemiq import load_input`
# resolves to cli/systemiq.py regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _clear_systemiq_api_url(monkeypatch):
    """Keep existing tests independent of a real SYSTEMIQ_API_URL in the environment."""
    monkeypatch.delenv("SYSTEMIQ_API_URL", raising=False)
