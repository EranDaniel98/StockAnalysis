"""Tier-2 audit #25: EDGAR client must fail loud on placeholder
User-Agent and survive transient 5xx / 429 with bounded retries.

Pre-fix:
  * ``get_user_agent`` quietly returned the placeholder
    ``contact@stocknew.local`` when the env var was unset. SEC bans
    anonymous / fake-identifier traffic and IP-bans repeat offenders —
    a host that ran the ingestion once with the placeholder could find
    itself locked out of EDGAR for hours, silently.
  * Every endpoint did a single GET with no retry path. A transient
    502/503 from the SEC WAF crashed the entire ingestion run.
  * 429 responses were ignored — no ``Retry-After`` honored.

After:
  * ``get_user_agent`` raises if env var is unset OR contains placeholder.
  * ``_get_with_retries`` honors Retry-After on 429 and applies
    exponential backoff on 5xx, bounded to ``DEFAULT_MAX_RETRIES``.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.market_data.edgar.client import (
    DEFAULT_USER_AGENT,
    _get_with_retries,
    _RateLimiter,
    get_user_agent,
)


# --- fail-loud User-Agent --------------------------------------------------


def test_get_user_agent_raises_when_env_unset(monkeypatch):
    """No env var → fail loud, don't silently return placeholder."""
    monkeypatch.delenv("STOCKNEW_EDGAR_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError, match="STOCKNEW_EDGAR_USER_AGENT"):
        get_user_agent()


def test_get_user_agent_raises_when_env_is_placeholder(monkeypatch):
    """Env var set to the literal placeholder → still fail. Catches the
    case where someone copy-pasted the default value during setup."""
    monkeypatch.setenv("STOCKNEW_EDGAR_USER_AGENT", DEFAULT_USER_AGENT)
    with pytest.raises(RuntimeError, match="placeholder"):
        get_user_agent()


def test_get_user_agent_raises_on_empty_string(monkeypatch):
    """Empty / whitespace-only env var doesn't count as set."""
    monkeypatch.setenv("STOCKNEW_EDGAR_USER_AGENT", "   ")
    with pytest.raises(RuntimeError):
        get_user_agent()


def test_get_user_agent_returns_real_value(monkeypatch):
    """Sanity: a real-looking UA passes through unchanged."""
    monkeypatch.setenv("STOCKNEW_EDGAR_USER_AGENT", "MyApp ed@example.com")
    assert get_user_agent() == "MyApp ed@example.com"


# --- _get_with_retries -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_with_retries_success_on_first_try():
    """200 on first attempt → no retry, no sleep."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(200, {"ok": True}))
    resp = await _get_with_retries(client, "http://x", max_retries=3, rate_limiter=None)
    assert resp.status_code == 200
    assert client.get.call_count == 1


@pytest.mark.asyncio
async def test_get_with_retries_honors_retry_after_on_429():
    """429 with Retry-After: sleep that long, then retry, then succeed."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=[
        _resp(429, b"rate limited", headers={"Retry-After": "1"}),
        _resp(200, {"ok": True}),
    ])
    with patch("src.market_data.edgar.client.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        resp = await _get_with_retries(client, "http://x", max_retries=3, rate_limiter=None)
    assert resp.status_code == 200
    assert client.get.call_count == 2
    # The first sleep arg should be exactly 1.0 (from Retry-After).
    assert sleep_mock.await_args_list[0].args[0] == 1.0


@pytest.mark.asyncio
async def test_get_with_retries_backs_off_on_503():
    """503 → exponential backoff, retry, succeed on the second try."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=[
        _resp(503, b"server busy"),
        _resp(200, {"ok": True}),
    ])
    with patch("src.market_data.edgar.client.asyncio.sleep", new_callable=AsyncMock):
        resp = await _get_with_retries(client, "http://x", max_retries=3, rate_limiter=None)
    assert resp.status_code == 200
    assert client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_with_retries_returns_5xx_after_exhausting_budget():
    """4 retries (1 initial + 3 retries) all 503 → return the last 503,
    don't crash. Caller decides how to interpret persistent failure."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(503, b"server busy"))
    with patch("src.market_data.edgar.client.asyncio.sleep", new_callable=AsyncMock):
        resp = await _get_with_retries(client, "http://x", max_retries=3, rate_limiter=None)
    assert resp.status_code == 503
    assert client.get.call_count == 4  # 1 initial + 3 retries


@pytest.mark.asyncio
async def test_get_with_retries_does_not_retry_on_4xx():
    """404 / 401 / 400 → return immediately. Retrying a client error
    just wastes the per-IP rate budget."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_resp(404, b"not found"))
    resp = await _get_with_retries(client, "http://x", max_retries=3, rate_limiter=None)
    assert resp.status_code == 404
    assert client.get.call_count == 1


# --- helpers ---------------------------------------------------------------


def _resp(status: int, body, headers: dict | None = None) -> httpx.Response:
    """Build a real httpx.Response so callers exercising .status_code and
    .headers see realistic objects, not MagicMock magic."""
    return httpx.Response(
        status_code=status,
        content=body if isinstance(body, (bytes, str)) else None,
        json=body if isinstance(body, dict) else None,
        headers=headers or {},
    )
