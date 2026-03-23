"""
技术指标计算
"""
from typing import List, Dict, Any, Optional
import numpy as np


def calculate_oi_change_rate(
    current_oi: float,
    previous_oi: float
) -> float:
    """
    计算持仓量变化率

    Args:
        current_oi: 当前持仓量
        previous_oi: 前一周期持仓量

    Returns:
        变化率 (百分比)
    """
    if previous_oi == 0:
        return 0.0
    return ((current_oi - previous_oi) / previous_oi) * 100


def calculate_basis(
    futures_price: float,
    spot_price: float
) -> Dict[str, float]:
    """
    计算期现价差（基差）

    Args:
        futures_price: 期货价格
        spot_price: 现货价格

    Returns:
        {
            'basis': 绝对价差,
            'basis_rate': 价差率 (%),
            'annualized_rate': 年化基差率 (%)
        }
    """
    if spot_price == 0:
        return {'basis': 0.0, 'basis_rate': 0.0, 'annualized_rate': 0.0}

    basis = futures_price - spot_price
    basis_rate = (basis / spot_price) * 100

    # 假设季度合约，年化计算
    annualized_rate = basis_rate * 4

    return {
        'basis': basis,
        'basis_rate': basis_rate,
        'annualized_rate': annualized_rate
    }


def calculate_funding_rate_deviation(
    current_rate: float,
    historical_rates: List[float]
) -> Dict[str, float]:
    """
    计算资金费率偏离度

    Args:
        current_rate: 当前资金费率
        historical_rates: 历史资金费率列表

    Returns:
        {
            'deviation': 与均值偏离 (标准差倍数),
            'percentile': 历史百分位 (0-1),
            'is_extreme': 是否极端值
        }
    """
    if not historical_rates:
        return {'deviation': 0.0, 'percentile': 0.5, 'is_extreme': False}

    mean_rate = np.mean(historical_rates)
    std_rate = np.std(historical_rates)

    if std_rate == 0:
        deviation = 0.0
    else:
        deviation = (current_rate - mean_rate) / std_rate

    # 计算百分位
    sorted_rates = sorted(historical_rates + [current_rate])
    percentile = sorted_rates.index(current_rate) / len(sorted_rates)

    # 判断是否极端 (>2σ 或 <2σ)
    is_extreme = abs(deviation) > 2.0

    return {
        'deviation': deviation,
        'percentile': percentile,
        'is_extreme': is_extreme
    }


def calculate_long_short_sentiment(long_short_ratio: float) -> str:
    """
    根据多空比判断市场情绪

    Args:
        long_short_ratio: 多空比 (多头/空头)

    Returns:
        情绪描述: 'extreme_long', 'long', 'neutral', 'short', 'extreme_short'
    """
    if long_short_ratio > 2.0:
        return 'extreme_long'
    elif long_short_ratio > 1.5:
        return 'long'
    elif long_short_ratio < 0.5:
        return 'extreme_short'
    elif long_short_ratio < 0.67:
        return 'short'
    else:
        return 'neutral'


def calculate_spot_flow_signal(
    buy_volume: float,
    sell_volume: float,
    large_buy_count: int = 0,
    large_sell_count: int = 0
) -> Dict[str, Any]:
    """
    计算现货资金流向信号

    Args:
        buy_volume: 买入量
        sell_volume: 卖出量
        large_buy_count: 大单买入次数
        large_sell_count: 大单卖出次数

    Returns:
        {
            'net_flow': 净流入 (>0买入, <0卖出),
            'flow_ratio': 买卖比率,
            'signal': 'inflow' | 'outflow' | 'neutral',
            'large_order_signal': 'buy' | 'sell' | 'neutral'
        }
    """
    total_volume = buy_volume + sell_volume

    if total_volume == 0:
        return {
            'net_flow': 0.0,
            'flow_ratio': 1.0,
            'signal': 'neutral',
            'large_order_signal': 'neutral'
        }

    net_flow = buy_volume - sell_volume
    flow_ratio = buy_volume / sell_volume if sell_volume > 0 else float('inf')

    # 判断资金流向
    if flow_ratio > 1.3:
        signal = 'inflow'
    elif flow_ratio < 0.77:
        signal = 'outflow'
    else:
        signal = 'neutral'

    # 大单信号
    large_order_diff = large_buy_count - large_sell_count
    if large_order_diff > 3:
        large_order_signal = 'buy'
    elif large_order_diff < -3:
        large_order_signal = 'sell'
    else:
        large_order_signal = 'neutral'

    return {
        'net_flow': net_flow,
        'flow_ratio': flow_ratio,
        'signal': signal,
        'large_order_signal': large_order_signal
    }


def calculate_oi_velocity(
    oi_history: List[float],
    window: int = 5
) -> Dict[str, float]:
    """
    计算持仓量变化速度

    Args:
        oi_history: 持仓量历史数据
        window: 计算窗口

    Returns:
        {
            'velocity': 变化速度 (%/周期),
            'acceleration': 加速度,
            'trend': 'increasing' | 'decreasing' | 'stable'
        }
    """
    if len(oi_history) < window + 1:
        return {'velocity': 0.0, 'acceleration': 0.0, 'trend': 'stable'}

    recent = oi_history[-window:]
    previous = oi_history[-(window+1):-1]

    # 计算平均变化率
    changes = [(r - p) / p * 100 for r, p in zip(recent, previous) if p != 0]

    if not changes:
        return {'velocity': 0.0, 'acceleration': 0.0, 'trend': 'stable'}

    velocity = np.mean(changes)

    # 计算加速度 (速度变化)
    if len(changes) >= 2:
        acceleration = changes[-1] - changes[-2]
    else:
        acceleration = 0.0

    # 判断趋势
    if velocity > 1.0:
        trend = 'increasing'
    elif velocity < -1.0:
        trend = 'decreasing'
    else:
        trend = 'stable'

    return {
        'velocity': velocity,
        'acceleration': acceleration,
        'trend': trend
    }


def detect_volume_anomaly(
    current_volume: float,
    volume_history: List[float],
    threshold: float = 2.0
) -> Dict[str, Any]:
    """
    检测成交量异常

    Args:
        current_volume: 当前成交量
        volume_history: 历史成交量
        threshold: 异常阈值 (标准差倍数)

    Returns:
        {
            'is_anomaly': 是否异常,
            'z_score': Z分数,
            'anomaly_type': 'spike' | 'drop' | 'normal'
        }
    """
    if not volume_history:
        return {'is_anomaly': False, 'z_score': 0.0, 'anomaly_type': 'normal'}

    mean_vol = np.mean(volume_history)
    std_vol = np.std(volume_history)

    if std_vol == 0:
        return {'is_anomaly': False, 'z_score': 0.0, 'anomaly_type': 'normal'}

    z_score = (current_volume - mean_vol) / std_vol

    is_anomaly = abs(z_score) > threshold

    if z_score > threshold:
        anomaly_type = 'spike'
    elif z_score < -threshold:
        anomaly_type = 'drop'
    else:
        anomaly_type = 'normal'

    return {
        'is_anomaly': is_anomaly,
        'z_score': z_score,
        'anomaly_type': anomaly_type
    }
