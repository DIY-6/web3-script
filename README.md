# web3-script
监控脚本集合：

- `scripts/btc_watch.py`：监控指定现货交易对价格波动并推送飞书。
- `scripts/binance_futures_monitor.py`：监控 Binance 所有 USDT 本位永续合约的 OI、Funding、盘口与主动成交方向，满足条件时推送飞书。

## 使用方法

1. 准备 `.env` 文件，至少包含：
   ```bash
   FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
   FEISHU_KEYWORD=BTC
   FUTURES_KEYWORD=FuturesWatch
   ```
2. 安装依赖：`pip install -r requirements.txt`。
3. 运行永续监控：
   ```bash
   python scripts/binance_futures_monitor.py
   ```

### 关键阈值（可通过环境变量覆盖）
- `OI_CHANGE_PCT`：5-15 分钟内 OI 涨幅阈值，默认 10%。
- `PRICE_CHANGE_PCT`：短时价格变动阈值，默认 2%。
- `FUNDING_WATCH`/`FUNDING_HIGH`：资金费率关注/极值阈值，默认 0.05% / 0.1%。
- `DEPTH_IMBALANCE_RATIO`：盘口买卖深度倍数阈值，默认 1.5x。
- `TAKER_RATIO_TREND`：taker 多空比趋势阈值，默认 0.2。

> 建议根据个人风控调整阈值和 `FUTURES_POLL_INTERVAL` 轮询周期。