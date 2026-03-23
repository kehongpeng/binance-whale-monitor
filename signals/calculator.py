"""
信号计算引擎 - 核心信号计算逻辑
"""
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from config import config
from signals.indicators import (
    calculate_oi_change_rate,
    calculate_basis,
    calculate_funding_rate_deviation,
    calculate_long_short_sentiment,
    calculate_spot_flow_signal,
    calculate_oi_velocity
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalResult:
    """信号结果"""
    symbol: str
    timestamp: datetime
    signal_type: str  # 'distribution', 'accumulation', 'none'
    signal_strength: float  # 0.0 - 1.0
    confidence: str  # 'strong', 'medium', 'weak', 'none'

    # 原始指标
    oi_change_rate: float
    funding_rate: float
    basis_rate: float
    spot_flow_signal: str

    # 详细评分
    oi_score: float
    funding_score: float
    basis_score: float
    flow_score: float

    # 附加信息
    details: Dict[str, Any]


class SignalCalculator:
    """信号计算器"""

    def __init__(self):
        self.history: Dict[str, List[Dict]] = {}
        self.max_history = config.HISTORY_SIZE

    def _normalize_score(self, value: float, min_val: float, max_val: float) -> float:
        """将值归一化到0-1范围"""
        if max_val == min_val:
            return 0.5
        return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))

    def _calculate_oi_component(self, oi_change_rate: float) -> float:
        """
        计算持仓量分量分数

        OI增长是必要条件：
        - OI增长 > 5%: 高分 (说明有新资金进场)
        - OI增长 2-5%: 中分
        - OI增长 < 2%: 低分 (资金参与度不够)
        """
        if oi_change_rate >= config.OI_CHANGE_THRESHOLD:
            # OI大幅增长，主力可能参与
            return 1.0
        elif oi_change_rate >= config.OI_CHANGE_THRESHOLD / 2:
            return 0.6
        elif oi_change_rate > 0:
            return 0.3
        else:
            # OI下降，不可能是出货/吸筹
            return 0.0

    def _calculate_funding_component(
        self,
        funding_rate: float,
        signal_type: str
    ) -> float:
        """
        计算资金费率分量分数

        出货信号：资金费率转负（空头支付多头，说明空头增加）
        吸筹信号：资金费率为正（多头支付空头，说明多头增加）
        """
        if signal_type == 'distribution':
            # 出货：希望资金费率变负或下降
            if funding_rate < -config.FUNDING_RATE_THRESHOLD:
                # 资金费率为负，空头占优，利于出货
                return 1.0
            elif funding_rate < 0:
                return 0.7
            elif funding_rate < config.FUNDING_RATE_THRESHOLD:
                return 0.4
            else:
                # 资金费率高，多头太强，不利于出货
                return 0.1
        else:  # accumulation
            # 吸筹：希望资金费率为正
            if funding_rate > config.FUNDING_RATE_THRESHOLD:
                return 1.0
            elif funding_rate > 0:
                return 0.7
            elif funding_rate > -config.FUNDING_RATE_THRESHOLD:
                return 0.4
            else:
                return 0.1

    def _calculate_basis_component(
        self,
        basis_rate: float,
        signal_type: str
    ) -> float:
        """
        计算期现价差分量分数

        出货信号：期货贴水（期货价格 < 现货价格）
        吸筹信号：期货升水（期货价格 > 现货价格）
        """
        if signal_type == 'distribution':
            # 出货：希望期货贴水
            if basis_rate < -config.BASIS_THRESHOLD:
                # 明显贴水，出货信号强
                return 1.0
            elif basis_rate < 0:
                return 0.7
            elif basis_rate < config.BASIS_THRESHOLD:
                return 0.3
            else:
                # 升水，不利于出货
                return 0.0
        else:  # accumulation
            # 吸筹：希望期货升水
            if basis_rate > config.BASIS_THRESHOLD:
                return 1.0
            elif basis_rate > 0:
                return 0.7
            elif basis_rate > -config.BASIS_THRESHOLD:
                return 0.4
            else:
                return 0.1

    def _calculate_flow_component(
        self,
        spot_flow: str,
        signal_type: str
    ) -> float:
        """
        计算现货资金流向分量分数

        出货信号：现货大单净流出
        吸筹信号：现货大单净流入
        """
        if signal_type == 'distribution':
            # 出货：希望现货流出
            if spot_flow == 'outflow':
                return 1.0
            elif spot_flow == 'neutral':
                return 0.5
            else:
                return 0.0
        else:  # accumulation
            # 吸筹：希望现货流入
            if spot_flow == 'inflow':
                return 1.0
            elif spot_flow == 'neutral':
                return 0.5
            else:
                return 0.0

    def calculate_signal(
        self,
        symbol: str,
        oi_data: Dict[str, Any],
        funding_data: Dict[str, Any],
        price_data: Dict[str, Any],
        flow_data: Dict[str, Any],
        oi_history: Optional[List[float]] = None
    ) -> SignalResult:
        """
        计算综合信号

        Args:
            symbol: 交易对
            oi_data: 持仓量数据
            funding_data: 资金费率数据
            price_data: 价格数据
            flow_data: 资金流向数据
            oi_history: OI历史数据

        Returns:
            SignalResult: 信号结果
        """
        # 提取原始值
        current_oi = float(oi_data.get('openInterest', 0))
        funding_rate = float(funding_data.get('lastFundingRate', 0))

        mark_price = float(price_data.get('markPrice', 0))
        spot_price = float(price_data.get('spot_price', mark_price))

        # 计算各项指标
        # 1. OI变化率
        oi_change_rate = 0.0
        if oi_history and len(oi_history) >= 2:
            oi_change_rate = calculate_oi_change_rate(
                current_oi,
                oi_history[-2]
            )

        # 2. 期现价差
        basis_info = calculate_basis(mark_price, spot_price)
        basis_rate = basis_info['basis_rate']

        # 3. 现货流向
        flow_info = calculate_spot_flow_signal(
            flow_data.get('buy_volume', 0),
            flow_data.get('sell_volume', 0),
            flow_data.get('large_buy_count', 0),
            flow_data.get('large_sell_count', 0)
        )
        spot_flow_signal = flow_info['signal']

        # 判断信号类型
        # 基于OI增长 + 资金费率方向
        if oi_change_rate > 0:
            if funding_rate < 0 or spot_flow_signal == 'outflow':
                signal_type = 'distribution'  # 出货
            else:
                signal_type = 'accumulation'  # 吸筹
        else:
            signal_type = 'none'

        # 计算各分量分数
        oi_score = self._calculate_oi_component(oi_change_rate)
        funding_score = self._calculate_funding_component(funding_rate, signal_type)
        basis_score = self._calculate_basis_component(basis_rate, signal_type)
        flow_score = self._calculate_flow_component(spot_flow_signal, signal_type)

        # 计算综合信号强度 (加权平均)
        if signal_type == 'none':
            signal_strength = 0.0
        else:
            signal_strength = (
                oi_score * config.WEIGHT_OI_CHANGE +
                funding_score * config.WEIGHT_FUNDING_RATE +
                basis_score * config.WEIGHT_BASIS +
                flow_score * config.WEIGHT_SPOT_FLOW
            )

        # 判断置信度
        if signal_strength >= config.SIGNAL_STRONG:
            confidence = 'strong'
        elif signal_strength >= config.SIGNAL_MEDIUM:
            confidence = 'medium'
        elif signal_strength >= config.SIGNAL_WEAK:
            confidence = 'weak'
        else:
            confidence = 'none'
            signal_type = 'none'

        # 构建详情
        details = {
            'basis_info': basis_info,
            'flow_info': flow_info,
            'long_short_ratio': price_data.get('long_short_ratio'),
            'mark_price': mark_price,
            'spot_price': spot_price,
            'current_oi': current_oi
        }

        return SignalResult(
            symbol=symbol,
            timestamp=datetime.now(),
            signal_type=signal_type,
            signal_strength=signal_strength,
            confidence=confidence,
            oi_change_rate=oi_change_rate,
            funding_rate=funding_rate,
            basis_rate=basis_rate,
            spot_flow_signal=spot_flow_signal,
            oi_score=oi_score,
            funding_score=funding_score,
            basis_score=basis_score,
            flow_score=flow_score,
            details=details
        )

    def calculate_signals_batch(
        self,
        market_data: Dict[str, Dict[str, Any]]
    ) -> List[SignalResult]:
        """
        批量计算多个交易对的信号

        Args:
            market_data: {symbol: {oi_data, funding_data, price_data, flow_data}}

        Returns:
            List[SignalResult]: 信号结果列表
        """
        results = []

        for symbol, data in market_data.items():
            try:
                # 更新历史数据
                if symbol not in self.history:
                    self.history[symbol] = []

                oi_value = float(data.get('oi_data', {}).get('openInterest', 0))
                self.history[symbol].append(oi_value)

                # 限制历史数据大小
                if len(self.history[symbol]) > self.max_history:
                    self.history[symbol] = self.history[symbol][-self.max_history:]

                # 计算信号
                result = self.calculate_signal(
                    symbol=symbol,
                    oi_data=data.get('oi_data', {}),
                    funding_data=data.get('funding_data', {}),
                    price_data=data.get('price_data', {}),
                    flow_data=data.get('flow_data', {}),
                    oi_history=self.history.get(symbol)
                )

                results.append(result)

            except Exception as e:
                logger.error(f'计算信号失败 {symbol}: {e}')

        return results


# 全局计算器实例
calculator = SignalCalculator()
