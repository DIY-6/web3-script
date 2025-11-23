from types import SimpleNamespace
from unittest.mock import patch
import pytest

import scripts.binance_futures_monitor as monitor


class MockResponse(SimpleNamespace):
    status_code: int = 200
    text: str = "ok"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ValueError(f"status {self.status_code}")

    def json(self):
        return self.payload


def test_fetch_usdt_perpetual_symbols_filters_and_limits():
    payload = {
        "symbols": [
            {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "status": "TRADING"},
            {"symbol": "ETHUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT", "status": "TRADING"},
            {"symbol": "FOOUSD", "contractType": "PERPETUAL", "quoteAsset": "USD", "status": "TRADING"},
        ]
    }
    with patch.object(monitor, "MAX_SYMBOLS", 1), patch(
        "scripts.binance_futures_monitor.requests.get",
        return_value=MockResponse(payload=payload),
    ):
        symbols = monitor.fetch_usdt_perpetual_symbols()
    assert symbols == ["BTCUSDT"]


def test_fetch_mark_and_funding_parses_values():
    payload = {"markPrice": "123.45", "lastFundingRate": "0.001", "nextFundingTime": 1234567890}
    with patch(
        "scripts.binance_futures_monitor.requests.get",
        return_value=MockResponse(payload=payload),
    ):
        mark, rate, ts = monitor.fetch_mark_and_funding("BTCUSDT")
    assert mark == 123.45
    assert rate == 0.001
    assert ts == 1234567890


def test_fetch_oi_change_returns_percentage():
    payload = [
        {"sumOpenInterest": "100"},
        {"sumOpenInterest": "120"},
    ]
    with patch(
        "scripts.binance_futures_monitor.requests.get",
        return_value=MockResponse(payload=payload),
    ):
        pct, total = monitor.fetch_oi_change("BTCUSDT")
    assert round(pct, 2) == 20.0
    assert total == 120.0


def test_fetch_taker_trend_reports_delta():
    payload = [
        {"buySellRatio": "0.8"},
        {"buySellRatio": "1.2"},
    ]
    with patch(
        "scripts.binance_futures_monitor.requests.get",
        return_value=MockResponse(payload=payload),
    ):
        ratio, trend = monitor.fetch_taker_trend("BTCUSDT")
    assert ratio == 1.2
    assert trend == pytest.approx(0.4)


def test_fetch_depth_imbalance_handles_zero_ask():
    payload = {"bids": [["100", "2"]], "asks": []}
    with patch(
        "scripts.binance_futures_monitor.requests.get",
        return_value=MockResponse(payload=payload),
    ):
        ratio = monitor.fetch_depth_imbalance("BTCUSDT")
    assert ratio == 0.0


def test_format_time_humanizes_timestamp():
    ts = 0
    assert monitor.format_time(ts) == "N/A"

    ts = 1609459200000  # 2021-01-01 00:00:00 UTC
    formatted = monitor.format_time(ts)
    assert "2021-01-01 08:00:00 UTC+8" in formatted