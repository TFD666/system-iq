"""
A token budget for the design writer's LLM calls.

Groq caps TWO things per minute: total tokens, and OUTPUT tokens
specifically (the output cap is usually much lower -- that's the one that
actually bit us). TokenBudget tracks both as separate rolling 60-second
windows and waits until BOTH have room before a call.

The clock and sleep function are injectable so tests can run instantly
with a fake clock instead of really waiting.
"""

import os
import time
from collections import deque

# Defaults when DESIGN_TPM / DESIGN_OTPM aren't set in the environment.
DEFAULT_MAX_TOTAL_TOKENS_PER_MINUTE = 6500
DEFAULT_MAX_OUTPUT_TOKENS_PER_MINUTE = 800

_WINDOW_SECONDS = 60

# However far over budget we are, never sleep longer than this in one call.
# (The rolling window is 60s, so waiting a little past that is enough.)
MAX_SLEEP_SECONDS = 65


class _Window:
    """One rolling 60-second token-usage window against one cap."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        # (timestamp, tokens) pairs for tokens spent in the last window.
        self._usage: deque[tuple[float, int]] = deque()

    def _forget_old(self, now: float) -> None:
        # Usage older than the window no longer counts against the cap.
        while self._usage and now - self._usage[0][0] >= _WINDOW_SECONDS:
            self._usage.popleft()

    def _used(self, now: float) -> int:
        self._forget_old(now)
        return sum(tokens for _, tokens in self._usage)

    def record(self, tokens: int, when: float) -> None:
        self._usage.append((when, tokens))

    def seconds_until_room(self, now: float, estimated: int) -> float:
        """0 if `estimated` more tokens fit now; otherwise how long until
        the oldest usage entry falls out of the window."""
        if self._used(now) + estimated <= self.cap:
            return 0.0

        self._forget_old(now)
        if not self._usage:
            # This one call is simply bigger than the whole cap --
            # waiting would never help, so don't.
            return 0.0

        oldest_timestamp = self._usage[0][0]
        return max(0.0, _WINDOW_SECONDS - (now - oldest_timestamp))


class TokenBudget:
    def __init__(
        self,
        max_total_tokens_per_minute=None,
        max_output_tokens_per_minute=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        # Read from the environment lazily (at construction, not import
        # time) so tests can set DESIGN_TPM/DESIGN_OTPM before construction.
        if max_total_tokens_per_minute is None:
            max_total_tokens_per_minute = int(
                os.environ.get("DESIGN_TPM", DEFAULT_MAX_TOTAL_TOKENS_PER_MINUTE)
            )
        if max_output_tokens_per_minute is None:
            max_output_tokens_per_minute = int(
                os.environ.get("DESIGN_OTPM", DEFAULT_MAX_OUTPUT_TOKENS_PER_MINUTE)
            )
        self._clock = clock
        self._sleep = sleep
        self._total_window = _Window(max_total_tokens_per_minute)
        self._output_window = _Window(max_output_tokens_per_minute)

    def record(self, total_tokens: int, output_tokens: int) -> None:
        """Remember the ACTUAL tokens a call just spent (from the
        response), for future budget checks."""
        now = self._clock()
        self._total_window.record(total_tokens, now)
        self._output_window.record(output_tokens, now)

    def wait_if_needed(self, estimated_total_tokens: int, estimated_output_tokens: int) -> None:
        """
        Sleep if the next call would go over EITHER the total or the
        output per-minute cap. Both windows must have room, so we wait
        for whichever one needs longer -- capped at MAX_SLEEP_SECONDS so
        one call can never block for a very long time.
        """
        now = self._clock()
        wait_for_total = self._total_window.seconds_until_room(now, estimated_total_tokens)
        wait_for_output = self._output_window.seconds_until_room(now, estimated_output_tokens)
        wait_seconds = min(max(wait_for_total, wait_for_output), MAX_SLEEP_SECONDS)

        if wait_seconds > 0:
            self._sleep(wait_seconds)
