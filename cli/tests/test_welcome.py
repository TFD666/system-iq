"""
Tests for the first-run welcome message, the no-argument quick-start screen,
and the --help argument-group layout.
"""

from unittest.mock import patch

import pytest

from systemiq import WELCOME, NO_ARGS_MESSAGE, config_dir, main


# ── WELCOME content itself ───────────────────────────────────────────────────

class TestWelcomeArt:
    def test_is_pure_ascii(self):
        WELCOME.encode("ascii")  # raises UnicodeEncodeError if not

    def test_at_most_7_lines(self):
        assert len(WELCOME.splitlines()) <= 7

    def test_no_line_over_60_columns(self):
        for line in WELCOME.splitlines():
            assert len(line) <= 60

    def test_no_url_or_secret(self):
        lowered = WELCOME.lower()
        for token in ("http://", "https://", "key", "token", "code", "secret"):
            assert token not in lowered


# ── --welcome flag ───────────────────────────────────────────────────────────

class TestWelcomeFlag:
    def test_always_prints_and_exits_0_regardless_of_marker(self, capsys):
        marker = config_dir() / "welcome_shown"
        marker.parent.mkdir(parents=True)
        marker.write_text("shown")

        with patch("sys.argv", ["systemiq", "--welcome"]):
            main()  # no SystemExit -> implicit 0

        assert WELCOME in capsys.readouterr().out


# ── first-run auto welcome ───────────────────────────────────────────────────

class TestAutoWelcome:
    def test_first_run_on_a_terminal_shows_welcome_once_and_creates_marker(self, capsys):
        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--sample", "99"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()

        err = capsys.readouterr().err
        assert WELCOME in err
        assert (config_dir() / "welcome_shown").exists()

    def test_second_run_shows_nothing(self, capsys):
        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--sample", "99"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()
        capsys.readouterr()  # discard first run's output

        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--sample", "99"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().err

    def test_not_a_terminal_shows_nothing_and_no_marker(self, capsys):
        with patch("sys.stderr.isatty", return_value=False), \
             patch("sys.argv", ["systemiq", "--sample", "99"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().err
        assert not (config_dir() / "welcome_shown").exists()

    def test_json_flag_shows_nothing(self, capsys):
        from unittest.mock import MagicMock

        fake_post_resp = MagicMock()
        fake_post_resp.status_code = 200
        fake_post_resp.json.return_value = {"stage": "extracted"}

        with patch("sys.stderr.isatty", return_value=True), \
             patch("systemiq.httpx.post", return_value=fake_post_resp), \
             patch("sys.argv", ["systemiq", "idea", "--json"]):
            main()

        assert WELCOME not in capsys.readouterr().err

    def test_quiet_flag_shows_nothing(self, capsys):
        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--sample", "99", "--quiet"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().err

    def test_version_shows_nothing(self, capsys):
        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--version"]):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().err

    def test_help_shows_nothing(self, capsys):
        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--help"]):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().err

    def test_no_welcome_env_var_shows_nothing(self, monkeypatch, capsys):
        monkeypatch.setenv("SYSTEMIQ_NO_WELCOME", "1")
        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--sample", "99"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().err
        assert not (config_dir() / "welcome_shown").exists()

    def test_unwritable_config_path_shows_nothing_and_does_not_crash(self, monkeypatch, capsys, tmp_path):
        # Use a regular file where the config folder would be, so mkdir fails.
        not_a_dir = tmp_path / "not_a_dir"
        not_a_dir.write_text("I am a file, not a directory")
        monkeypatch.setenv("SYSTEMIQ_CONFIG_DIR", str(not_a_dir / "systemiq"))

        with patch("sys.stderr.isatty", return_value=True), \
             patch("sys.argv", ["systemiq", "--sample", "99"]), \
             patch("hosted_client.httpx.get", side_effect=AssertionError("no network")):
            with pytest.raises(SystemExit):
                main()  # must not raise anything other than the expected SystemExit

        assert WELCOME not in capsys.readouterr().err


# ── no-argument quick-start screen ───────────────────────────────────────────

class TestNoArgumentScreen:
    def test_prints_quick_start_and_exits_2(self, capsys):
        with patch("sys.argv", ["systemiq"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        out = capsys.readouterr().out
        assert out.strip() == NO_ARGS_MESSAGE.strip()
        assert "--access-code" in out
        assert "--sample 1" in out
        assert "--help" in out

    def test_no_welcome_art_in_the_screen_itself(self, capsys):
        """The first-run welcome (if any) goes to stderr; the screen text on
        stdout never contains the art."""
        with patch("sys.stderr.isatty", return_value=False), \
             patch("sys.argv", ["systemiq"]):
            with pytest.raises(SystemExit):
                main()

        assert WELCOME not in capsys.readouterr().out


# ── --help layout ─────────────────────────────────────────────────────────────

class TestHelpLayout:
    def test_help_has_both_group_titles(self, capsys):
        with patch("sys.argv", ["systemiq", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Common options" in out
        assert "Advanced and development options" in out
        assert out.index("Common options") < out.index("Advanced and development options")

    def test_help_mentions_new_env_vars_and_exit_codes(self, capsys):
        with patch("sys.argv", ["systemiq", "--help"]):
            with pytest.raises(SystemExit):
                main()

        out = capsys.readouterr().out
        assert "SYSTEMIQ_CONFIG_DIR" in out
        assert "SYSTEMIQ_NO_WELCOME" in out
        assert "2 no arguments given" in out
