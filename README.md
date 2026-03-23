# 币安期货主力出货监控系统

一个实时监控系统，通过分析币安期货数据（OI、资金费率、期现价差等）来识别主力出货/吸筹信号。

## 核心监控逻辑

### 出货信号
- OI增长 + 资金费率转负 + 期货贴水 + 现货大单净流出
- 主力在期货开空，同时现货卖出

### 吸筹信号
- OI增长 + 资金费率正 + 期货升水 + 现货净流入
- 主力在期货开多，同时现货买入

### 多因子验证
单一OI指标不足以判断，系统结合以下指标进行综合评分：
- OI变化率 (30%)
- 资金费率 (25%)
- 期现价差 (25%)
- 现货流向 (20%)

## 快速开始

### 1. 安装依赖

```bash
cd binance-whale-monitor
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的API密钥（可选，用于更高频率限制）
```

### 3. 运行监控

**命令行模式：**
```bash
python monitor.py
```

**Web可视化界面：**
```bash
streamlit run web/dashboard.py
# 或
python monitor.py --web
```

## 项目结构

```
binance-whale-monitor/
├── data/
│   ├── __init__.py
│   ├── binance_client.py    # 币安API客户端
│   └── websocket_client.py  # WebSocket实时数据
├── signals/
│   ├── __init__.py
│   ├── calculator.py        # 信号计算引擎
│   └── indicators.py        # 技术指标计算
├── alert/
│   ├── __init__.py
│   └── manager.py           # 告警管理
├── web/
│   ├── __init__.py
│   └── dashboard.py         # Streamlit面板
├── config.py                # 配置文件
├── requirements.txt         # 依赖
├── monitor.py              # 主监控程序入口
└── README.md               # 使用说明
```

## 配置文件说明

编辑 `config.py` 或使用环境变量：

```python
# 监控交易对
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT')

# OI监控阈值 (%)
OI_CHANGE_THRESHOLD = 5.0

# 资金费率监控阈值 (%)
FUNDING_RATE_THRESHOLD = 0.01

# 期现价差阈值 (%)
BASIS_THRESHOLD = 0.1

# 信号综合评分阈值
SIGNAL_STRONG = 0.7
SIGNAL_MEDIUM = 0.5
SIGNAL_WEAK = 0.3

# 数据更新间隔 (秒)
UPDATE_INTERVAL = 30
```

## 信号强度计算

```
出货信号强度 = w1*ΔOI + w2*FundingRate + w3*Basis + w4*SpotOutflow
吸筹信号强度 = w1*ΔOI + w2*FundingRate + w3*Basis + w4*SpotInflow

阈值:
- 0.7+: 强烈信号 🔴
- 0.5-0.7: 中等信号 🟡
- 0.3-0.5: 弱信号 🟢
- <0.3: 无信号 ⚪
```

## 关键监控指标

| 指标 | 来源 | 用途 |
|------|------|------|
| Open Interest (OI) | /fapi/v1/openInterest | 判断资金进场/出场 |
| Funding Rate | /fapi/v1/fundingRate | 判断多空情绪 |
| Mark Price | /fapi/v1/premiumIndex | 计算期现价差 |
| Spot Price | /api/v3/ticker/price | 计算基差 |
| Long/Short Ratio | /fapi/v1/topLongShortAccountRatio | 判断散户情绪 |

## Web界面功能

- 📊 实时信号监控卡片
- 📈 OI变化趋势图
- 🌡️ 资金费率热力图
- 🎯 信号强度仪表盘
- 🔔 实时告警列表
- 📋 详细指标表格

## 告警通知

系统支持多种告警渠道：

1. **控制台输出** - 默认启用
2. **Telegram** - 需要配置 bot token 和 chat id
3. **Webhook** - 可推送到自定义接口

配置告警：

```python
from alert.manager import AlertManager, AlertConfig

config = AlertConfig(
    telegram_enabled=True,
    telegram_bot_token='your_bot_token',
    telegram_chat_id='your_chat_id'
)

alert_manager = AlertManager(config)
```

## 运行示例

```
🚨 【主力出货】 BTCUSDT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 信号强度: 78.5% (strong)
📈 OI变化: +8.32%
💰 资金费率: -0.0234%
📉 期现价差: -0.15%
🌊 现货流向: outflow

🔍 详细评分:
  • OI分量: 1.00
  • 资金费率分量: 0.85
  • 基差分量: 0.75
  • 流向分量: 0.90

⏰ 时间: 2024-01-15 14:32:18
```

## 注意事项

1. **API限制**: 未使用API密钥时，请求频率受币安限制（1200 weight/分钟）
2. **信号延迟**: 数据更新间隔建议设置为 30 秒以上
3. **风险提示**: 本系统仅供参考，不构成投资建议
4. **误报可能**: 建议结合其他分析工具验证信号

## 许可证

MIT License
