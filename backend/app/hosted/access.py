"""Hosted access control: code validation, IP rate limiting, daily caps."""

import hashlib
import hmac
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from ..config import access_codes, daily_design_cap, ip_daily_limit, trusted_proxy_hops

logger = logging.getLogger(__name__)


class BadCode(Exception):
    pass


class IPLimitReached(Exception):
    pass


class CodeLimitReached(Exception):
    pass


class CapacityReached(Exception):
    def __init__(self, reason: str = "capacity"):
        self.reason = reason
        super().__init__(reason)


class AccessManager:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        salt_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    ):
        self._clock = clock
        self._salt_factory = salt_factory
        self._lock = threading.Lock()
        self._day: str | None = None
        self._salt: str = ""
        self._global_count = 0
        self._ip_counts: dict[str, int] = {}
        self._code_counts: dict[str, int] = {}
        self._exhausted: set[str] = set()
        self._reservations: dict[str, dict] = {}
        self._cap_80_warned = False
        self._cap_hit_warned = False

    def _maybe_reset(self) -> None:
        today = datetime.fromtimestamp(
            self._clock(), tz=timezone.utc,
        ).strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self._salt = self._salt_factory()
            self._global_count = 0
            self._ip_counts.clear()
            self._code_counts.clear()
            self._exhausted.clear()
            self._reservations.clear()
            self._cap_80_warned = False
            self._cap_hit_warned = False

    def check_code(self, raw_code: str) -> str | None:
        """Constant-time comparison against every configured code."""
        codes = access_codes()
        if not codes:
            return None
        found: str | None = None
        for label, code, _limit in codes:
            if hmac.compare_digest(raw_code, code):
                found = label
        return found

    def client_ip(self, request) -> str:
        """Hash the client IP with the daily salt."""
        hops = trusted_proxy_hops()
        if hops <= 0:
            raw_ip = request.client.host
        else:
            xff = request.headers.get("x-forwarded-for", "")
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if len(parts) >= hops:
                raw_ip = parts[-hops]
            else:
                raw_ip = request.client.host
        with self._lock:
            self._maybe_reset()
            return hashlib.sha256(
                (self._salt + raw_ip).encode(),
            ).hexdigest()

    def reserve(self, code_label: str | None, ip_hash: str) -> str:
        """Check limits, increment counters, return reservation token."""
        with self._lock:
            self._maybe_reset()

            if code_label is None:
                raise BadCode()

            ip_limit = ip_daily_limit()
            if self._ip_counts.get(ip_hash, 0) >= ip_limit:
                raise IPLimitReached()

            code_limit = self._code_limit(code_label)
            if self._code_counts.get(code_label, 0) >= code_limit:
                raise CodeLimitReached()

            cap = daily_design_cap()
            if self._global_count >= cap:
                raise CapacityReached("capacity")
            if "groq" in self._exhausted:
                raise CapacityReached("quota")

            self._ip_counts[ip_hash] = self._ip_counts.get(ip_hash, 0) + 1
            self._code_counts[code_label] = (
                self._code_counts.get(code_label, 0) + 1
            )
            self._global_count += 1

            if not self._cap_80_warned and self._global_count >= cap * 0.8:
                logger.warning("CAP_80 %d/%d", self._global_count, cap)
                self._cap_80_warned = True
            if not self._cap_hit_warned and self._global_count >= cap:
                logger.warning("CAP_HIT %d/%d", self._global_count, cap)
                self._cap_hit_warned = True

            token = uuid.uuid4().hex
            self._reservations[token] = {
                "code_label": code_label,
                "ip_hash": ip_hash,
            }
            return token

    def release(self, token: str, app_failure: bool) -> None:
        """Refund per-IP and per-code counts on app failures."""
        with self._lock:
            res = self._reservations.pop(token, None)
            if res is None:
                return
            if app_failure:
                ip = res["ip_hash"]
                lbl = res["code_label"]
                if ip in self._ip_counts:
                    self._ip_counts[ip] = max(0, self._ip_counts[ip] - 1)
                if lbl in self._code_counts:
                    self._code_counts[lbl] = max(0, self._code_counts[lbl] - 1)

    def set_exhausted(self, flag: str) -> None:
        with self._lock:
            self._exhausted.add(flag)

    def is_exhausted(self, flag: str) -> bool:
        with self._lock:
            return flag in self._exhausted

    def snapshot(self) -> dict:
        with self._lock:
            self._maybe_reset()
            return {
                "day": self._day,
                "global_count": self._global_count,
                "global_cap": daily_design_cap(),
                "code_counts": dict(self._code_counts),
                "exhausted": sorted(self._exhausted),
            }

    def _code_limit(self, label: str) -> int:
        for l, _, limit in access_codes():
            if l == label:
                return limit
        return 0
