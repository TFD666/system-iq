import hashlib
import sys
from pathlib import Path

import pytest

# Add eval/m6/ to sys.path so `import run_eval` etc. resolve, regardless
# of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

_M6_DIR = Path(__file__).parent.parent
_REAL_FILES = (
    _M6_DIR / "blind_key.json",
    _M6_DIR / "blind" / "ratings.csv",
    _M6_DIR / "report.md",
)


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def _real_eval_m6_files_stay_untouched():
    """
    Guards the real eval/m6/ output files against a test that forgets to
    redirect a path constant and writes into them for real (as happened
    once with blind_key.json). Hashes each file before the session and
    asserts it is byte-identical after; a file missing before is skipped.
    """
    before = {path: _hash(path) for path in _REAL_FILES}
    yield
    for path, before_hash in before.items():
        if before_hash is None:
            continue
        assert _hash(path) == before_hash, f"test run modified a real file: {path}"
