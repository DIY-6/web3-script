"""
Binance 永续合约 1H 异动监控配置

所有可调参数都集中在这里，脚本只读这些配置。
"""

import os
from dotenv import load_dotenv

# 读取 .env
load_dotenv()

# ---------- Binance API ----------
BINANCE_FAPI_BASE = "https://fapi.binance.com"

# USDT 本位永续合约列表
FAPI_EXCHANGE_INFO = f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo"

# 24h ticker（取 24H 涨跌 & 24H 交易额）
FAPI_TICKER_24H = f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/24hr"

# K线（用来算 1H 价格变化）
FAPI_KLINES = f"{BINANCE_FAPI_BASE}/fapi/v1/klines"

# OI 历史（用来算 1H OI 变化）
FAPI_OI_HISTORY = f"{BINANCE_FAPI_BASE}/futures/data/openInterestHist"


# ---------- 监控参数（你之后基本只改这里） ----------

# 轮询间隔（秒）
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))  # 默认 5 分钟跑一次

# 最多监控多少个 USDT 永续（想全市场就给个大数即可）
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "9999"))

# 价格 1 小时变化阈值（百分比，取绝对值）
PRICE_CHANGE_1H_PCT = float(os.getenv("PRICE_CHANGE_1H_PCT", "11.0"))

# OI 1 小时增长阈值（百分比，只看增加）
OI_CHANGE_1H_PCT = float(os.getenv("OI_CHANGE_1H_PCT", "10.0"))

# OI 使用的时间粒度（Binance 支持：5m, 15m, 1h, 4h, 1d）
OI_PERIOD = os.getenv("OI_PERIOD", "5m")
# 为了覆盖 1 小时，取多少个点（5m 粒度下 12~13 个点 ≈ 1h）
OI_POINTS = int(os.getenv("OI_POINTS", "13"))

# 过滤太小的 24H 交易额（单位：USD），避免空气币乱报
MIN_NOTIONAL_24H = float(os.getenv("MIN_NOTIONAL_24H", "1000000"))  # 比如 "1000000" 过滤日成交 < 100w 的


# ---------- 飞书配置 ----------

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
FEISHU_KEYWORD = os.getenv("FEISHU_KEYWORD_oi", "Binance Futures OI")