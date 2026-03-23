"""
实时WebSocket监控服务器
- 自动发现异常币种
- 实时推送数据到前端
- 智能分析庄家行为
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set
import sys
sys.path.insert(0, '.')

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from data.screener import MarketScreener, ScreeningCriteria, AnomalyScore
from data.binance_client import BinanceAPIClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="币安期货实时监控系统")

# 全局状态
class MonitorState:
    def __init__(self):
        self.screener = MarketScreener(
            client=BinanceAPIClient(),
            criteria=ScreeningCriteria(
                min_oi_change_percent=5.0,
                min_funding_rate=0.03,
                min_price_change_24h=3.0
            )
        )
        self.active_connections: List[WebSocket] = []
        self.known_symbols: Set[str] = set()  # 已通知的币种
        self.anomaly_history: Dict[str, dict] = {}
        self.running = False

state = MonitorState()

# 智能分析模板
WHALE_ANALYSIS = {
    'distribution': {
        'high_funding_short': '庄家可能在高位开空，利用高资金费率吸引多头接盘出货',
        'oi_drop_price_drop': '持仓量下降伴随价格下跌，庄家已完成出货',
        'oi_rise_price_drop': '持仓量上升价格下跌，庄家正在打压吸筹或出货',
    },
    'accumulation': {
        'high_funding_long': '庄家可能在建仓多头，市场空头付息较多',
        'oi_rise_price_rise': '持仓量价格齐涨，庄家正在拉升建仓',
        'oi_drop_price_rise': '缩量上涨，庄家控盘度高',
    },
    'manipulation': {
        'extreme_funding': '资金费率极端，可能存在逼空或逼多操作',
        'volume_spike': '成交量异常放大，庄家正在诱导散户跟风',
        'low_cap_pump': '小币种突然放量，典型的庄家拉盘特征',
    }
}

def analyze_whale_behavior(anomaly: AnomalyScore) -> str:
    """智能分析庄家行为"""
    signals = anomaly.signals
    components = anomaly.components
    score = anomaly.total_score

    # 分析资金费率方向
    funding_signal = next((s for s in signals if '资金费率' in s), '')
    is_negative_funding = '空头付息' in funding_signal
    is_extreme_funding = components.get('funding', 0) > 0.8

    # 分析价格变化
    price_signal = next((s for s in signals if '价格变化' in s), '')
    is_price_up = '+' in price_signal if price_signal else False
    is_big_move = components.get('volume', 0) > 0.7

    # 生成分析
    if is_extreme_funding and is_negative_funding:
        if is_price_up:
            return "🚨 庄家疑似高位诱多：资金费率极端负值但价格上涨，可能是出货陷阱"
        else:
            return "💰 庄家可能在吸筹：空头付息极高，庄家收集带血筹码"

    elif is_extreme_funding and not is_negative_funding:
        if is_price_up:
            return "📈 庄家拉升建仓：多头付息高，庄家愿意承担成本拉盘"
        else:
            return "⚠️ 庄家可能出货：多头付息高但价格下跌，散户追高庄家出货"

    elif is_big_move:
        if is_price_up:
            return "🎯 小币种异动：可能是庄家启动行情，关注成交量持续性"
        else:
            return "🔻 放量下跌：庄家恐慌盘或主动砸盘，关注是否止跌"

    elif components.get('oi_change', 0) > 0.5:
        return "📊 持仓量异常：大户正在布局，方向不明但波动将至"

    else:
        return "👁️ 综合评分异常：多指标共振，建议密切关注"

async def broadcast(message: dict):
    """广播消息到所有连接"""
    disconnected = []
    for conn in state.active_connections:
        try:
            await conn.send_json(message)
        except:
            disconnected.append(conn)

    # 清理断开的连接
    for conn in disconnected:
        if conn in state.active_connections:
            state.active_connections.remove(conn)

async def monitor_loop():
    """监控循环"""
    logger.info("🚀 启动实时监控系统...")

    while state.running:
        try:
            logger.info("📡 执行全量扫描...")

            # 获取数据
            snapshots = await state.screener.get_all_snapshots()
            anomalies = state.screener.screen_anomalies(snapshots, min_score=0.3)

            # 找出新的异常
            new_anomalies = []
            current_symbols = set()

            for anomaly in anomalies[:20]:  # 只处理前20
                current_symbols.add(anomaly.symbol)

                # 新币种或评分显著变化
                is_new = anomaly.symbol not in state.known_symbols
                score_changed = (
                    anomaly.symbol in state.anomaly_history and
                    abs(state.anomaly_history[anomaly.symbol]['score'] - anomaly.total_score) > 0.15
                )

                if is_new:
                    new_anomalies.append(anomaly)
                    state.known_symbols.add(anomaly.symbol)

                # 更新历史
                state.anomaly_history[anomaly.symbol] = {
                    'score': anomaly.total_score,
                    'timestamp': datetime.now().isoformat(),
                    'signals': anomaly.signals
                }

            # 广播数据
            data = {
                'type': 'update',
                'timestamp': datetime.now().isoformat(),
                'total_scanned': len(snapshots),
                'anomalies_count': len(anomalies),
                'new_count': len(new_anomalies),
                'anomalies': [
                    {
                        'symbol': a.symbol,
                        'score': round(a.total_score, 3),
                        'components': {k: round(v, 3) for k, v in a.components.items()},
                        'signals': a.signals[:3],
                        'analysis': analyze_whale_behavior(a),
                        'is_new': a.symbol in {na.symbol for na in new_anomalies}
                    }
                    for a in anomalies[:15]
                ]
            }

            await broadcast(data)

            # 如果有新发现，发送警报
            for anomaly in new_anomalies:
                alert = {
                    'type': 'alert',
                    'symbol': anomaly.symbol,
                    'score': round(anomaly.total_score, 3),
                    'analysis': analyze_whale_behavior(anomaly),
                    'timestamp': datetime.now().isoformat()
                }
                await broadcast(alert)
                logger.info(f"🚨 新信号: {anomaly.symbol} - {alert['analysis'][:50]}...")

            # 清理过期的known_symbols（保留最近50个）
            if len(state.known_symbols) > 100:
                state.known_symbols = set(list(state.known_symbols)[-50:])

            # 等待下一轮
            await asyncio.sleep(15)  # 15秒更新一次

        except Exception as e:
            logger.error(f"监控循环错误: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup():
    """启动时初始化"""
    state.running = True
    asyncio.create_task(monitor_loop())

@app.on_event("shutdown")
async def shutdown():
    """关闭时清理"""
    state.running = False

@app.get("/")
async def get_dashboard():
    """返回实时监控页面"""
    return HTMLResponse(content=DASHBOARD_HTML)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket连接处理"""
    await websocket.accept()
    state.active_connections.append(websocket)
    logger.info(f"✅ 新连接: {websocket.client}")

    # 发送初始数据
    await websocket.send_json({
        'type': 'connected',
        'message': '已连接到实时监控系统'
    })

    try:
        while True:
            # 保持连接，接收前端心跳
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get('action') == 'ping':
                await websocket.send_json({'type': 'pong', 'time': datetime.now().isoformat()})

    except WebSocketDisconnect:
        state.active_connections.remove(websocket)
        logger.info(f"❌ 连接断开: {websocket.client}")

