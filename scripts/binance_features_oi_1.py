"""
监控 Binance 所有 USDT 永续合约 + CoinGecko 实时流通市值 MC：

触发条件（满足其一）：

条件1（1小时级别）：
1. 价格在过去 1 小时变化 >= PRICE_CHANGE_1H_PCT（取绝对值）；
2. OI 在过去 1 小时内增加 >= OI_CHANGE_1H_PCT。

条件2（15分钟级别）：
1. 价格在过去 15 分钟变化 >= PRICE_CHANGE_15M_PCT（取绝对值）；
2. OI 在过去 15 分钟内增加 >= OI_CHANGE_15M_PCT。

将满足上述条件的合约输出到飞书，格式（UTC+8）：

XXUSDT  MC:$XXM
Price: <当前价格>
OI:$XXM
OI/MC:<比值>
15min price change:xx%
15min OI change:xx%
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
    FEISHU_WEBHOOK,
    FEISHU_KEYWORD,
)

print("DEBUG FEISHU_WEBHOOK =", repr(FEISHU_WEBHOOK))
print("DEBUG FEISHU_KEYWORD =", repr(FEISHU_KEYWORD))


# ========= 可调参数（只改这里）=========

# 轮询间隔（秒）
POLL_INTERVAL: int = 60

# 最多监控多少个 USDT 永续合约（按 exchangeInfo 返回顺序截断）
MAX_SYMBOLS: int = 500

# 24H 成交额过滤下限（USDT），小于这个就不监控，避免垃圾币
MIN_NOTIONAL_24H: float = 5_000_000.0

# 1 小时触发条件阈值
PRICE_CHANGE_1H_PCT: float = 11.0  # 1H 价格变动绝对值 >= 11%
OI_CHANGE_1H_PCT: float = 10.0     # 1H OI 增长 >= 10%

# 15 分钟触发条件阈值
PRICE_CHANGE_15M_PCT: float = 8.0  # 15m 价格变动绝对值 >= 8%
OI_CHANGE_15M_PCT: float = 8.0     # 15m OI 增长 >= 8%

# 价格波动是否取绝对值（True = 涨跌都算，False = 只看上涨）
USE_ABS_PRICE_CHANGE: bool = True

# 价格 K 线配置
PRICE_1H_INTERVAL: str = "1h"
PRICE_1H_LIMIT: int = 2           # 取最近两根 1h K 线

PRICE_15M_INTERVAL: str = "15m"
PRICE_15M_LIMIT: int = 2          # 取最近两根 15m K 线

# OI 历史配置（Binance openInterestHist）
# 说明：period 支持 "5m", "15m", "1h", "4h" 等
OI_1H_PERIOD: str = "1h"
OI_1H_POINTS: int = 2             # 最近两条 1h OI 数据

OI_15M_PERIOD: str = "15m"
OI_15M_POINTS: int = 2            # 最近两条 15m OI 数据

# ========= CoinGecko 相关配置 =========

COINGECKO_API_BASE: str = "https://api.coingecko.com/api/v3"

# MC 刷新间隔（秒），不要太频繁避免被限流
COINGECKO_REFRESH_SECONDS: int = 300

# Binance symbol -> CoinGecko id 映射（只手动维护对不上号的币，主流都在这里写好）
# 比如：BTCUSDT -> bitcoin，ETHUSDT -> ethereum
SYMBOL_TO_COINGECKO_ID: Dict[str, str] = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana",
    "XRPUSDT": "ripple",
    "DOGEUSDT": "dogecoin",
    "ADAUSDT": "cardano",
    "TONUSDT": "toncoin",
    "TRXUSDT": "tron",
    "LINKUSDT": "chainlink",
    # 以后发现对不上号的，可以继续往这里补
}

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
        part = content[i: i + MAX_LEN]
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


def fetch_price_change(symbol: str, interval: str, limit: int) -> Tuple[float, float]:
    """
    通用价格变化计算：
    - interval: "1h" / "15m" 等
    - limit: 至少 2
    - 返回 (涨跌幅%, 最新收盘价)
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    resp = http_get(FAPI_KLINES, params=params)
    rows = resp.json()
    if len(rows) < 2:
        return 0.0, 0.0

    prev_close = float(rows[-2][4])
    last_close = float(rows[-1][4])

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0
    return change_pct, last_close


