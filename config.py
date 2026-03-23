"""
币安期货主力出货监控系统配置
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """系统配置"""

    # Binance API配置
    BINANCE_API_KEY: str = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET: str = os.getenv('BINANCE_API_SECRET', '')

    # 测试网配置 (开发时使用)
    USE_TESTNET: bool = os.getenv('USE_TESTNET', 'false').lower() == 'true'

    # ==================== 监控模式配置 ====================

    # 监控模式: 'auto' (自动发现) 或 'manual' (定向监控)
    MONITOR_MODE: str = os.getenv('MONITOR_MODE', 'auto')

    # 定向监控交易对 (manual模式使用)
    SYMBOLS: tuple = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT')

    # ==================== 自动发现模式配置 ====================

    # 全量扫描间隔 (秒)
    LIGHT_SCAN_INTERVAL: int = 30

    # 深度扫描最大币种数 (每轮)
    DEEP_SCAN_MAX_SYMBOLS: int = 20

    # 最小异常评分 (0-1)
    SCREEN_MIN_SCORE: float = 0.3

    # 返回候选币数量 (None = 返回所有符合条件的)
    SCREEN_TOP_N: int = 30

    # OI筛选阈值 (%)
    SCREEN_OI_THRESHOLD: float = 5.0

    # 资金费率筛选阈值 (%)
    SCREEN_FUNDING_THRESHOLD: float = 0.05

    # 价格变化筛选阈值 (%)
    SCREEN_PRICE_CHANGE_THRESHOLD: float = 5.0

    # 排除的symbol (如大币)
    SCREEN_EXCLUDE_SYMBOLS: tuple = ()

    # ==================== 信号计算配置 ====================

    # OI监控阈值 (%)
    OI_CHANGE_THRESHOLD: float = 5.0

    # 资金费率监控阈值 (%)
    FUNDING_RATE_THRESHOLD: float = 0.01

    # 期现价差阈值 (%)
    BASIS_THRESHOLD: float = 0.1

    # 信号综合评分阈值
    SIGNAL_STRONG: float = 0.7
    SIGNAL_MEDIUM: float = 0.5
    SIGNAL_WEAK: float = 0.3

    # 信号权重配置
    WEIGHT_OI_CHANGE: float = 0.3
    WEIGHT_FUNDING_RATE: float = 0.25
    WEIGHT_BASIS: float = 0.25
    WEIGHT_SPOT_FLOW: float = 0.2

    # ==================== 运行时配置 ====================

    # 数据更新间隔 (秒)
    UPDATE_INTERVAL: int = 5

    # WebSocket重连间隔 (秒)
    WS_RECONNECT_INTERVAL: int = 5

    # 告警去重时间 (分钟)
    ALERT_DEDUP_MINUTES: int = 15

    # 历史数据保留数量
    HISTORY_SIZE: int = 1000

    # 日志配置
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = 'logs/whale_monitor.log'


# 全局配置实例
config = Config()
