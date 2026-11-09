import hashlib
import sys
from pathlib import Path

import pytest

# Add eval/seeded/ to sys.path so `import make_variants` etc. resolve,
# regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

_REAL_FILES = (Path(__file__).parent.parent / "report.md",)


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def _real_eval_seeded_files_stay_untouched():
    """Same guard as eval/m6/tests/conftest.py: hashes real eval/seeded/
    output files before the session and asserts they are unchanged after.
    A file missing before is skipped."""
    before = {path: _hash(path) for path in _REAL_FILES}
    yield
    for path, before_hash in before.items():
        if before_hash is None:
            continue
        assert _hash(path) == before_hash, f"test run modified a real file: {path}"
