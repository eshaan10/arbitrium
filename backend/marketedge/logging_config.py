"""Logging setup, including secret redaction.

The Odds API accepts its credential ONLY as an ``apiKey`` query parameter, so the
key is necessarily part of every request URL. httpx logs each request line at
INFO — meaning a default logging setup writes the API key into container logs on
every single poll, indefinitely.

Anything that formats a URL is therefore a disclosure risk, not just the happy
path: ``raise_for_status()`` puts the full URL in its exception message, which
then lands in tracebacks and error logs.
"""

from __future__ import annotations

import logging
import re

from marketedge.config import settings

# Matches the credential in a query string, capturing the parameter name so the
# shape of the URL is preserved in logs while the value is destroyed.
_SECRET_QUERY_PARAMS = re.compile(
    r"\b(apiKey|api_key|apikey|token|access_token)=([^&\s\"']+)",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Replace credential query-parameter values with ``***REDACTED***``."""
    return _SECRET_QUERY_PARAMS.sub(r"\1=***REDACTED***", text)


class RedactingFilter(logging.Filter):
    """Strips credentials from log records regardless of which library emitted them.

    Applied to the root handler rather than to one logger: the key can surface via
    httpx's request line, a traceback, or our own f-string, and a filter on the
    handler catches all three.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_arg(v) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact_arg(a) for a in record.args)
        return True


def _redact_arg(value: object) -> object:
    return redact(value) if isinstance(value, str) else value


def configure_logging() -> None:
    """Configure root logging and prevent credential leakage.

    Two independent defences, because either alone is insufficient:
      * httpx's request logger is raised to WARNING, so the routine request line
        carrying ``apiKey=`` is never emitted at all;
      * a redacting filter on every root handler catches whatever still slips
        through — tracebacks, HTTPStatusError messages, third-party loggers.
    """
    logging.basicConfig(level=settings.log_level)

    # Routine "HTTP Request: GET https://...?apiKey=..." lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    redactor = RedactingFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)