# 实时前端HTML
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>币安期货实时监控系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e14;
            color: #e8e8e8;
            min-height: 100vh;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 25px 30px;
            box-shadow: 0 4px 30px rgba(102, 126, 234, 0.3);
        }

        .header h1 {
            font-size: 24px;
            font-weight: 700;
        }

        .header .status {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 8px;
            font-size: 13px;
            opacity: 0.9;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            background: #00ff88;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }

        .stats-bar {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }

        .stat-card {
            background: linear-gradient(145deg, #151b26 0%, #1a2332 100%);
            border: 1px solid #2a3441;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            transition: all 0.3s;
        }

        .stat-card:hover {
            border-color: #667eea;
            transform: translateY(-2px);
        }

        .stat-value {
            font-size: 36px;
            font-weight: 700;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .stat-label {
            font-size: 12px;
            color: #8892a0;
            margin-top: 5px;
        }

        .main-grid {
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 20px;
        }

        .panel {
            background: #151b26;
            border: 1px solid #2a3441;
            border-radius: 12px;
            overflow: hidden;
        }

        .panel-header {
            padding: 15px 20px;
            border-bottom: 1px solid #2a3441;
            font-size: 16px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .panel-body {
            padding: 0;
            max-height: 600px;
            overflow-y: auto;
        }

        /* Feed样式 */
        .feed-item {
            padding: 15px 20px;
            border-bottom: 1px solid #2a3441;
            transition: all 0.3s;
            position: relative;
        }

        .feed-item:hover {
            background: #1a2332;
        }

        .feed-item.new {
            animation: highlight 3s ease-out;
        }

        @keyframes highlight {
            0% { background: rgba(102, 126, 234, 0.3); }
            100% { background: transparent; }
        }

        .feed-item.high-risk { border-left: 3px solid #ff4757; }
        .feed-item.medium-risk { border-left: 3px solid #ffa502; }
        .feed-item.low-risk { border-left: 3px solid #2ed573; }

        .feed-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .feed-symbol {
            font-size: 18px;
            font-weight: 700;
            color: #fff;
        }

        .feed-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }

        .badge-high { background: rgba(255, 71, 87, 0.2); color: #ff4757; }
        .badge-medium { background: rgba(255, 165, 2, 0.2); color: #ffa502; }
        .badge-low { background: rgba(46, 213, 115, 0.2); color: #2ed573; }

        .feed-analysis {
            font-size: 13px;
            color: #aab7c4;
            line-height: 1.5;
            margin: 8px 0;
            padding: 10px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            border-left: 3px solid #667eea;
        }

        .feed-signals {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 8px;
        }

        .signal-tag {
            background: #2a3441;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            color: #8892a0;
        }

        .feed-time {
            font-size: 11px;
            color: #5a6672;
            margin-top: 8px;
        }

        /* 表格样式 */
        .data-table {
            width: 100%;
            border-collapse: collapse;
        }

        .data-table th {
            text-align: left;
            padding: 14px 16px;
            background: #0f1419;
            font-size: 12px;
            color: #8892a0;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .data-table td {
            padding: 14px 16px;
            border-bottom: 1px solid #2a3441;
            font-size: 13px;
        }

        .data-table tr:hover td {
            background: #1a2332;
        }

        .progress-bar {
            height: 6px;
            background: #2a3441;
            border-radius: 3px;
            overflow: hidden;
            width: 60px;
        }

        .progress-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s ease;
        }

        .progress-oi { background: #667eea; }
        .progress-funding { background: #ffa502; }
        .progress-volume { background: #2ed573; }

        /* 告警遮罩 */
        .alert-overlay {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .alert-toast {
            background: linear-gradient(145deg, #151b26 0%, #1a2332 100%);
            border: 1px solid #ff4757;
            border-left: 4px solid #ff4757;
            border-radius: 8px;
            padding: 15px 20px;
            min-width: 300px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
            animation: slideIn 0.3s ease;
        }

        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }

        .alert-toast .alert-title {
            font-weight: 700;
            color: #ff4757;
            margin-bottom: 5px;
        }

        .alert-toast .alert-content {
            font-size: 13px;
            color: #aab7c4;
        }

        .settings-panel {
            background: #151b26;
            border: 1px solid #2a3441;
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }

        .setting-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #2a3441;
        }

        .setting-row:last-child {
            border-bottom: none;
        }

        .setting-label {
            font-size: 14px;
        }

        .toggle {
            width: 50px;
            height: 26px;
            background: #2a3441;
            border-radius: 13px;
            position: relative;
            cursor: pointer;
            transition: background 0.3s;
        }

        .toggle.active {
            background: #667eea;
        }

        .toggle::after {
            content: '';
            position: absolute;
            width: 22px;
            height: 22px;
            background: #fff;
            border-radius: 50%;
            top: 2px;
            left: 2px;
            transition: transform 0.3s;
        }

        .toggle.active::after {
            transform: translateX(24px);
        }

        @media (max-width: 1200px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
            .stats-bar {
                grid-template-columns: repeat(2, 1fr);
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 币安期货主力出货/吸筹实时监控系统</h1>
        <div class="status">
            <div class="status-dot"></div>
            <span id="status-text">正在连接...</span>
            <span>|</span>
            <span id="last-update">等待数据</span>
        </div>
    </div>

    <div class="alert-overlay" id="alert-container"></div>

    <div class="container">
        <div class="stats-bar">
            <div class="stat-card">
                <div class="stat-value" id="stat-scanned">0</div>
                <div class="stat-label">监控币种总数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-anomalies">0</div>
                <div class="stat-label">异常币种发现</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-new">0</div>
                <div class="stat-label">本轮新发现</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="font-size: 28px;">15s</div>
                <div class="stat-label">更新间隔</div>
            </div>
        </div>

        <div class="main-grid">
            <div class="left-col">
                <div class="panel">
                    <div class="panel-header">🔍 实时发现 Feed</div>
                    <div class="panel-body" id="feed-container">
                        <div style="padding: 40px; text-align: center; color: #5a6672;">
                            等待数据...
                        </div>
                    </div>
                </div>

                <div class="settings-panel">
                    <h3 style="margin-bottom: 15px;">⚙️ 设置</h3>
                    <div class="setting-row">
                        <span class="setting-label">浏览器通知</span>
                        <div class="toggle" id="notify-toggle" onclick="toggleNotification()"></div>
                    </div>
                    <div class="setting-row">
                        <span class="setting-label">声音提醒</span>
                        <div class="toggle active" id="sound-toggle" onclick="toggleSound()"></div>
                    </div>
                    <div class="setting-row">
                        <span class="setting-label">最小评分阈值</span>
                        <span style="color: #667eea;">0.3</span>
                    </div>
                </div>
            </div>

            <div class="right-col">
                <div class="panel">
                    <div class="panel-header">📊 异常币种详细分析</div>
                    <div class="panel-body" style="max-height: 700px; overflow: auto;">
                        <table class="data-table">
                            <thead>
                                <tr>
                                    <th>排名</th>
                                    <th>币种</th>
                                    <th>评分</th>
                                    <th>OI</th>
                                    <th>资金费率</th>
                                    <th>成交量</th>
                                    <th>庄家行动判断</th>
                                </tr>
                            </thead>
                            <tbody id="table-body">
                                <tr>
                                    <td colspan="7" style="text-align: center; padding: 40px; color: #5a6672;">
                                        等待数据...
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let ws;
        let reconnectInterval;
        let soundEnabled = true;
        let notificationEnabled = false;

        // 连接WebSocket
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                console.log('✅ WebSocket连接成功');
                document.getElementById('status-text').textContent = '实时监控中';
                document.getElementById('status-text').style.color = '#00ff88';
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleMessage(data);
            };

            ws.onclose = () => {
                console.log('❌ WebSocket连接断开');
                document.getElementById('status-text').textContent = '连接断开，正在重连...';
                document.getElementById('status-text').style.color = '#ff4757';
                setTimeout(connect, 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket错误:', error);
            };
        }

        // 处理消息
        function handleMessage(data) {
            if (data.type === 'update') {
                updateDashboard(data);
            } else if (data.type === 'alert') {
                showAlert(data);
            } else if (data.type === 'connected') {
                console.log(data.message);
            }
        }

        // 更新面板
        function updateDashboard(data) {
            // 更新统计
            document.getElementById('stat-scanned').textContent = data.total_scanned;
            document.getElementById('stat-anomalies').textContent = data.anomalies_count;
            document.getElementById('stat-new').textContent = data.new_count;
            document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

            // 更新Feed
            const feedContainer = document.getElementById('feed-container');
            feedContainer.innerHTML = '';

            data.anomalies.forEach((item, index) => {
                const riskClass = item.score >= 0.7 ? 'high-risk' : item.score >= 0.5 ? 'medium-risk' : 'low-risk';
                const badgeClass = item.score >= 0.7 ? 'badge-high' : item.score >= 0.5 ? 'badge-medium' : 'badge-low';
                const isNew = item.is_new ? 'new' : '';

                const signalsHtml = item.signals.map(s => `<span class="signal-tag">${s}</span>`).join('');

                const feedItem = document.createElement('div');
                feedItem.className = `feed-item ${riskClass} ${isNew}`;
                feedItem.innerHTML = `
                    <div class="feed-header">
                        <span class="feed-symbol">${item.symbol}</span>
                        <span class="feed-badge ${badgeClass}">${item.score}</span>
                    </div>
                    <div class="feed-analysis">${item.analysis}</div>
                    <div class="feed-signals">${signalsHtml}</div>
                `;
                feedContainer.appendChild(feedItem);
            });

            // 更新表格
            const tableBody = document.getElementById('table-body');
            tableBody.innerHTML = '';

            data.anomalies.forEach((item, index) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${index + 1}</td>
                    <td><strong>${item.symbol}</strong></td>
                    <td>
                        <span class="feed-badge ${item.score >= 0.7 ? 'badge-high' : item.score >= 0.5 ? 'badge-medium' : 'badge-low'}">
                            ${item.score}
                        </span>
                    </td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill progress-oi" style="width: ${Math.min(item.components.oi_change * 100, 100)}%"></div>
                        </div>
                    </td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill progress-funding" style="width: ${Math.min(item.components.funding * 100, 100)}%"></div>
                        </div>
                    </td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill progress-volume" style="width: ${Math.min(item.components.volume * 100, 100)}%"></div>
                        </div>
                    </td>
                    <td style="max-width: 300px; font-size: 12px; color: #aab7c4;">${item.analysis}</td>
                `;
                tableBody.appendChild(row);
            });
        }

        // 显示告警
        function showAlert(data) {
            // 前端弹窗
            const container = document.getElementById('alert-container');
            const toast = document.createElement('div');
            toast.className = 'alert-toast';
            toast.innerHTML = `
                <div class="alert-title">🚨 新信号: ${data.symbol}</div>
                <div class="alert-content">${data.analysis}</div>
            `;
            container.appendChild(toast);

            // 声音提醒
            if (soundEnabled) {
                playAlertSound();
            }

            // 浏览器通知
            if (notificationEnabled && Notification.permission === 'granted') {
                new Notification('币安期货监控 - 新信号', {
                    body: `${data.symbol}: ${data.analysis}`,
                    icon: '🔔'
                });
            }

            // 3秒后移除
            setTimeout(() => {
                toast.remove();
            }, 5000);
        }

        // 播放提醒音
        function playAlertSound() {
            const audio = new Audio();
            audio.src = 'data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBTGH0fPTgjMGHm7A7+OZURE'; // 简短提示音
            audio.volume = 0.5;
            audio.play().catch(() => {});
        }

        // 切换通知
        async function toggleNotification() {
            const toggle = document.getElementById('notify-toggle');

            if (!notificationEnabled) {
                const permission = await Notification.requestPermission();
                if (permission === 'granted') {
                    notificationEnabled = true;
                    toggle.classList.add('active');
                }
            } else {
                notificationEnabled = false;
                toggle.classList.remove('active');
            }
        }

        // 切换声音
        function toggleSound() {
            const toggle = document.getElementById('sound-toggle');
            soundEnabled = !soundEnabled;
            toggle.classList.toggle('active');
        }

        // 启动
        connect();

        // 心跳
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({action: 'ping'}));
            }
        }, 30000);
    </script>
</body>
</html>
'''

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 启动实时监控系统")
    print("=" * 60)
    print("\n📱 访问地址:")
    print("   http://localhost:8080")
    print("\n功能:")
    print("   ✓ 每15秒自动扫描全市场")
    print("   ✓ WebSocket实时推送数据")
    print("   ✓ 新币种浏览器通知")
    print("   ✓ 智能分析庄家行为")
    print("\n按 Ctrl+C 停止\n")

    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="warning")
