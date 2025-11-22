from dotenv import load_dotenv
import os

# 读取 .env
load_dotenv()

# 从环境变量拿敏感信息
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
FEISHU_KEYWORD = os.getenv("FEISHU_KEYWORD", "BTC")

# 普通配置直接写死
SYMBOL = "BTCUSDT"
API_URL = "https://api.binance.us/api/v3/ticker/price"
POLL_INTERVAL = 5
ALERT_CHANGE_PCT = 0.1

