"""
监控 Binance USDT 本位永续合约关键指标，并通过飞书告警。

核心逻辑（结合需求图示）：
1. 观察 5-15 分钟内的 OI（未平仓量）快速拉升。
2. 同步关注 Funding Rate（资金费率）极值与方向。
3. 结合盘口深度与多空主动成交（taker 多空比）判断情绪是否一致。
4. 持续输出到飞书，方便人工及时下单。
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from typing import Optional

import requests


from config.config import (
    FEISHU_WEBHOOK,
    FUTURES_KEYWORD,
    FAPI_EXCHANGE_INFO,
    FAPI_PREMIUM_INDEX,
    FAPI_OI_HISTORY,
    FAPI_TAKER_RATIO,
    FAPI_DEPTH,
    FUTURES_POLL_INTERVAL,
    MAX_SYMBOLS,
    OI_CHANGE_PCT,
    PRICE_CHANGE_PCT,
    DEPTH_IMBALANCE_RATIO,
    FUNDING_HIGH,
    FUNDING_WATCH,
    TAKER_RATIO_TREND,
)


def send_feishu_text(content: str) -> None:
    if not FEISHU_WEBHOOK:
        print("FEISHU_WEBHOOK not set; skip sending")
        return

    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = {
        "msg_type": "text",
        "content": {"text": f"{FUTURES_KEYWORD} {content}"},
    }
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=data, headers=headers, timeout=8)
        print("Feishu status:", resp.status_code, resp.text)
    except Exception as exc:  # noqa: BLE001
        print("Feishu error:", exc)


def fetch_usdt_perpetual_symbols() -> List[str]:
    resp = requests.get(FAPI_EXCHANGE_INFO, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    symbols = []
    for item in data.get("symbols", []):
        if (
            item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and item.get("status") == "TRADING"
        ):
            symbols.append(item["symbol"])
    symbols.sort()
    return symbols[:MAX_SYMBOLS]


def fetch_mark_and_funding(symbol: str) -> Tuple[float, float, int]:
    resp = requests.get(FAPI_PREMIUM_INDEX, params={"symbol": symbol}, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    mark_price = float(data.get("markPrice", 0))
    funding_rate = float(data.get("lastFundingRate", 0))
    next_funding_time = int(data.get("nextFundingTime", 0))
    return mark_price, funding_rate, next_funding_time


def fetch_oi_change(symbol: str) -> Tuple[float, float]:
    params = {
        "symbol": symbol,
        "period": "5m",
        "limit": 3,
    }
    resp = requests.get(FAPI_OI_HISTORY, params=params, timeout=8)
    resp.raise_for_status()
    rows = resp.json()
    if len(rows) < 2:
        return 0.0, 0.0

    first = float(rows[0]["sumOpenInterest"])
    last = float(rows[-1]["sumOpenInterest"])
    change_pct = (last - first) / first * 100 if first else 0.0
    return change_pct, last



def fetch_taker_trend(symbol: str) -> Tuple[float, float]:
    params = {
        "symbol": symbol,
        "period": "5m",
        "limit": 2,
    }

    resp = requests.get(FAPI_TAKER_RATIO, params=params, timeout=8)
    resp.raise_for_status()
    rows = resp.json()
    if len(rows) < 2:
        return 0.0, 0.0

    prev = float(rows[0]["buySellRatio"])
    last = float(rows[-1]["buySellRatio"])
    trend = last - prev
    return last, trend



def fetch_depth_imbalance(symbol: str) -> Optional[float]:
    params = {"symbol": symbol, "limit": 50}
    resp = requests.get(FAPI_DEPTH, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    bids_val = sum(float(b[0]) * float(b[1]) for b in data.get("bids", []))
    asks_val = sum(float(a[0]) * float(a[1]) for a in data.get("asks", []))

    if bids_val == 0 or asks_val == 0:
        return None

    return bids_val / asks_val


def format_time(ts_ms: int) -> str:
    if not ts_ms:
        return "N/A"
    dt = datetime.utcfromtimestamp(ts_ms / 1000) + timedelta(hours=8)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC+8"


def main() -> None:
    symbols = fetch_usdt_perpetual_symbols()
    print(f"Loaded {len(symbols)} USDT perpetual symbols")

    send_feishu_text(" 监控已启动")

    last_prices: Dict[str, float] = {}

    while True:
        start_ts = time.time()
        alerts: List[str] = []

        for symbol in symbols:
            try:
                mark_price, funding_rate, next_funding_time = fetch_mark_and_funding(symbol)
                oi_change_pct, oi_total = fetch_oi_change(symbol)
                taker_ratio, taker_trend = fetch_taker_trend(symbol)
                depth_ratio = fetch_depth_imbalance(symbol)

                price_change_pct = 0.0
                if symbol in last_prices and last_prices[symbol]:
                    price_change_pct = (mark_price - last_prices[symbol]) / last_prices[symbol] * 100
                last_prices[symbol] = mark_price

                messages: List[str] = []

                if oi_change_pct >= OI_CHANGE_PCT:
                    messages.append(
                        f"OI +{oi_change_pct:.2f}% 至 {oi_total:.2f}, 5-15 分钟资金涌入"
                    )

                if abs(price_change_pct) >= PRICE_CHANGE_PCT:
                    direction = "上涨" if price_change_pct > 0 else "下跌"
                    messages.append(f"价格{direction} {price_change_pct:+.2f}% 至 {mark_price:.4f}")

                if abs(funding_rate) >= FUNDING_HIGH:
                    messages.append(
                        f"Funding 极值 {funding_rate:+.4f}，情绪过热，下一次 {format_time(next_funding_time)}"
                    )
                elif abs(funding_rate) >= FUNDING_WATCH:
                    messages.append(
                        f"Funding 偏高 {funding_rate:+.4f}，注意多空极端持仓"
                    )

                if abs(taker_trend) >= TAKER_RATIO_TREND:
                    direction = "多头主动" if taker_trend > 0 else "空头主动"
                    messages.append(
                        f"Taker 多空比 {taker_ratio:.2f}（{direction} 连续放量）"
                    )

                if depth_ratio is not None:
                    if depth_ratio >= DEPTH_IMBALANCE_RATIO:
                        messages.append(f"买盘深度 {depth_ratio:.2f}x 卖盘，存在拉升动力")
                    elif depth_ratio <= 1 / DEPTH_IMBALANCE_RATIO:
                        messages.append(f"卖盘深度 {1/depth_ratio:.2f}x 买盘，抛压显著")

                # 组合信号：价格横盘但 OI、taker 同向，提示埋伏
                if (
                    abs(price_change_pct) < PRICE_CHANGE_PCT
                    and oi_change_pct >= OI_CHANGE_PCT
                    and abs(taker_trend) >= TAKER_RATIO_TREND
                ):
                    messages.append("价格横盘 + OI&主动成交同向，关注突破")

                if messages:
                    now = datetime.utcnow() + timedelta(hours=8)
                    stamp = now.strftime("%Y-%m-%d %H:%M:%S UTC+8")
                    detail = "\n".join(messages)

                    depth_str = "N/A" if depth_ratio is None else f"{depth_ratio:.2f}"

                    alert = (
                        f"[{stamp}] {symbol}\n"
                        f"价格 {mark_price:.4f} USDT\n"
                        f"Funding {funding_rate:+.4f}\n"
                        f"盘口买卖比 {depth_str}\n"
                        f"信号:\n{detail}"
                    )
                    alerts.append(alert)
            except Exception as exc:  # noqa: BLE001
                print(f"{symbol} fetch error: {exc}")
                continue

        if alerts:
            text = "\n\n".join(alerts)
            send_feishu_text(text)
        else:
            print("No alert this round")

        duration = time.time() - start_ts
        sleep_for = max(5, FUTURES_POLL_INTERVAL - int(duration))
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()