def fetch_oi_change(symbol: str, period: str, points: int) -> Tuple[float, float]:
    """
    使用 openInterestHist 估算一段时间 OI 变化：
    - period: "15m" / "1h" 等
    - points: 至少 2
    - 返回 (OI 变化%, 最新 OI 名义价值 USDT)
    """
    params = {
        "symbol": symbol,
        "period": period,
        "limit": points,
    }
    resp = http_get(FAPI_OI_HISTORY, params=params)
    rows = resp.json()
    if len(rows) < 2:
        return 0.0, 0.0

    first = rows[-2]
    last = rows[-1]

    # sumOpenInterestValue 是名义价值（USDT）
    first_val = float(first.get("sumOpenInterestValue", 0.0))
    last_val = float(last.get("sumOpenInterestValue", 0.0))

    change_pct = (last_val - first_val) / first_val * 100 if first_val else 0.0
    return change_pct, last_val


# ========= CoinGecko 相关逻辑 =========

def build_symbol_id_map(symbols: List[str]) -> Dict[str, str]:
    """
    构建 symbol -> coingecko_id 映射：
    1. 如果在 SYMBOL_TO_COINGECKO_ID 中有显式配置，则用配置；
    2. 否则用一个简单 heuristic：base = symbol[:-4].lower()（如 BTCUSDT -> btc）。
       很多山寨币可能对不上，需要你后期在 SYMBOL_TO_COINGECKO_ID 里补。
    """
    mapping: Dict[str, str] = {}
    for s in symbols:
        if s in SYMBOL_TO_COINGECKO_ID:
            mapping[s] = SYMBOL_TO_COINGECKO_ID[s]
        else:
            # 假设都是 XXXUSDT 结构，截掉 USDT
            if s.endswith("USDT"):
                base = s[:-4].lower()
            else:
                base = s.lower()
            mapping[s] = base
    return mapping


def chunk_list(items: List[str], size: int) -> List[List[str]]:
    return [items[i: i + size] for i in range(0, len(items), size)]


def fetch_mc_map_from_coingecko(symbol_id_map: Dict[str, str]) -> Dict[str, float]:
    """
    使用 CoinGecko simple/price 接口获取 MC：
    - 对每个 coingecko_id 请求 usd_market_cap
    - 返回 {symbol: mc_usd}
    注意：CoinGecko 的 market_cap 定义就是 circulating_supply * current_price，
    符合你要的 MC 定义。
    """
    # 去重后的 id 列表
    ids = sorted(set(symbol_id_map.values()))
    if not ids:
        return {}

    id_to_mc: Dict[str, float] = {}

    # simple/price 单次最多支持 ~250 个 id，这里保守用 200 一批
    for batch in chunk_list(ids, 200):
        params = {
            "ids": ",".join(batch),
            "vs_currencies": "usd",
            "include_market_cap": "true",
        }
        try:
            resp = http_get(f"{COINGECKO_API_BASE}/simple/price", params=params, timeout=10)
            data = resp.json()
            for cid, val in data.items():
                mc = float(val.get("usd_market_cap") or 0.0)
                if mc > 0:
                    id_to_mc[cid] = mc
        except Exception as exc:
            print(f"{now_utc8_str()} CoinGecko batch fetch error: {type(exc).__name__} - {exc}")
            continue

    # 映射回 symbol
    symbol_mc: Dict[str, float] = {}
    for symbol, cid in symbol_id_map.items():
        mc = id_to_mc.get(cid, 0.0)
        if mc > 0:
            symbol_mc[symbol] = mc

    print(f"{now_utc8_str()} CoinGecko MC loaded for {len(symbol_mc)} symbols")
    return symbol_mc


# ========= 主逻辑 =========

def format_millions(value: float) -> str:
    return f"{value / 1_000_000:.2f}M"


