"""
Packaging checks for the Docker image: no secrets baked in, .dockerignore
covers the required paths, every third-party import has a pinned entry in
requirements.txt, and the samples path resolves correctly inside the
container's /app/backend/app layout.
"""

import ast
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "backend" / "app"
REQUIREMENTS_PATH = REPO_ROOT / "backend" / "requirements.txt"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"

_STDLIB_MODULES = set(sys.stdlib_module_names)

# Every third-party module backend/app imports, mapped to its pip package
# name explicitly -- a new unmapped import fails test_every_third_party_
# import_is_in_requirements below, forcing this map (and requirements.txt)
# to be updated rather than silently passing.
IMPORT_TO_PACKAGE = {
    "fastapi": "fastapi",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "dotenv": "python-dotenv",
}


def _collect_top_level_imports() -> set[str]:
    found: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
    return found


# ── requirements.txt completeness ────────────────────────────────────────────

def test_every_third_party_import_is_in_requirements():
    imports = _collect_top_level_imports()
    third_party = imports - _STDLIB_MODULES

    unmapped = third_party - set(IMPORT_TO_PACKAGE)
    assert not unmapped, f"import(s) not mapped to a package in IMPORT_TO_PACKAGE: {sorted(unmapped)}"

    requirements_lines = REQUIREMENTS_PATH.read_text().splitlines()
    for module_name in third_party:
        package_name = IMPORT_TO_PACKAGE[module_name]
        found = any(
            line.strip().lower().startswith(package_name.lower() + "==")
            for line in requirements_lines
        )
        assert found, f"{package_name} (imported as {module_name}) missing from backend/requirements.txt"


# ── .dockerignore ─────────────────────────────────────────────────────────────

def test_dockerignore_lists_required_patterns():
    lines = {line.strip() for line in DOCKERIGNORE_PATH.read_text().splitlines()}
    for required in (".env", ".venv", "eval", ".git"):
        assert required in lines, f"{required!r} missing from .dockerignore"


# ── Dockerfile: no secrets baked in ──────────────────────────────────────────

_FORBIDDEN_TOKENS = (".env", "API_KEY", "ACCESS_CODES=", "ADMIN_TOKEN")


def test_dockerfile_has_no_secrets_outside_comments():
    for line in DOCKERFILE_PATH.read_text().splitlines():
        code = line.split("#", 1)[0]
        for token in _FORBIDDEN_TOKENS:
            assert token not in code, f"{token!r} found outside a comment in Dockerfile: {line!r}"


# ── samples path resolution inside the container layout ─────────────────────

def test_repo_root_formula_resolves_under_app_container_layout(tmp_path):
    """
    main.py computes _REPO_ROOT as two directories up from its own file
    (backend/app/main.py -> repo root). In the image, main.py lives at
    /app/backend/app/main.py, so this must resolve to /app. Reproduce that
    shape under tmp_path and confirm the same formula finds samples/index.json.
    """
    fake_app_root = tmp_path / "app"
    fake_main = fake_app_root / "backend" / "app" / "main.py"
    fake_main.parent.mkdir(parents=True)
    fake_main.write_text("# placeholder")

    samples_dir = fake_app_root / "samples"
    samples_dir.mkdir()
    (samples_dir / "index.json").write_text(json.dumps([{"title": "Clinic app", "url": "http://x"}]))

    # The exact formula used in backend/app/main.py.
    computed_root = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(str(fake_main))), "..", ".."),
    )
    assert computed_root == str(fake_app_root)

    resolved_samples_path = os.path.join(computed_root, "samples", "index.json")
    assert os.path.isfile(resolved_samples_path)
    assert json.loads(Path(resolved_samples_path).read_text()) == [{"title": "Clinic app", "url": "http://x"}]
