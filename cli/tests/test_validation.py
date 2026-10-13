import pytest
from systemiq import load_input, MAX_BYTES


# ── valid cases ────────────────────────────────────────────────────────────────

def test_valid_md_file_returns_text(tmp_path):
    f = tmp_path / "idea.md"
    f.write_text("My great idea", encoding="utf-8")
    assert load_input(str(f)) == "My great idea"


def test_valid_txt_file_returns_text(tmp_path):
    f = tmp_path / "idea.txt"
    f.write_text("Another idea", encoding="utf-8")
    assert load_input(str(f)) == "Another idea"


def test_valid_inline_idea_returns_string():
    result = load_input("Just a plain inline idea")
    assert result == "Just a plain inline idea"


def test_uppercase_extension_md_works(tmp_path):
    # Extension matching must be case-insensitive (.MD == .md)
    f = tmp_path / "idea.MD"
    f.write_text("Uppercase extension idea", encoding="utf-8")
    assert load_input(str(f)) == "Uppercase extension idea"


# ── file-path error cases ──────────────────────────────────────────────────────

def test_missing_md_path_raises_value_error(tmp_path):
    # A path that ends in .md but does not exist is a mistyped file, not inline
    missing = tmp_path / "ghost.md"
    with pytest.raises(ValueError, match="not found"):
        load_input(str(missing))


def test_directory_path_raises_value_error(tmp_path):
    # tmp_path itself is a directory; that is never valid input
    with pytest.raises(ValueError, match="directory"):
        load_input(str(tmp_path))


def test_wrong_extension_pdf_raises_value_error(tmp_path):
    # .pdf files exist on disk but are not an allowed plain-text format
    f = tmp_path / "report.pdf"
    f.write_bytes(b"pdf content")
    with pytest.raises(ValueError, match="not allowed"):
        load_input(str(f))


def test_wrong_extension_py_raises_value_error(tmp_path):
    # .py files exist on disk but are not an allowed plain-text format
    f = tmp_path / "script.py"
    f.write_text("print('hello')", encoding="utf-8")
    with pytest.raises(ValueError, match="not allowed"):
        load_input(str(f))


def test_empty_file_raises_value_error(tmp_path):
    # A file with zero bytes has nothing to process
    f = tmp_path / "empty.md"
    f.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_input(str(f))


def test_whitespace_only_file_raises_value_error(tmp_path):
    # A file containing only spaces/newlines is functionally empty
    f = tmp_path / "blank.md"
    f.write_text("   \n\n\t  ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_input(str(f))


def test_file_over_20kb_raises_value_error(tmp_path):
    # Files larger than MAX_BYTES must be rejected before reading
    f = tmp_path / "big.md"
    f.write_bytes(b"x" * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="20 KB"):
        load_input(str(f))


def test_binary_file_raises_value_error(tmp_path):
    # b"\xff\xfe\x00" starts with an invalid UTF-8 byte (\xff),
    # so decoding raises UnicodeDecodeError before the null-byte check
    f = tmp_path / "binary.md"
    f.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="UTF-8"):
        load_input(str(f))


# ── inline error cases ─────────────────────────────────────────────────────────

def test_empty_string_raises_value_error():
    # An empty string is rejected at the first blank-check
    with pytest.raises(ValueError, match="empty"):
        load_input("")


def test_inline_over_20kb_raises_value_error():
    # Inline input is bounded by the same MAX_BYTES ceiling as files
    big = "a" * (MAX_BYTES + 1)
    with pytest.raises(ValueError, match="20 KB"):
        load_input(big)
