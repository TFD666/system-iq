"""
Tests for app/design/limiter.py. Uses a fake clock and a fake sleep
function so nothing actually waits in real time.

TokenBudget now tracks TWO windows (total tokens, output tokens), so
record()/wait_if_needed() both take two arguments instead of one -- the
tests below were rewritten for that, not just for new timing.
"""

from app.design.limiter import MAX_SLEEP_SECONDS, TokenBudget

# A cap so high it's never the bottleneck -- used on the window a given
# test isn't trying to exercise.
_HUGE_CAP = 1_000_000


class FakeClock:
    """A clock you control by hand, instead of real wall-clock time."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_budget(clock: FakeClock, total_cap: int = _HUGE_CAP, output_cap: int = _HUGE_CAP):
    sleep_calls: list[float] = []
    budget = TokenBudget(
        max_total_tokens_per_minute=total_cap,
        max_output_tokens_per_minute=output_cap,
        clock=clock,
        sleep=sleep_calls.append,
    )
    return budget, sleep_calls


def test_wait_if_needed_does_not_sleep_when_window_is_empty():
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1000)

    budget.wait_if_needed(500, 500)

    assert sleep_calls == []


def test_wait_if_needed_does_not_sleep_when_there_is_still_room():
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1000)

    budget.record(400, 400)
    budget.wait_if_needed(500, 500)  # 400 + 500 = 900, still under 1000

    assert sleep_calls == []


def test_wait_if_needed_sleeps_when_total_window_is_full():
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1000)

    budget.record(900, 0)
    budget.wait_if_needed(200, 0)  # 900 + 200 > 1000 -- must wait

    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0


def test_wait_if_needed_sleeps_when_output_window_is_full_even_if_total_has_room():
    # This is exactly the bug: the total window had room, but the much
    # smaller output window did not, and the writer called too fast anyway.
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1_000_000, output_cap=800)

    budget.record(100, 800)  # output window is now full; total window is not
    budget.wait_if_needed(100, 100)

    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0


def test_wait_if_needed_never_sleeps_more_than_the_cap():
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=100, output_cap=100)

    budget.record(100, 100)
    budget.wait_if_needed(100, 100)

    assert sleep_calls[0] <= MAX_SLEEP_SECONDS


def test_old_usage_falls_out_of_the_window():
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1000)

    budget.record(900, 0)
    clock.advance(61)  # past the 60s window -- that usage no longer counts
    budget.wait_if_needed(200, 0)

    assert sleep_calls == []


def test_record_without_wait_is_fine():
    # record() by itself must never raise or need a clock/sleep call.
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1000)
    budget.record(50, 20)
    budget.record(50, 20)
    assert sleep_calls == []


def test_record_stores_the_actual_counts_passed_in():
    # record() takes the ACTUAL token counts from the response, which can
    # differ from whatever was estimated before the call.
    clock = FakeClock()
    budget, sleep_calls = _make_budget(clock, total_cap=1000, output_cap=1000)

    budget.record(900, 900)  # actual usage, not an estimate
    budget.wait_if_needed(200, 0)  # 900 + 200 > 1000 -- the real usage counts

    assert len(sleep_calls) == 1


def test_default_caps_read_design_tpm_and_otpm_env(monkeypatch):
    monkeypatch.setenv("DESIGN_TPM", "1000000")  # keep the total window out of the way
    monkeypatch.setenv("DESIGN_OTPM", "42")
    clock = FakeClock()
    waited: list[float] = []
    # No caps given -- must fall back to reading DESIGN_TPM / DESIGN_OTPM.
    budget = TokenBudget(clock=clock, sleep=waited.append)

    budget.record(0, 40)
    budget.wait_if_needed(0, 10)  # 40 + 10 = 50 > 42, so this must wait

    assert waited
