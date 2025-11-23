from dotenv import load_dotenv
import os

# 读取 .env
load_dotenv()

# 从环境变量拿敏感信息
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
FEISHU_KEYWORD = os.getenv("FEISHU_KEYWORD_btc", "BTC")

# 现货价格监控配置
SYMBOL = "BTCUSDT"
API_URL = "https://api.binance.com/api/v3/ticker/price"
POLL_INTERVAL = 5
ALERT_CHANGE_PCT = 1

# 永续合约监控配置
FAPI_BASE_URL = "https://fapi.binance.com"
FAPI_EXCHANGE_INFO = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
FAPI_PREMIUM_INDEX = f"{FAPI_BASE_URL}/fapi/v1/premiumIndex"
FAPI_OI_HISTORY = f"{FAPI_BASE_URL}/futures/data/openInterestHist"
FAPI_TAKER_RATIO = f"{FAPI_BASE_URL}/futures/data/takerlongshortRatio"
FAPI_DEPTH = f"{FAPI_BASE_URL}/fapi/v1/depth"

# 监控节奏
FUTURES_POLL_INTERVAL = int(os.getenv("FUTURES_POLL_INTERVAL", "60"))
MAX_SYMBOLS = int(os.getenv("MAX_SYMBOLS", "40"))  # 防止过多请求，可按需调整

# 告警阈值
OI_CHANGE_PCT = float(os.getenv("OI_CHANGE_PCT", "10"))  # 5-15 分钟 OI 上涨幅度阈值
PRICE_CHANGE_PCT = float(os.getenv("PRICE_CHANGE_PCT", "10"))  # 价格短时涨跌幅
DEPTH_IMBALANCE_RATIO = float(os.getenv("DEPTH_IMBALANCE_RATIO", "1.5"))  # 买卖盘深度差
FUNDING_HIGH = float(os.getenv("FUNDING_HIGH", "0.01"))  # 0.1%
FUNDING_WATCH = float(os.getenv("FUNDING_WATCH", "0.05"))  # 0.05%
TAKER_RATIO_TREND = float(os.getenv("TAKER_RATIO_TREND", "0.5"))  # 多空比变化

# Feishu 关键字用于永续监控
FUTURES_KEYWORD = os.getenv("FUTURES_KEYWORD_fu", "Binance Futures")