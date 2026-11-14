"""Logging configuration with secret-filtering."""

import logging
import os


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for val in _secret_values():
            if len(val) >= 8 and val in msg:
                return False
        return True


def _secret_values() -> list[str]:
    from .config import access_codes

    values: list[str] = []
    for _, code, _ in access_codes():
        values.append(code)
    for key in ("ADMIN_TOKEN", "GROQ_API_KEY", "OPENCODE_API_KEY"):
        val = os.environ.get(key, "")
        if val:
            values.append(val)
    return values


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root = logging.getLogger()
    if not any(isinstance(f, _SecretFilter) for f in root.filters):
        root.addFilter(_SecretFilter())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
