"""Tests for cli packaging (pyproject.toml, entry point, --version)."""

import subprocess
import sys
from pathlib import Path

import tomli

CLI_DIR = Path(__file__).parent.parent


def _load_pyproject():
    with open(CLI_DIR / "pyproject.toml", "rb") as f:
        return tomli.load(f)


class TestPyprojectToml:
    def test_project_metadata(self):
        data = _load_pyproject()
        project = data["project"]
        assert project["name"] == "systemiq"
        assert project["version"] == "1.0.0"
        assert project["requires-python"] == ">=3.10"

    def test_dependency_is_pinned_httpx(self):
        data = _load_pyproject()
        deps = data["project"]["dependencies"]
        assert deps == ["httpx==0.28.1"]

    def test_py_modules(self):
        data = _load_pyproject()
        assert data["tool"]["setuptools"]["py-modules"] == ["systemiq", "redact", "hosted_client"]

    def test_entry_point(self):
        data = _load_pyproject()
        scripts = data["project"]["scripts"]
        assert scripts["systemiq"] == "systemiq:main"


class TestImports:
    def test_import_systemiq_and_redact(self):
        import hosted_client
        import redact
        import systemiq

        assert callable(systemiq.main)
        assert callable(redact.redact)
        assert callable(hosted_client.detect_mode)


class TestVersionFlag:
    def test_version_output(self):
        result = subprocess.run(
            [sys.executable, str(CLI_DIR / "systemiq.py"), "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "systemiq 1.0.0"


class TestModuleEntry:
    def test_python_dash_m_systemiq_version(self):
        """`python -m systemiq` must work: run from cli/ so systemiq.py (and its
        same-directory imports, hosted_client/redact) are importable as top-level
        modules -- no package or __main__.py needed, just the existing __main__ guard."""
        result = subprocess.run(
            [sys.executable, "-m", "systemiq", "--version"],
            capture_output=True, text=True, cwd=str(CLI_DIR),
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "systemiq 1.0.0"
