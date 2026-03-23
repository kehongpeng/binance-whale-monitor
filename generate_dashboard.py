"""
生成前端可视化界面报告
展示自动发现模式的Web界面效果
"""
import asyncio
import sys
sys.path.insert(0, '.')

from data.screener import MarketScreener, ScreeningCriteria, AnomalyScore
from data.binance_client import BinanceAPIClient
from datetime import datetime

async def generate_html_report():
    """生成HTML格式的可视化报告"""

    # 获取数据
    client = BinanceAPIClient()
    screener = MarketScreener(client=client)

    print("🔄 正在获取全市场数据...")
    snapshots = await screener.get_all_snapshots()
    anomalies = screener.screen_anomalies(snapshots, min_score=0.3)

    # 生成HTML
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>币安期货主力出货监控系统 - 自动发现模式</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #e6edf3;
            line-height: 1.6;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 30px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .header .subtitle {{
            opacity: 0.9;
            font-size: 14px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}
        .mode-badge {{
            display: inline-block;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            padding: 10px 20px;
            border-radius: 20px;
            font-weight: bold;
            margin: 20px 0;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            transition: transform 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-2px);
            border-color: #667eea;
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }}
        .stat-label {{
            font-size: 12px;
            color: #8b949e;
            margin-top: 5px;
        }}
        .two-column {{
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 20px;
            margin: 20px 0;
        }}
        @media (max-width: 768px) {{
            .two-column {{
                grid-template-columns: 1fr;
            }}
        }}
        .panel {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
        }}
        .panel h2 {{
            font-size: 18px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .feed-item {{
            background: rgba(102, 126, 234, 0.05);
            border-left: 4px solid;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 0 8px 8px 0;
            transition: all 0.2s;
        }}
        .feed-item:hover {{
            background: rgba(102, 126, 234, 0.1);
        }}
        .feed-item.high-risk {{
            border-color: #ff4b4b;
        }}
        .feed-item.medium-risk {{
            border-color: #ffa500;
        }}
        .feed-item.low-risk {{
            border-color: #00cc66;
        }}
        .feed-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .feed-symbol {{
            font-size: 18px;
            font-weight: bold;
        }}
        .feed-score {{
            font-size: 14px;
            color: #8b949e;
        }}
        .feed-signals {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 8px;
        }}
        .signal-tag {{
            background: #30363d;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
        }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .data-table th {{
            text-align: left;
            padding: 12px;
            background: #0d1117;
            font-size: 12px;
            color: #8b949e;
            text-transform: uppercase;
        }}
        .data-table td {{
            padding: 12px;
            border-bottom: 1px solid #30363d;
        }}
        .data-table tr:hover td {{
            background: rgba(102, 126, 234, 0.05);
        }}
        .score-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 12px;
        }}
        .score-high {{
            background: rgba(255, 75, 75, 0.2);
            color: #ff4b4b;
        }}
        .score-medium {{
            background: rgba(255, 165, 0, 0.2);
            color: #ffa500;
        }}
        .score-low {{
            background: rgba(0, 204, 102, 0.2);
            color: #00cc66;
        }}
        .progress-bar {{
            height: 6px;
            background: #30363d;
            border-radius: 3px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #8b949e;
            font-size: 12px;
            border-top: 1px solid #30363d;
            margin-top: 40px;
        }}
        .sidebar {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .sidebar h3 {{
            font-size: 14px;
            margin-bottom: 15px;
            color: #8b949e;
        }}
        .slider-control {{
            margin-bottom: 20px;
        }}
        .slider-label {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            margin-bottom: 5px;
        }}
        .slider {{
            width: 100%;
            height: 6px;
            background: #30363d;
            border-radius: 3px;
            position: relative;
        }}
        .slider-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            border-radius: 3px;
            width: 50%;
        }}
        .btn {{
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            width: 100%;
            font-weight: bold;
            transition: opacity 0.2s;
        }}
        .btn:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 币安期货主力出货/吸筹监控系统</h1>
        <div class="subtitle">自动发现全市场异常信号 · 实时多因子分析</div>
    </div>

    <div class="container">
        <div class="mode-badge">🔍 自动发现模式 - 扫描全市场异常</div>

        <!-- 统计卡片 -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{len(snapshots)}</div>
                <div class="stat-label">监控币种总数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(anomalies)}</div>
                <div class="stat-label">异常币种发现</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len([a for a in anomalies if a.total_score >= 0.5])}</div>
                <div class="stat-label">高风险信号</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">2</div>
                <div class="stat-label">API调用/轮</div>
            </div>
        </div>

        <div class="two-column">
            <!-- 左列：发现Feed -->
            <div>
                <div class="panel">
                    <h2>🔍 实时发现 Feed</h2>
