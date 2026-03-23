"""
Streamlit实时监控面板 - 支持自动发现模式
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import config
from data.binance_client import BinanceAPIClient
from data.screener import MarketScreener, ScreeningCriteria, AnomalyScore
from signals.calculator import SignalCalculator
from alert.manager import AlertManager

# 页面配置
st.set_page_config(
    page_title="币安期货主力监控",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化
client = BinanceAPIClient()
calculator = SignalCalculator()
alert_manager = AlertManager()

# 初始化screener (用于自动发现模式)
screener = MarketScreener(
    client=client,
    criteria=ScreeningCriteria(
        min_oi_change_percent=config.SCREEN_OI_THRESHOLD,
        min_funding_rate=config.SCREEN_FUNDING_THRESHOLD,
        min_price_change_24h=config.SCREEN_PRICE_CHANGE_THRESHOLD,
        exclude_symbols=set(config.SCREEN_EXCLUDE_SYMBOLS or [])
    )
)

# 会话状态
if 'signal_history' not in st.session_state:
    st.session_state.signal_history = {}

if 'price_history' not in st.session_state:
    st.session_state.price_history = {}

if 'alerts' not in st.session_state:
    st.session_state.alerts = []

if 'last_update' not in st.session_state:
    st.session_state.last_update = datetime.min

if 'discovery_mode' not in st.session_state:
    st.session_state.discovery_mode = True  # 默认启用自动发现

if 'screened_candidates' not in st.session_state:
    st.session_state.screened_candidates = []

if 'discovery_feed' not in st.session_state:
    st.session_state.discovery_feed = []

if 'manual_symbols' not in st.session_state:
    st.session_state.manual_symbols = list(config.SYMBOLS)


class DashboardData:
    """面板数据管理"""

    @staticmethod
    @st.cache_data(ttl=30)
    def fetch_market_data(symbols: tuple) -> Dict[str, Any]:
        """获取市场数据"""
        async def _fetch():
            tasks = [client.get_all_market_data(s) for s in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            data = {}
            for symbol, result in zip(symbols, results):
                if not isinstance(result, Exception):
                    data[symbol] = result
            return data

        return asyncio.run(_fetch())

    @staticmethod
    def run_light_scan(min_score: float = 0.3, top_n: int = 20) -> List[AnomalyScore]:
        """运行全量筛选"""
        async def _scan():
            return await screener.get_candidates_for_deep_scan(min_score=min_score, top_n=top_n)

        candidates = asyncio.run(_scan())

        # 获取完整的AnomalyScore对象
        snapshots = asyncio.run(screener.get_all_snapshots())
        anomalies = screener.screen_anomalies(snapshots, min_score=min_score)

        return [a for a in anomalies if a.symbol in candidates]

    @staticmethod
    def update_history(symbol: str, signal_data: Dict):
        """更新历史数据"""
        if symbol not in st.session_state.signal_history:
            st.session_state.signal_history[symbol] = []

        st.session_state.signal_history[symbol].append({
            'timestamp': datetime.now(),
            'data': signal_data
        })

        # 限制历史数据大小
        max_size = 200
        if len(st.session_state.signal_history[symbol]) > max_size:
            st.session_state.signal_history[symbol] = \
                st.session_state.signal_history[symbol][-max_size:]

    @staticmethod
    def add_to_discovery_feed(anomaly: AnomalyScore):
        """添加异常发现到feed"""
        feed_item = {
            'timestamp': datetime.now(),
            'symbol': anomaly.symbol,
            'score': anomaly.total_score,
            'signals': anomaly.signals,
            'components': anomaly.components
        }

        # 检查是否已存在
        existing = [f for f in st.session_state.discovery_feed if f['symbol'] == anomaly.symbol]
        if not existing:
            st.session_state.discovery_feed.insert(0, feed_item)

        # 限制feed大小
        if len(st.session_state.discovery_feed) > 50:
            st.session_state.discovery_feed = st.session_state.discovery_feed[:50]


def render_header():
    """渲染头部"""
    st.title("📊 币安期货主力出货/吸筹监控系统")
    st.markdown("---")


def render_sidebar():
    """渲染侧边栏 - 支持自动发现模式"""
    with st.sidebar:
        st.header("⚙️ 监控设置")

        # 模式切换
        st.subheader("监控模式")
        mode_col1, mode_col2 = st.columns(2)

        with mode_col1:
            if st.button(
                "🔍 自动发现",
                type="primary" if st.session_state.discovery_mode else "secondary",
                use_container_width=True
            ):
                st.session_state.discovery_mode = True
                st.rerun()

        with mode_col2:
            if st.button(
                "📋 定向监控",
                type="primary" if not st.session_state.discovery_mode else "secondary",
                use_container_width=True
            ):
                st.session_state.discovery_mode = False
                st.rerun()

        st.markdown("---")

        # 根据模式显示不同配置
        if st.session_state.discovery_mode:
            # ========== 自动发现模式配置 ==========
            st.subheader("🔍 自动发现配置")

            # 筛选阈值
            st.markdown("**筛选阈值**")

            screen_oi_threshold = st.slider(
                "OI变化率阈值 (%)",
                min_value=1.0,
                max_value=20.0,
                value=config.SCREEN_OI_THRESHOLD,
                help="持仓量变化率超过此值被视为异常"
            )

            screen_funding_threshold = st.slider(
                "资金费率阈值 (%)",
                min_value=0.01,
                max_value=0.5,
                value=config.SCREEN_FUNDING_THRESHOLD,
                format="%.2f",
                help="资金费率绝对值超过此值被视为异常"
            )

            screen_price_threshold = st.slider(
                "价格变化阈值 (%)",
                min_value=1.0,
                max_value=20.0,
                value=config.SCREEN_PRICE_CHANGE_THRESHOLD,
                help="24h价格变化超过此值被视为异常"
            )

            min_score = st.slider(
                "最小异常评分",
                min_value=0.0,
                max_value=1.0,
                value=0.3,
                format="%.2f",
                help="综合评分超过此值才显示"
            )

            top_n = st.slider(
                "最大候选数",
                min_value=5,
                max_value=50,
                value=20,
                help="每轮最多显示多少个候选币种"
            )

            st.markdown("---")

            # 运行筛选按钮
            if st.button("🚀 立即扫描全市场", use_container_width=True):
                with st.spinner("正在扫描全市场 (~300币种)..."):
                    anomalies = DashboardData.run_light_scan(min_score=min_score, top_n=top_n)
                    st.session_state.screened_candidates = [a.symbol for a in anomalies]
                    for anomaly in anomalies:
                        DashboardData.add_to_discovery_feed(anomaly)
                st.success(f"发现 {len(anomalies)} 个异常币种")
                st.rerun()

            selected_symbols = st.session_state.screened_candidates

        else:
            # ========== 定向监控模式配置 ==========
            st.subheader("📋 定向监控配置")

            # 交易对选择
            selected_symbols = st.multiselect(
                "监控交易对",
                options=st.session_state.manual_symbols,
                default=st.session_state.manual_symbols[:4]
            )

            # 信号阈值设置
            st.subheader("信号阈值")
            oi_threshold = st.slider(
                "OI变化阈值 (%)",
                min_value=1.0,
                max_value=20.0,
                value=config.OI_CHANGE_THRESHOLD
            )

            funding_threshold = st.slider(
                "资金费率阈值 (%)",
                min_value=0.001,
                max_value=0.1,
                value=config.FUNDING_RATE_THRESHOLD,
                format="%.4f"
            )

            basis_threshold = st.slider(
                "期现价差阈值 (%)",
                min_value=0.01,
                max_value=1.0,
                value=config.BASIS_THRESHOLD
            )

        # 公共按钮
        st.markdown("---")
        if st.button("🔄 立即刷新", use_container_width=True):
            st.rerun()

        st.markdown("---")
        st.markdown("### 📈 信号说明")

        if st.session_state.discovery_mode:
            st.markdown("""
            **自动发现模式**
            - 🔍 扫描全市场 ~300个币种
            - ⚡ 两层扫描策略：Light Scan + Deep Scan
            - 📊 多因子异常检测
            - 🔔 自动发现小币种机会
            """)
        else:
            st.markdown("""
            **定向监控模式**
            - 🚨 **出货信号**: OI增长 + 资金费率负
            - 💎 **吸筹信号**: OI增长 + 资金费率正
            - 多因子验证，避免单一指标误导
            """)

    # 返回配置值
    if st.session_state.discovery_mode:
        return selected_symbols, screen_oi_threshold, screen_funding_threshold, min_score, top_n
    else:
        return selected_symbols, oi_threshold, funding_threshold, basis_threshold, None


def render_signal_cards(signals: List[Dict]):
    """渲染信号卡片"""
    if not signals:
        st.info("暂无信号数据")
        return

    cols = st.columns(min(len(signals), 4))

    for idx, signal in enumerate(signals[:4]):
        with cols[idx % 4]:
            symbol = signal.get('symbol', 'Unknown')
            signal_type = signal.get('signal_type', 'none')
            strength = signal.get('signal_strength', 0)
            confidence = signal.get('confidence', 'none')

            # 根据信号类型设置颜色
            if signal_type == 'distribution':
                color = "#ff4b4b"
                emoji = "🚨"
                label = "出货"
            elif signal_type == 'accumulation':
                color = "#00cc66"
                emoji = "💎"
                label = "吸筹"
            else:
                color = "#888888"
                emoji = "➖"
                label = "无信号"

            # 置信度指示
            conf_emoji = {
                'strong': '🔴',
                'medium': '🟡',
                'weak': '🟢',
                'none': '⚪'
            }.get(confidence, '⚪')

            st.markdown(f"""
            <div style="
                padding: 15px;
                border-radius: 10px;
                border-left: 5px solid {color};
                background-color: rgba({','.join(str(int(int(color[i:i+2], 16) * 0.1)) for i in (1, 3, 5))}, 0.1);
            ">
                <h3 style="margin: 0; color: {color};">{emoji} {symbol}</h3>
                <p style="margin: 5px 0; font-size: 18px; font-weight: bold;">
                    {label} {conf_emoji} {confidence.upper()}
                </p>
                <div style="background: #333; border-radius: 5px; height: 8px;">
                    <div style="
                        background: {color};
                        width: {strength * 100}%;
                        height: 100%;
                        border-radius: 5px;
                    "></div>
                </div>
                <p style="margin: 5px 0; text-align: center; font-size: 12px;">
                    强度: {strength:.1%}
                </p>
            </div>
            """, unsafe_allow_html=True)


def render_oi_chart(symbol: str, history: List[Dict]):
    """渲染OI变化图表"""
    if not history or len(history) < 2:
        return

    df = pd.DataFrame([
        {
            'time': h['timestamp'],
            'OI': float(h['data'].get('open_interest', {}).get('openInterest', 0))
        }
        for h in history
    ])

    fig = px.line(
        df,
        x='time',
        y='OI',
        title=f"{symbol} - 持仓量(OI)变化趋势",
        labels={'time': '时间', 'OI': '持仓量'}
    )
    fig.update_layout(
        height=300,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)


def render_funding_heatmap(symbols: List[str]):
    """渲染资金费率热力图"""
    async def fetch_funding():
        tasks = [client.get_funding_rate(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = []
        for symbol, result in zip(symbols, results):
            if not isinstance(result, Exception):
                data.append({
                    'symbol': symbol,
                    'funding_rate': float(result.get('lastFundingRate', 0)) * 100
                })
        return data

    funding_data = asyncio.run(fetch_funding())

    if not funding_data:
        return

    df = pd.DataFrame(funding_data)

    fig = px.bar(
        df,
        x='symbol',
        y='funding_rate',
        title="资金费率对比 (%)",
        color='funding_rate',
        color_continuous_scale=['red', 'white', 'green'],
        color_continuous_midpoint=0
    )
    fig.update_layout(height=300)
    st.plotly_chart(fig, use_container_width=True)


def render_signal_gauge(signal_data: Dict):
    """渲染信号强度仪表盘"""
    strength = signal_data.get('signal_strength', 0)
    signal_type = signal_data.get('signal_type', 'none')

    if signal_type == 'distribution':
        title = "出货信号强度"
        color = "red"
    elif signal_type == 'accumulation':
        title = "吸筹信号强度"
        color = "green"
    else:
        title = "信号强度"
        color = "gray"

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=strength * 100,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': title},
        gauge={
            'axis': {'range': [None, 100]},
            'bar': {'color': color},
            'steps': [
                {'range': [0, 30], 'color': "lightgray"},
                {'range': [30, 50], 'color': "yellow"},
                {'range': [50, 70], 'color': "orange"},
                {'range': [70, 100], 'color': "red" if signal_type == 'distribution' else "green"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': strength * 100
            }
        }
    ))
    fig.update_layout(height=300)
    st.plotly_chart(fig, use_container_width=True)


def render_alerts_table():
    """渲染告警列表"""
    st.subheader("🔔 最近告警")

    alerts = st.session_state.alerts[-20:]  # 最近20条

    if not alerts:
        st.info("暂无告警")
        return

    df = pd.DataFrame([
        {
            '时间': a['timestamp'].strftime('%H:%M:%S'),
            '交易对': a['symbol'],
            '类型': '出货' if a['type'] == 'distribution' else '吸筹',
            '强度': f"{a['strength']:.1%}",
            '置信度': a['confidence']
        }
        for a in reversed(alerts)
    ])

    st.dataframe(df, use_container_width=True, hide_index=True)


def render_discovery_feed():
    """渲染发现Feed - 类似Twitter时间线"""
    st.subheader("🔍 实时发现Feed")

    feed = st.session_state.discovery_feed[:20]  # 最近20条

    if not feed:
        st.info("暂无发现数据，点击侧边栏的 '🚀 立即扫描全市场' 开始扫描")
        return

    for item in feed:
        time_ago = (datetime.now() - item['timestamp']).seconds
        if time_ago < 60:
            time_str = f"{time_ago}秒前"
        elif time_ago < 3600:
            time_str = f"{time_ago // 60}分钟前"
        else:
            time_str = f"{time_ago // 3600}小时前"

        # 根据评分设置颜色
        score = item['score']
        if score >= 0.7:
            border_color = "#ff4b4b"
            bg_color = "rgba(255, 75, 75, 0.05)"
        elif score >= 0.5:
            border_color = "#ffa500"
            bg_color = "rgba(255, 165, 0, 0.05)"
        else:
            border_color = "#00cc66"
            bg_color = "rgba(0, 204, 102, 0.05)"

        # 信号标签
        signal_tags = ""
        for signal in item['signals'][:3]:  # 只显示前3个信号
            signal_tags += f'<span style="background: #333; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-right: 5px;">{signal}</span>'

        st.markdown(f"""
        <div style="
            padding: 12px 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 4px solid {border_color};
            background-color: {bg_color};
        ">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 18px; font-weight: bold;">{item['symbol']}</span>
                    <span style="font-size: 14px; color: #888; margin-left: 10px;">评分: {score:.2f}</span>
                </div>
                <span style="font-size: 12px; color: #666;">{time_str}</span>
            </div>
            <div style="margin-top: 8px;">
                {signal_tags}
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_anomaly_details(anomalies: List[AnomalyScore]):
    """渲染异常详情表格"""
    st.subheader("📊 异常币种详情")

    if not anomalies:
        st.info("暂无异常数据")
        return

    rows = []
    for anomaly in anomalies:
        rows.append({
            '币种': anomaly.symbol,
            '综合评分': f"{anomaly.total_score:.2f}",
            'OI因子': f"{anomaly.components.get('oi_change', 0):.2f}",
            '资金费率': f"{anomaly.components.get('funding', 0):.2f}",
            '成交量': f"{anomaly.components.get('volume', 0):.2f}",
            '波动率': f"{anomaly.components.get('volatility', 0):.2f}",
            '信号数': len(anomaly.signals)
        })

    df = pd.DataFrame(rows)

    # 使用颜色映射
    def highlight_score(val):
        try:
            score = float(val)
            if score >= 0.7:
                return 'background-color: rgba(255, 75, 75, 0.3)'
            elif score >= 0.5:
                return 'background-color: rgba(255, 165, 0, 0.3)'
            elif score >= 0.3:
                return 'background-color: rgba(0, 204, 102, 0.3)'
        except:
            pass
        return ''

    styled_df = df.style.applymap(highlight_score, subset=['综合评分'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)


def render_metrics_table(market_data: Dict[str, Any]):
    """渲染指标表格"""
    st.subheader("📋 详细指标")

    rows = []
    for symbol, data in market_data.items():
        oi = data.get('open_interest') or {}
        funding = data.get('funding_rate') or {}
        price = data.get('mark_price') or {}
        ratio = data.get('long_short_ratio') or {}

        rows.append({
            '交易对': symbol,
            '持仓量': f"{float(oi.get('openInterest', 0)):,.0f}",
            '标记价格': f"${float(price.get('markPrice', 0)):,.2f}",
            '资金费率': f"{float(funding.get('lastFundingRate', 0)):.4%}",
            '多空比': f"{float(ratio.get('longShortRatio', 0)):.2f}" if ratio else "N/A",
            '预测资金费': f"{float(funding.get('estimatedSettlePrice', 0)):,.2f}" if funding else "N/A"
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def main():
    """主函数 - 支持自动发现和定向监控两种模式"""
    render_header()

    # 获取侧边栏配置
    sidebar_result = render_sidebar()
    selected_symbols = sidebar_result[0]

    # 自动发现模式
    is_discovery_mode = st.session_state.discovery_mode

    if is_discovery_mode:
        # ========== 自动发现模式 ==========
        screen_oi_threshold, screen_funding_threshold, min_score, top_n = sidebar_result[1:]

        # 显示模式标签
        st.markdown("""
        <div style="
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            padding: 10px 20px;
            border-radius: 20px;
            display: inline-block;
            margin-bottom: 20px;
        ">
            <span style="color: white; font-weight: bold;">🔍 自动发现模式 - 扫描全市场异常</span>
        </div>
        """, unsafe_allow_html=True)

        # 两列布局
        col1, col2 = st.columns([1, 2])

        with col1:
            # 发现Feed
            render_discovery_feed()

            # 告警列表
            render_alerts_table()

        with col2:
            # 如果有候选币种，显示详情
            if selected_symbols:
                st.success(f"当前监控 {len(selected_symbols)} 个候选币种")

                # 获取详细数据
                with st.spinner("获取详细数据中..."):
                    market_data = DashboardData.fetch_market_data(tuple(selected_symbols))

                if market_data:
                    # 显示异常详情
                    anomalies = DashboardData.run_light_scan(min_score=min_score, top_n=top_n)
                    render_anomaly_details(anomalies)

                    # 显示指标表格
                    render_metrics_table(market_data)

                    # 显示资金费率热力图
                    render_funding_heatmap(selected_symbols[:10])
                else:
                    st.warning("无法获取详细数据")
            else:
                st.info("👈 点击侧边栏的 '🚀 立即扫描全市场' 发现异常币种")

                # 显示示例说明
                with st.expander("📖 如何使用自动发现模式"):
                    st.markdown("""
                    ### 自动发现模式使用指南

                    **1. 设置筛选阈值**
                    - OI变化率: 持仓量异常增长的阈值
                    - 资金费率: 资金费率异常的阈值
                    - 价格变化: 24h价格波动的阈值
                    - 最小评分: 综合异常评分的阈值

                    **2. 点击"立即扫描全市场"**
                    - 系统会扫描~300个USDT合约
                    - 使用两层扫描策略: Light Scan + Deep Scan
                    - 仅2个API调用完成全量筛选

                    **3. 查看发现Feed**
                    - 异常币种以时间线形式展示
                    - 颜色编码: 红色=高异常, 橙色=中等, 绿色=低异常
                    - 点击刷新可更新数据

                    **4. 深度分析**
                    - 对候选币种获取完整数据
                    - 计算多因子信号
                    - 触发告警通知
                    """)

    else:
        # ========== 定向监控模式 ==========
        oi_th, fund_th, basis_th, _ = sidebar_result[1:]

        if not selected_symbols:
            st.warning("请至少选择一个交易对")
            return

        # 显示模式标签
        st.markdown("""
        <div style="
            background: linear-gradient(90deg, #11998e 0%, #38ef7d 100%);
            padding: 10px 20px;
            border-radius: 20px;
            display: inline-block;
            margin-bottom: 20px;
        ">
            <span style="color: white; font-weight: bold;">📋 定向监控模式</span>
        </div>
        """, unsafe_allow_html=True)

        # 获取数据
        with st.spinner("获取数据中..."):
            market_data = DashboardData.fetch_market_data(tuple(selected_symbols))

        if not market_data:
            st.error("无法获取数据，请检查网络连接")
            return

        # 处理信号
        signals = []
        for symbol, data in market_data.items():
            DashboardData.update_history(symbol, data)

            # 简化的信号数据
            signal = {
                'symbol': symbol,
                'signal_type': 'none',
                'signal_strength': 0,
                'confidence': 'none'
            }

            # 计算信号
            oi_change = 0
            history = st.session_state.signal_history.get(symbol, [])
            if len(history) >= 2:
                current_oi = float((data.get('open_interest') or {}).get('openInterest', 0))
                prev_data = history[-2]['data'] or {}
                prev_oi_raw = (prev_data.get('open_interest') or {}).get('openInterest', current_oi)
                prev_oi = float(prev_oi_raw if prev_oi_raw is not None else current_oi)
                if prev_oi > 0:
                    oi_change = (current_oi - prev_oi) / prev_oi * 100

            funding_rate = float((data.get('funding_rate') or {}).get('lastFundingRate', 0))
            mark_price = float((data.get('mark_price') or {}).get('markPrice', 0))
            spot_price_data = data.get('spot_price') or {}
            spot_price = float(spot_price_data.get('price', mark_price) if spot_price_data else mark_price)
            basis_rate = (mark_price - spot_price) / spot_price * 100 if spot_price > 0 else 0

            # 判断信号
            if oi_change > oi_th:
                if funding_rate < -fund_th or basis_rate < -basis_th:
                    signal['signal_type'] = 'distribution'
                elif funding_rate > fund_th or basis_rate > basis_th:
                    signal['signal_type'] = 'accumulation'

                # 计算强度
                oi_score = min(oi_change / (oi_th * 2), 1.0)
                funding_score = min(abs(funding_rate) / (fund_th * 2), 1.0)
                basis_score = min(abs(basis_rate) / (basis_th * 2), 1.0)

                signal['signal_strength'] = (oi_score + funding_score + basis_score) / 3

                if signal['signal_strength'] > 0.7:
                    signal['confidence'] = 'strong'
                elif signal['signal_strength'] > 0.5:
                    signal['confidence'] = 'medium'
                else:
                    signal['confidence'] = 'weak'

            signals.append(signal)

        # 主内容区
        st.subheader("📊 实时信号监控")
        render_signal_cards(signals)

        # 详细分析区
        col1, col2 = st.columns(2)

        with col1:
            # 选择交易对查看详情
            detail_symbol = st.selectbox(
                "选择交易对查看详情",
                options=selected_symbols
            )

            if detail_symbol:
                history = st.session_state.signal_history.get(detail_symbol, [])

                # 信号仪表盘
                signal_for_symbol = next(
                    (s for s in signals if s['symbol'] == detail_symbol),
                    None
                )
                if signal_for_symbol:
                    render_signal_gauge(signal_for_symbol)

                # OI图表
                render_oi_chart(detail_symbol, history)

        with col2:
            # 资金费率热力图
            render_funding_heatmap(selected_symbols)

        # 告警和指标表格
        col3, col4 = st.columns([1, 2])

        with col3:
            render_alerts_table()

        with col4:
            render_metrics_table(market_data)

    # 自动刷新
    st.session_state.last_update = datetime.now()
    st.caption(f"最后更新: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')}")

    # 自动刷新
    st_autorefresh = st.empty()
    st_autorefresh.markdown(
        """<meta http-equiv="refresh" content="30">""",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
