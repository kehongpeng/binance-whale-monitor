"""
币安期货主力出货/吸筹监控系统 - 主程序入口
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

from config import config
from data.binance_client import BinanceAPIClient
from data.websocket_client import BinanceWebSocketClient
from data.screener import MarketScreener, SymbolQueue, ScreeningCriteria
from signals.calculator import SignalCalculator
from alert.manager import AlertManager, AlertConfig

# 配置日志
def setup_logging():
    """设置日志"""
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE, encoding='utf-8')
        ]
    )


class WhaleMonitor:
    """主力监控主类 - 支持自动发现模式"""

    def __init__(self, mode: str = 'auto'):
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.mode = mode  # 'auto' 或 'manual'

        # 初始化组件
        self.client = BinanceAPIClient()
        self.ws_client = BinanceWebSocketClient()
        self.calculator = SignalCalculator()
        self.alert_manager = AlertManager(
            AlertConfig(
                enabled=True,
                min_confidence='weak',
                console_enabled=True
            )
        )

        # 自动发现模式组件
        if self.mode == 'auto':
            self.screener = MarketScreener(
                client=self.client,
                criteria=ScreeningCriteria(
                    min_oi_change_percent=config.SCREEN_OI_THRESHOLD,
                    min_funding_rate=config.SCREEN_FUNDING_THRESHOLD,
                    min_price_change_24h=config.SCREEN_PRICE_CHANGE_THRESHOLD,
                    exclude_symbols=set(config.SCREEN_EXCLUDE_SYMBOLS or [])
                )
            )
            self.symbol_queue = SymbolQueue()
            self.candidates: Set[str] = set()
        else:
            self.screener = None
            self.symbol_queue = None

        # 数据缓存
        self.market_data: dict = {}
        self.spot_trades: dict = {}

        # 扫描统计
        self.light_scan_count = 0
        self.deep_scan_count = 0
        self.last_light_scan = 0

    async def initialize(self):
        """初始化监控"""
        self.logger.info("正在初始化监控系统...")
        self.logger.info(f"运行模式: {self.mode}")

        if self.mode == 'auto':
            self.logger.info("自动发现模式: 自动扫描全市场异常币种")
            self.logger.info(
                f"筛选阈值 - OI: {config.SCREEN_OI_THRESHOLD}%, "
                f"资金费率: {config.SCREEN_FUNDING_THRESHOLD}%, "
                f"价格变化: {config.SCREEN_PRICE_CHANGE_THRESHOLD}%"
            )
            # 预加载symbol列表
            symbols = await self.screener.refresh_all_symbols()
            self.symbol_queue.all_symbols = symbols
            self.logger.info(f"已加载 {len(symbols)} 个交易对")
        else:
            self.logger.info(f"定向监控模式: {config.SYMBOLS}")

        self.logger.info(f"更新间隔: {config.UPDATE_INTERVAL}秒")

    async def run_light_scan(self) -> List[str]:
        """
        第一层: 全量快速筛选 (Light Scan)

        每30秒执行一次，从~300币种中筛选出异常候选
        """
        if not self.screener:
            return list(config.SYMBOLS)

        self.light_scan_count += 1
        self.last_light_scan = asyncio.get_event_loop().time()

        try:
            candidates = await self.screener.get_candidates_for_deep_scan(
                min_score=config.SCREEN_MIN_SCORE,
                top_n=config.SCREEN_TOP_N
            )

            # 更新候选列表
            self.candidates = set(candidates)

            # 更新symbol队列
            self.symbol_queue.update_watch_list(candidates)

            self.logger.info(
                f"Light Scan #{self.light_scan_count}: "
                f"发现 {len(candidates)} 个候选币种 - {candidates[:5]}"
            )

            return candidates

        except Exception as e:
            self.logger.error(f"Light Scan失败: {e}")
            return []

    async def run_deep_scan(self, symbols: List[str]):
        """
        第二层: 深度信号分析 (Deep Scan)

        对候选币种进行完整的多因子信号计算
        """
        if not symbols:
            return

        self.deep_scan_count += 1

        # 限制每次扫描的symbol数量
        max_scan = config.DEEP_SCAN_MAX_SYMBOLS
        if len(symbols) > max_scan:
            self.logger.debug(f"深度扫描限制: 只扫描前 {max_scan} 个")
            symbols = symbols[:max_scan]

        self.logger.info(f"Deep Scan #{self.deep_scan_count}: 分析 {len(symbols)} 个币种")

        # 获取详细数据
        for symbol in symbols:
            try:
                data = await self.client.get_all_market_data(symbol)
                self.market_data[symbol] = data
                self.logger.debug(f"获取 {symbol} 数据成功")
            except Exception as e:
                self.logger.error(f"获取 {symbol} 数据失败: {e}")

        # 计算信号
        await self.calculate_and_alert(symbols)

    async def calculate_and_alert(self, symbols: Optional[List[str]] = None):
        """计算信号并触发告警"""
        if symbols:
            # 只计算指定symbol的数据
            market_data = {k: v for k, v in self.market_data.items() if k in symbols}
        else:
            market_data = self.market_data

        if not market_data:
            return

        signals = self.calculator.calculate_signals_batch(market_data)

        active_signals = [s for s in signals if s.signal_type != 'none']

        for signal in active_signals:
            self.logger.info(
                f"检测到信号: {signal.symbol} - "
                f"{signal.signal_type} ({signal.confidence}) - "
                f"强度: {signal.signal_strength:.2%}"
            )

        # 更新活跃symbol列表
        if self.symbol_queue and active_signals:
            active_symbols = [s.symbol for s in active_signals]
            self.symbol_queue.update_active_symbols(active_symbols)

        # 处理告警
        alerts = self.alert_manager.process_signals_batch(signals)
        if alerts:
            self.logger.info(f"本次扫描触发 {len(alerts)} 条告警")

    async def run_monitoring_loop(self):
        """运行监控循环 - 双层扫描策略"""
        self.logger.info("开始监控循环...")

        iteration = 0

        while self.running:
            try:
                iteration += 1
                now = asyncio.get_event_loop().time()

                if self.mode == 'auto':
                    # ========== 自动发现模式 ==========

                    # 1. Light Scan: 每 LIGHT_SCAN_INTERVAL 秒执行一次
                    time_since_light = now - self.last_light_scan
                    if time_since_light >= config.LIGHT_SCAN_INTERVAL:
                        candidates = await self.run_light_scan()

                        # 2. Deep Scan: 立即对候选币种深度分析
                        if candidates:
                            await self.run_deep_scan(candidates)
                    else:
                        # 3. 高优先级symbol持续监控
                        priority_symbols = self.symbol_queue.get_priority_symbols(
                            max_count=config.DEEP_SCAN_MAX_SYMBOLS
                        )
                        if priority_symbols:
                            await self.run_deep_scan(priority_symbols)

                else:
                    # ========== 定向监控模式 ==========
                    await self.fetch_market_data()
                    await self.calculate_and_alert()

                # 等待下一次更新
                await asyncio.sleep(config.UPDATE_INTERVAL)

            except Exception as e:
                self.logger.error(f"监控循环出错: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def fetch_market_data(self):
        """获取市场数据 (定向模式)"""
        for symbol in config.SYMBOLS:
            try:
                data = await self.client.get_all_market_data(symbol)
                self.market_data[symbol] = data
                self.logger.debug(f"获取 {symbol} 数据成功")
            except Exception as e:
                self.logger.error(f"获取 {symbol} 数据失败: {e}")

    async def run_websocket(self):
        """运行WebSocket监听"""
        async def on_trade(trade_data):
            """处理交易数据"""
            symbol = trade_data['symbol']
            if symbol not in self.spot_trades:
                self.spot_trades[symbol] = {'buy': [], 'sell': []}

            trade_type = 'buy' if trade_data['type'] == 'large_buy' else 'sell'
            self.spot_trades[symbol][trade_type].append(trade_data)

            # 限制列表大小
            if len(self.spot_trades[symbol][trade_type]) > 100:
                self.spot_trades[symbol][trade_type] = \
                    self.spot_trades[symbol][trade_type][-100:]

        # 为每个交易对订阅大单
        tasks = []
        for symbol in config.SYMBOLS:
            task = self.ws_client.subscribe_agg_trades(
                symbol,
                on_trade,
                min_quantity=1.0  # 过滤大单阈值
            )
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        """运行监控"""
        self.running = True

        await self.initialize()

        # 创建任务
        monitor_task = asyncio.create_task(self.run_monitoring_loop())
        # websocket_task = asyncio.create_task(self.run_websocket())

        # 等待任务
        try:
            await asyncio.gather(
                monitor_task,
                # websocket_task,
                return_exceptions=True
            )
        except asyncio.CancelledError:
            self.logger.info("监控任务被取消")

    async def stop(self):
        """停止监控"""
        self.logger.info("正在停止监控...")
        self.running = False
        await self.ws_client.disconnect()


def signal_handler(monitor: WhaleMonitor):
    """信号处理器"""
    def handler(signum, frame):
        print("\n收到停止信号，正在关闭...")
        asyncio.create_task(monitor.stop())
    return handler


async def main():
    """主函数"""
    setup_logging()

    # 解析命令行参数
    mode = 'auto'  # 默认自动发现模式
    if len(sys.argv) > 1:
        if sys.argv[1] in ['--auto', '-a']:
            mode = 'auto'
        elif sys.argv[1] in ['--manual', '-m']:
            mode = 'manual'

    monitor = WhaleMonitor(mode=mode)

    # 注册信号处理
    signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(monitor.stop()))
    signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(monitor.stop()))

    try:
        await monitor.run()
    except KeyboardInterrupt:
        await monitor.stop()
    finally:
        print("监控已停止")


if __name__ == "__main__":
    # 运行方式:
    # 1. 自动发现模式: python monitor.py (默认)
    # 2. 自动发现模式: python monitor.py --auto
    # 3. 定向监控模式: python monitor.py --manual
    # 4. Web界面: streamlit run web/dashboard.py

    if len(sys.argv) > 1 and sys.argv[1] == '--web':
        # 启动Web界面
        import subprocess
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", "web/dashboard.py"
        ])
    else:
        # 启动命令行监控
        asyncio.run(main())