"""

    # 添加Feed项
    for i, a in enumerate(anomalies[:10], 1):
        risk_class = "high-risk" if a.total_score >= 0.7 else "medium-risk" if a.total_score >= 0.5 else "low-risk"
        signals_html = "".join([f'<span class="signal-tag">{s[:30]}</span>' for s in a.signals[:3]])

        html += f"""
                    <div class="feed-item {risk_class}">
                        <div class="feed-header">
                            <span class="feed-symbol">{a.symbol}</span>
                            <span class="feed-score">评分: {a.total_score:.2f}</span>
                        </div>
                        <div class="feed-signals">{signals_html}</div>
                    </div>
"""

    html += """
                </div>

                <!-- 侧边栏配置 -->
                <div class="sidebar" style="margin-top: 20px;">
                    <h3>⚙️ 筛选配置</h3>

                    <div class="slider-control">
                        <div class="slider-label">
                            <span>OI变化率阈值</span>
                            <span>5.0%</span>
                        </div>
                        <div class="slider"><div class="slider-fill" style="width: 25%"></div></div>
                    </div>

                    <div class="slider-control">
                        <div class="slider-label">
                            <span>资金费率阈值</span>
                            <span>0.05%</span>
                        </div>
                        <div class="slider"><div class="slider-fill" style="width: 10%"></div></div>
                    </div>

                    <div class="slider-control">
                        <div class="slider-label">
                            <span>最小异常评分</span>
                            <span>0.30</span>
                        </div>
                        <div class="slider"><div class="slider-fill" style="width: 30%"></div></div>
                    </div>

                    <button class="btn">🚀 立即扫描全市场</button>
                </div>
            </div>

            <!-- 右列：详细数据 -->
            <div>
                <div class="panel">
                    <h2>📊 异常币种详情</h2>
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>排名</th>
                                <th>币种</th>
                                <th>综合评分</th>
                                <th>OI因子</th>
                                <th>资金费率</th>
                                <th>成交量</th>
                                <th>波动率</th>
                            </tr>
                        </thead>
                        <tbody>
"""

    # 添加表格行
    for i, a in enumerate(anomalies[:20], 1):
        score_class = "score-high" if a.total_score >= 0.7 else "score-medium" if a.total_score >= 0.5 else "score-low"
        oi = a.components.get('oi_change', 0)
        funding = a.components.get('funding', 0)
        volume = a.components.get('volume', 0)
        volatility = a.components.get('volatility', 0)

        html += f"""
                            <tr>
                                <td>{i}</td>
                                <td><strong>{a.symbol}</strong></td>
                                <td><span class="score-badge {score_class}">{a.total_score:.2f}</span></td>
                                <td>
                                    <div class="progress-bar">
                                        <div class="progress-fill" style="width: {min(oi*100, 100)}%; background: #667eea;"></div>
                                    </div>
                                </td>
                                <td>
                                    <div class="progress-bar">
                                        <div class="progress-fill" style="width: {min(funding*100, 100)}%; background: #ffa500;"></div>
                                    </div>
                                </td>
                                <td>
                                    <div class="progress-bar">
                                        <div class="progress-fill" style="width: {min(volume*100, 100)}%; background: #00cc66;"></div>
                                    </div>
                                </td>
                                <td>
                                    <div class="progress-bar">
                                        <div class="progress-fill" style="width: {min(volatility*100, 100)}%; background: #ff4b4b;"></div>
                                    </div>
                                </td>
                            </tr>
"""

    html += f"""
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="footer">
            <p>币安期货主力出货监控系统 v2.0 | 自动发现模式 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>扫描范围: {len(snapshots)} 个USDT合约 | 发现异常: {len(anomalies)} 个币种</p>
        </div>
    </div>
</body>
</html>
"""

    # 保存HTML文件
    with open('dashboard_report.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ HTML报告已生成: dashboard_report.html")
    print(f"📊 数据概览:")
    print(f"   - 监控币种: {len(snapshots)}")
    print(f"   - 异常发现: {len(anomalies)}")
    print(f"   - 高风险: {len([a for a in anomalies if a.total_score >= 0.5])}")
    print(f"   - 低风险: {len([a for a in anomalies if a.total_score < 0.5])}")

if __name__ == "__main__":
    asyncio.run(generate_html_report())
