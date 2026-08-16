"""Credential must never reach a log line.

The Odds API accepts its key only as a query parameter, so every request URL
contains it and httpx logs that URL at INFO by default — writing the key into
container logs on every poll, forever. These tests pin both defences.
"""

from __future__ import annotations

import logging

from arbitrium.logging_config import RedactingFilter, configure_logging, redact

FAKE_KEY = "abcdef0123456789abcdef0123456789"
URL = f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey={FAKE_KEY}&regions=us"


def test_redact_removes_the_key_but_keeps_url_shape():
    out = redact(URL)
    assert FAKE_KEY not in out
    assert "apiKey=***REDACTED***" in out
    assert "americanfootball_nfl" in out  # still diagnosable
    assert "regions=us" in out  # non-secret params survive


def test_redact_handles_common_credential_param_names():
    for param in ("apiKey", "api_key", "apikey", "token", "access_token"):
        assert FAKE_KEY not in redact(f"https://x.test/?{param}={FAKE_KEY}")


def test_redact_leaves_clean_text_alone():
    assert redact("Kalshi ingest complete: 33 events") == "Kalshi ingest complete: 33 events"


def test_filter_scrubs_the_message(caplog):
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1, "HTTP Request: GET %s", (URL,), None
    )
    RedactingFilter().filter(record)
    assert FAKE_KEY not in record.getMessage()
    assert "***REDACTED***" in record.getMessage()


def test_filter_scrubs_a_bare_message_with_no_args():
    record = logging.LogRecord(
        "root", logging.ERROR, __file__, 1, f"failed calling {URL}", None, None
    )
    RedactingFilter().filter(record)
    assert FAKE_KEY not in record.getMessage()


def test_httpx_request_logging_is_silenced():
    configure_logging()
    # The specific logger that emits "HTTP Request: GET <url>" at INFO.
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_root_handlers_carry_the_filter():
    configure_logging()
    handlers = logging.getLogger().handlers
    assert handlers, "expected at least one root handler"
    assert all(
        any(isinstance(f, RedactingFilter) for f in h.filters) for h in handlers
    ), "every root handler must redact"
