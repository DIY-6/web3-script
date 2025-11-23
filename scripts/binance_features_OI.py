"""
监控 Binance 所有 USDT 永续合约：

条件（同时满足）：
1. 价格在过去 1 小时变化 >= PRICE_CHANGE_1H_PCT（取绝对值）；
2. OI 在过去 1 小时内增加 >= OI_CHANGE_1H_PCT。

将符合条件的合约输出到飞书，格式：

XXUSDT  MC:$XXM
Price: <当前价格>
OI:$XXM
OI/MC:<比值>
1H price change:xx%
1H OI change:xx%
24H Price change:xx%
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

import requests

from config.config_oi import (
    BINANCE_FAPI_BASE,
    FAPI_EXCHANGE_INFO,
    FAPI_TICKER_24H,
    FAPI_KLINES,
    FAPI_OI_HISTORY,
    POLL_INTERVAL,
    MAX_SYMBOLS,
    PRICE_CHANGE_1H_PCT,
    OI_CHANGE_1H_PCT,
    OI_PERIOD,
    OI_POINTS,
    MIN_NOTIONAL_24H,
    FEISHU_WEBHOOK,
    FEISHU_KEYWORD,
)

print("DEBUG FEISHU_WEBHOOK =", repr(FEISHU_WEBHOOK))
print("DEBUG FEISHU_KEYWORD =", repr(FEISHU_KEYWORD))


# ========= 工具函数 =========

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=2, pool_connections=50, pool_maxsize=50)
session.mount("https://", adapter)
session.mount("http://", adapter)


def http_get(url: str, *, params: Optional[Dict] = None, timeout: int = 10) -> requests.Response:
    """带简单重试的 GET 请求。"""
    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


def send_feishu_text(content: str) -> None:
    if not FEISHU_WEBHOOK:
        print("FEISHU_WEBHOOK not set; skip sending")
        return

    headers = {"Content-Type": "application/json; charset=utf-8"}

    # 飞书文本消息大约 4000 字符以内比较稳，这里保守一点 3500
    MAX_LEN = 3500

    # 按长度切块发送
    for i in range(0, len(content), MAX_LEN):
        part = content[i : i + MAX_LEN]
        data = {
            "msg_type": "text",
            "content": {"text": f"{FEISHU_KEYWORD} {part}"},
        }
        try:
            resp = requests.post(FEISHU_WEBHOOK, json=data, headers=headers, timeout=8)
            print("Feishu status:", resp.status_code, resp.text)
        except Exception as exc:
            print("Feishu error:", exc)
            break

def now_utc8_str() -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=8)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC+8")


# ========= Binance 数据获取 =========

def fetch_usdt_perp_symbols() -> List[str]:
    """获取所有 USDT 永续合约 symbol 列表。"""
    resp = http_get(FAPI_EXCHANGE_INFO)
    data = resp.json()
    symbols: List[str] = []
    for item in data.get("symbols", []):
        if (
            item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and item.get("status") == "TRADING"
        ):
            symbols.append(item["symbol"])
    symbols.sort()
    return symbols[:MAX_SYMBOLS]


def fetch_24h_ticker_map() -> Dict[str, Dict]:
    """
    获取所有 symbol 的 24h 数据：
    - priceChangePercent
    - lastPrice
    - quoteVolume（24H USDT 成交额）
    """
    resp = http_get(FAPI_TICKER_24H)
    rows = resp.json()
    mapping: Dict[str, Dict] = {}
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        mapping[symbol] = row
    return mapping


def fetch_1h_price_change(symbol: str) -> Tuple[float, float]:
    """
    通过 1h K 线计算 1 小时价格变化：
    - 返回 (1H 涨跌幅%, 当前收盘价)
    """
    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": 2,  # 最近两根：前一根收盘 vs 最新收盘
    }
    resp = http_get(FAPI_KLINES, params=params)
    rows = resp.json()
    if len(rows) < 2:
        return 0.0, 0.0

    prev_close = float(rows[0][4])
    last_close = float(rows[-1][4])

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0
    return change_pct, last_close


def fetch_1h_oi_change(symbol: str) -> Tuple[float, float]:
    """
    使用 openInterestHist 估算 1 小时 OI 变化：
    - period: OI_PERIOD（默认 5m）
    - limit: OI_POINTS（默认 13，约 1h）
    - 返回 (1H OI 变化%, 最新 OI 名义价值 USDT)
    """
    params = {
        "symbol": symbol,
        "period": OI_PERIOD,
        "limit": OI_POINTS,
    }
    resp = http_get(FAPI_OI_HISTORY, params=params)
    rows = resp.json()
    if len(rows) < 2:
        return 0.0, 0.0

    first = rows[0]
    last = rows[-1]

    # sumOpenInterestValue 是名义价值（USDT），更直观
    first_val = float(first.get("sumOpenInterestValue", 0.0))
    last_val = float(last.get("sumOpenInterestValue", 0.0))

    change_pct = (last_val - first_val) / first_val * 100 if first_val else 0.0
    return change_pct, last_val


# ========= 主逻辑 =========

def format_millions(value: float) -> str:
    return f"{value/1_000_000:.2f}M"


def main() -> None:

    # 先拿币种列表
    symbols = fetch_usdt_perp_symbols()
    print(f"[{now_utc8_str()}] Loaded {len(symbols)} USDT perpetual symbols")

    # 再发启动提示
    start_msg = (
        f"脚本已启动:\n"
        f"启动时间：{now_utc8_str()}\n"
        f"监控上限：{len(symbols)} 合约\n"
        f"条件：1H价格变化 ≥ {PRICE_CHANGE_1H_PCT}% 且 "
        f"1H OI 增长 ≥ {OI_CHANGE_1H_PCT}%"
    )
    send_feishu_text(start_msg)
    # ===========================


    while True:
        started = time.time()
        alerts: List[str] = []

        try:
            ticker_map = fetch_24h_ticker_map()
        except Exception as exc:
            print("fetch_24h_ticker_map error:", exc)
            ticker_map = {}

        for symbol in symbols:
            try:
                t24 = ticker_map.get(symbol)
                if not t24:
                    continue

                # 过滤日成交额太低的
                quote_volume = float(t24.get("quoteVolume", 0.0))
                if quote_volume < MIN_NOTIONAL_24H:
                    continue

                price_24h_pct = float(t24.get("priceChangePercent", 0.0))

                price_1h_pct, last_price = fetch_1h_price_change(symbol)
                oi_1h_pct, oi_notional = fetch_1h_oi_change(symbol)

                # 只关心：|1H 价格变化| >= 阈值 且 OI 1H 增长 >= 阈值
                if abs(price_1h_pct) < PRICE_CHANGE_1H_PCT:
                    continue
                if oi_1h_pct < OI_CHANGE_1H_PCT:
                    continue

                # MC 用 24H notional 近似（quoteVolume），你可以理解为流动性规模
                mc_notional = quote_volume

                oi_mc_ratio = oi_notional / mc_notional if mc_notional > 0 else 0.0

                line = (
                    f"{symbol}  MC:${format_millions(mc_notional)}\n\n"
                    f"Price: {last_price:.4f}\n"
                    f"OI:${format_millions(oi_notional)}\n"
                    f"OI/MC:{oi_mc_ratio:.2f}\n"
                    f"1H price change:{price_1h_pct:+.2f}%\n"
                    f"1H OI change:{oi_1h_pct:+.2f}%\n"
                    f"24H Price change:{price_24h_pct:+.2f}%"
                )
                alerts.append(line)

            except Exception as exc:
                # print(f"{symbol} fetch error: {exc}")  # 调试时用
                print(f"{now_utc8_str()} {symbol} fetch error: {type(exc).__name__}")
                continue

        if alerts:
            header = f"[{now_utc8_str()}] 1H 异动合约（价格≥{PRICE_CHANGE_1H_PCT}%, OI≥{OI_CHANGE_1H_PCT}%，绝对值）\n\n"
            text = header + "\n\n".join(alerts)
            send_feishu_text(text)
        else:
            print(f"[{now_utc8_str()}] No symbols matched conditions this round")

        elapsed = time.time() - started
        sleep_for = max(5, POLL_INTERVAL - int(elapsed))
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