def main() -> None:
    # 先拿币种列表
    symbols = fetch_usdt_perp_symbols()
    print(f"[{now_utc8_str()}] Loaded {len(symbols)} USDT perpetual symbols")

    # 构建 symbol -> coingecko_id 映射
    symbol_id_map = build_symbol_id_map(symbols)
    print(f"[{now_utc8_str()}] Built symbol-id map for {len(symbol_id_map)} symbols")

    # 初次拉 MC
    last_mc_update = 0.0
    mc_map: Dict[str, float] = {}

    # 脚本启动提示
    start_msg = (
        f"脚本已启动:\n"
        f"启动时间：{now_utc8_str()}\n"
        f"监控上限：{len(symbols)} 合约\n"
        f"条件1（1H）：|1H 价格变化| ≥ {PRICE_CHANGE_1H_PCT}% 且 "
        f"1H OI 增长 ≥ {OI_CHANGE_1H_PCT}%\n"
        f"条件2（15m）：|15m 价格变化| ≥ {PRICE_CHANGE_15M_PCT}% 且 "
        f"15m OI 增长 ≥ {OI_CHANGE_15M_PCT}%\n\n"
        f"MC 来源：CoinGecko market_cap(USD)，定义等价于 circulating_supply × price。\n"
        f"MC 刷新间隔：{COINGECKO_REFRESH_SECONDS}s；"
        f"部分新币/屎币可能获取不到 MC，会自动跳过。"
    )
    send_feishu_text(start_msg)

    while True:
        started = time.time()
        alerts: List[str] = []

        # 按周期刷新 CoinGecko MC
        now_ts = time.time()
        if now_ts - last_mc_update > COINGECKO_REFRESH_SECONDS:
            try:
                mc_map = fetch_mc_map_from_coingecko(symbol_id_map)
                last_mc_update = now_ts
            except Exception as exc:
                print(f"{now_utc8_str()} refresh MC error: {type(exc).__name__} - {exc}")

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

                # 过滤日成交额太低的（只是流动性过滤）
                quote_volume = float(t24.get("quoteVolume", 0.0))
                if quote_volume < MIN_NOTIONAL_24H:
                    continue

                price_24h_pct = float(t24.get("priceChangePercent", 0.0))

                # 价格变化（1H & 15m）
                price_1h_pct, last_price = fetch_price_change(
                    symbol, PRICE_1H_INTERVAL, PRICE_1H_LIMIT
                )
                price_15m_pct, _ = fetch_price_change(
                    symbol, PRICE_15M_INTERVAL, PRICE_15M_LIMIT
                )

                # OI 变化（1H & 15m）
                oi_1h_pct, oi_notional = fetch_oi_change(
                    symbol, OI_1H_PERIOD, OI_1H_POINTS
                )
                oi_15m_pct, _ = fetch_oi_change(
                    symbol, OI_15M_PERIOD, OI_15M_POINTS
                )

                # MC 从 CoinGecko 来（USD）
                mc_notional = mc_map.get(symbol, 0.0)
                if mc_notional <= 0:
                    # 没拿到 MC 的直接跳过
                    continue

                # 条件判断
                if USE_ABS_PRICE_CHANGE:
                    cond_1h_price_ok = abs(price_1h_pct) >= PRICE_CHANGE_1H_PCT
                    cond_15m_price_ok = abs(price_15m_pct) >= PRICE_CHANGE_15M_PCT
                else:
                    cond_1h_price_ok = price_1h_pct >= PRICE_CHANGE_1H_PCT
                    cond_15m_price_ok = price_15m_pct >= PRICE_CHANGE_15M_PCT

                cond_1h = cond_1h_price_ok and (oi_1h_pct >= OI_CHANGE_1H_PCT)
                cond_15m = cond_15m_price_ok and (oi_15m_pct >= OI_CHANGE_15M_PCT)

                # 没有任何一个条件满足就跳过
                if not (cond_1h or cond_15m):
                    continue

                oi_mc_ratio = oi_notional / mc_notional if mc_notional > 0 else 0.0

                line = (
                    f"{symbol}  MC:${format_millions(mc_notional)}\n\n"
                    f"Price: {last_price:.4f}\n"
                    f"OI:${format_millions(oi_notional)}\n"
                    f"OI/MC:{oi_mc_ratio:.4f}\n"
                    f"15min price change:{price_15m_pct:+.2f}%\n"
                    f"15min OI change:{oi_15m_pct:+.2f}%\n"
                    f"1H price change:{price_1h_pct:+.2f}%\n"
                    f"1H OI change:{oi_1h_pct:+.2f}%\n"
                    f"24H Price change:{price_24h_pct:+.2f}%"
                )
                alerts.append(line)

            except Exception as exc:
                print(f"{now_utc8_str()} {symbol} fetch error: {type(exc).__name__} - {exc}")
                continue

        if alerts:
            header = (
                f"[{now_utc8_str()}] 价格/OI 异动合约\n"
                f"条件1（1H）：|ΔP_1H|≥{PRICE_CHANGE_1H_PCT}%, ΔOI_1H≥{OI_CHANGE_1H_PCT}%\n"
                f"条件2（15m）：|ΔP_15m|≥{PRICE_CHANGE_15M_PCT}%, ΔOI_15m≥{OI_CHANGE_15M_PCT}%\n\n"
            )
            text = header + "\n\n".join(alerts)
            send_feishu_text(text)
        else:
            print(f"[{now_utc8_str()}] No symbols matched conditions this round")

        elapsed = time.time() - started
        sleep_for = max(5, POLL_INTERVAL - int(elapsed))
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
