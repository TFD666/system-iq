"""Tests for systemiq.resolve_api_url priority: flag > env > default."""

from systemiq import DEFAULT_API_URL, resolve_api_url


class TestResolveApiUrl:
    def test_flag_wins_over_everything(self, monkeypatch):
        monkeypatch.setenv("SYSTEMIQ_API_URL", "http://env-host:9000")
        assert resolve_api_url("http://flag-host:1234") == "http://flag-host:1234"

    def test_env_used_when_no_flag(self, monkeypatch):
        monkeypatch.setenv("SYSTEMIQ_API_URL", "http://env-host:9000")
        assert resolve_api_url(None) == "http://env-host:9000"

    def test_default_when_neither(self, monkeypatch):
        monkeypatch.delenv("SYSTEMIQ_API_URL", raising=False)
        assert resolve_api_url(None) == DEFAULT_API_URL

    def test_default_is_the_hosted_render_url(self, monkeypatch):
        """Pin against accidentally reverting DEFAULT_API_URL back to localhost."""
        monkeypatch.delenv("SYSTEMIQ_API_URL", raising=False)
        assert resolve_api_url(None) == "https://systemiq-api-pbwg.onrender.com"

    def test_flag_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.delenv("SYSTEMIQ_API_URL", raising=False)
        assert resolve_api_url("http://flag-host:1234/") == "http://flag-host:1234"

    def test_env_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("SYSTEMIQ_API_URL", "http://env-host:9000/")
        assert resolve_api_url(None) == "http://env-host:9000"

    def test_empty_flag_falls_through_to_env(self, monkeypatch):
        monkeypatch.setenv("SYSTEMIQ_API_URL", "http://env-host:9000")
        assert resolve_api_url("") == "http://env-host:9000"
