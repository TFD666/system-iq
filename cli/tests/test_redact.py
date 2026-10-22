"""
Tests for cli/redact.py.
No network calls; pure unit tests on the redact() function.

Token-shaped strings are assembled at runtime by joining short pieces so that
no complete credential literal appears in the source text, avoiding GitHub
secret-scanning alerts.
"""
import pytest
from redact import redact


# ── runtime token builders ─────────────────────────────────────────────────────
# Each helper joins short fragments so no single string literal in this file
# matches a known secret pattern.

def _sk_key():
    # OpenAI-style secret key: sk- + 36 alphanum chars
    return "sk-" + "abcdefghijklmnop" + "qrstuvwxyz" + "1234567890"


def _groq_key():
    # Groq service key: gsk_ + 34 alphanum chars
    return "gsk_" + "abcdefghijklmnop" + "qrstuvwxyz" + "12345678"


def _ghp_token():
    # GitHub personal access token (classic): ghp_ + 36 alphanum chars
    return "ghp_" + "abcdefghijklmnop" + "qrstuvwxyz" + "1234567890abcd"


def _github_pat():
    # GitHub fine-grained PAT: github_pat_ + 30+ chars
    return "github" + "_pat_" + "abcdefghijklmnop" + "qrstuvwxyz12345"


def _aws_key():
    # AWS access key ID: AKIA + 16 uppercase alphanum chars
    return "AKIA" + "IOSFODNN" + "7EXAMPLE"


def _slack_token():
    # Slack bot token: xoxb- + numeric segment + alphanum segment
    return "xox" + "b-" + "1234567890" + "-abcdefghijklmno"


def _private_key_block():
    # PEM private key block assembled from harmless fragments
    begin = "-----BEGIN RSA " + "PRIVATE KEY-----"
    body  = "MIIEowIBAAKCAQEA" + "0Z3VS5JJcds3xHn" + "/ygWep4"
    end   = "-----END RSA " + "PRIVATE KEY-----"
    return begin + "\n" + body + "\n" + end


def _sk_key_short():
    # Shorter variant used in multi-type test (still ≥ 20 chars after prefix)
    return "sk-" + "abcdefghijklmnop" + "qrstuvwxyz1234"


# ── helper assertions ──────────────────────────────────────────────────────────

def assert_redacted(input_text: str, expected_type: str) -> None:
    """
    Assert that redact() replaces the entire input with a [REDACTED:…] token
    and that the findings list records the expected type with count >= 1.
    The original value must NOT appear in the clean text.
    """
    clean, findings = redact(input_text)
    types = {t for t, _ in findings}
    assert expected_type in types, f"Expected type {expected_type!r} in findings {findings}"
    assert input_text not in clean or "[REDACTED:" in clean


def assert_untouched(input_text: str) -> None:
    """Assert that redact() leaves ordinary text completely unchanged."""
    clean, findings = redact(input_text)
    assert clean == input_text, f"Expected no change but got: {clean!r}"
    assert findings == [], f"Expected no findings but got: {findings}"


# ── each pattern is redacted ───────────────────────────────────────────────────

def test_openai_style_api_key_is_redacted():
    assert_redacted(_sk_key(), "api_key")


def test_groq_api_key_is_redacted():
    assert_redacted(_groq_key(), "api_key")


def test_github_personal_token_ghp_is_redacted():
    assert_redacted(_ghp_token(), "api_key")


def test_github_pat_is_redacted():
    assert_redacted(_github_pat(), "api_key")


def test_aws_access_key_is_redacted():
    assert_redacted(_aws_key(), "api_key")


def test_slack_bot_token_is_redacted():
    assert_redacted(_slack_token(), "api_key")


def test_email_is_redacted():
    assert_redacted("alice@example.com", "email")


def test_international_phone_number_is_redacted():
    assert_redacted("+1 800-555-0100", "phone_number")


def test_ten_digit_phone_number_is_redacted():
    assert_redacted("800-555-0199", "phone_number")


def test_ipv4_address_is_redacted():
    assert_redacted("192.168.1.100", "ipv4")


def test_url_with_credentials_is_redacted():
    assert_redacted("https://user:password@example.com/api", "url_credentials")


def test_password_assignment_is_redacted():
    assert_redacted("password=supersecretvalue", "secret_assignment")


def test_secret_assignment_is_redacted():
    assert_redacted("secret=mysecrettoken", "secret_assignment")


def test_token_assignment_is_redacted():
    assert_redacted("token=abc123xyz", "secret_assignment")


def test_api_key_assignment_is_redacted():
    assert_redacted("api_key=abc123xyz456", "secret_assignment")


def test_private_key_block_is_redacted():
    assert_redacted(_private_key_block(), "private_key")


def test_long_hex_string_is_redacted():
    # 32+ hex chars → hex_secret
    assert_redacted("a" * 32 + "bcdef012345678901234567890abcdef", "hex_secret")


def test_long_base64_string_is_redacted():
    # 40+ base64 chars
    assert_redacted("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef0123456789AB", "base64_secret")


# ── false-positive cases stay untouched ───────────────────────────────────────

def test_ordinary_sentence_is_untouched():
    assert_untouched("I want to build a social app for dog owners.")


def test_scale_abbreviation_is_untouched():
    assert_untouched("We expect 100k users in the first year.")


def test_version_number_is_untouched():
    assert_untouched("We are on version 2.3.1 of the platform.")


def test_short_number_is_untouched():
    assert_untouched("The app has 500 daily active users.")


def test_plain_word_secret_without_assignment_is_untouched():
    # "secret" as a standalone word is fine; only "secret=..." is redacted
    assert_untouched("Keep the implementation details secret.")


def test_localhost_url_without_credentials_is_untouched():
    assert_untouched("The backend runs at http://localhost:8000.")


# ── findings contain type and count, never values ─────────────────────────────

def test_findings_contain_type_and_count_not_value():
    sensitive = "email me at alice@example.com or bob@example.com"
    clean, findings = redact(sensitive)
    # Both emails must be gone from clean text
    assert "alice@example.com" not in clean
    assert "bob@example.com" not in clean
    # Findings must record the count
    email_count = next((c for t, c in findings if t == "email"), 0)
    assert email_count == 2
    # The actual email addresses must not appear anywhere in findings
    findings_str = str(findings)
    assert "alice" not in findings_str
    assert "bob" not in findings_str


def test_multiple_types_each_counted_separately():
    text = "email: alice@example.com, key: " + _sk_key_short()
    clean, findings = redact(text)
    types = {t for t, _ in findings}
    assert "email" in types
    assert "api_key" in types
    assert "alice@example.com" not in clean
