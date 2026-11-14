import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add cli/ to the front of sys.path so that `from systemiq import load_input`
# resolves to cli/systemiq.py regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Repo root (two levels up from cli/tests/), where the CLI's default output
# files land when main() is run as documented (`python cli/systemiq.py ...`
# from the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_STRAY_OUTPUT_PATTERNS = ("system-design.md", "*.SAMPLE.md")


@pytest.fixture(autouse=True)
def _chdir_tmp(tmp_path, monkeypatch):
    """
    main() writes its default output file ("system-design.md") relative to
    the current directory. Without this, a test run from a directory that
    happens to already have that file (or one left behind by a previous
    failed run) fails, and a test that doesn't pass --out can write into the
    real repo. Every CLI test now runs with an empty tmp_path as its cwd;
    tests that need an existing output file create it inside tmp_path
    themselves (see test_output_path_guard.py and others).
    """
    monkeypatch.chdir(tmp_path)


def _find_stray_outputs() -> set[Path]:
    found: set[Path] = set()
    for pattern in _STRAY_OUTPUT_PATTERNS:
        found.update(_REPO_ROOT.glob(pattern))
    return found


@pytest.fixture(scope="session", autouse=True)
def _guard_no_stray_output_files():
    """
    Fails the session at teardown if any CLI test left a design output file
    in the repo root. Records what was already there (so a pre-existing
    stray file isn't blamed on the tests) and diffs against it afterward.
    """
    before = _find_stray_outputs()
    yield
    after = _find_stray_outputs()
    created = after - before
    assert not created, (
        f"tests created stray output file(s) in the repo root: "
        f"{sorted(str(p) for p in created)}"
    )


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
