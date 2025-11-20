import time
import requests
from datetime import datetime,timedelta

# ===== 配置区 =====
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/d509003d-059c-42a2-b1bd-3baa8aabe3a3"  # 飞书自定义机器人 Webhook
FEISHU_KEYWORD = "BTC"                  # 机器人关键词（按你飞书里设置的来）

SYMBOL = "BTCUSDT"                      # 监控 BTC/USDT
API_URL = "https://api.binance.com/api/v3/ticker/price"

POLL_INTERVAL = 120                      # 查询间隔（秒），可改大一点
ALERT_CHANGE_PCT = 1                  # 价格相对上次通知波动超过 0.5% 就推送
# ==================


def send_feishu_text(content: str):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = {
        "msg_type": "text",
        "content": {
            "text": f"{FEISHU_KEYWORD} {content}"
        }
    }
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=data, headers=headers, timeout=5)
        print("Feishu status:", resp.status_code, resp.text)
    except Exception as e:
        print("Feishu error:", e)


def get_price() -> float:
    resp = requests.get(API_URL, params={"symbol": SYMBOL}, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return float(data["price"])


def main():
    last_notify_price = None

    while True:
        try:
            price = get_price()
            now = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S UTC+8")
            print(f"[{now}] {SYMBOL} price = {price}")

            if last_notify_price is None:
                # 第一次直接发一条当前价
                msg = f"BTC 价格监控启动：当前价格 {price:.2f} USDT（时间：{now}）"
                send_feishu_text(msg)
                last_notify_price = price
            else:
                change_pct = (price - last_notify_price) / last_notify_price * 100
                if abs(change_pct) >= ALERT_CHANGE_PCT:
                    direction = "上涨" if change_pct > 0 else "下跌"
                    msg = (
                        f"BTC 价格{direction}预警：\n"
                        f"当前价格：{price:.2f} USDT\n"
                        f"上次通知价：{last_notify_price:.2f} USDT\n"
                        f"变动：{change_pct:+.2f}%\n"
                        f"时间：{now}"
                    )
                    send_feishu_text(msg)
                    last_notify_price = price

        except Exception as e:
            print("Loop error:", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
