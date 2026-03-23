"""
市场筛选器 - 快速发现异常币种

三层扫描策略:
1. Light Scan: 全量快速筛选 (~300币种, 2个API调用)
2. Deep Scan: 深度信号分析 (仅对候选币种)
3. WebSocket: 实时监控所有币种
"""
import asyncio
import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import time

from config import config

logger = logging.getLogger(__name__)


@dataclass
class ScreeningCriteria:
    """筛选条件配置"""
    # OI相关阈值
    min_oi_change_percent: float = 5.0  # OI变化率阈值 (%)
    min_oi_value_usdt: float = 1000000  # 最小OI市值 ($1M)

    # 资金费率阈值
    min_funding_rate: float = 0.05  # 资金费率绝对值阈值 (%)
    funding_velocity_threshold: float = 0.02  # 资金费率变化速度 (%/小时)

    # 成交量相关
    min_volume_24h: float = 1000000  # 最小24h成交量 ($1M)
    volume_change_threshold: float = 50.0  # 成交量变化率 (%)

    # 价格波动
    min_price_change_24h: float = 5.0  # 24h价格变化 (%)
    volatility_threshold: float = 3.0  # 波动率阈值 (%)

    # 市值过滤
    max_market_cap_rank: int = 300  # 最大市值排名
    exclude_symbols: Set[str] = field(default_factory=lambda: {'BTCUSDT', 'ETHUSDT'})  # 可配置排除大币

    def adjust_for_market_cap(self, symbol: str, base_threshold: float) -> float:
        """
        根据市值调整阈值
        - 小币: 阈值放宽 (波动本来就大)
        - 大币: 阈值收紧
        """
        # 简单实现: 根据symbol后缀和常见命名规则判断
        # 实际项目中可以从API获取市值数据
        is_large_cap = any(x in symbol for x in ['BTC', 'ETH', 'BNB', 'SOL', 'XRP'])

        if is_large_cap:
            return base_threshold * 0.8  # 大币收紧20%
        else:
            return base_threshold * 1.2  # 小币放宽20%


@dataclass
class SymbolSnapshot:
    """币种快照数据"""
    symbol: str
    timestamp: float

    # OI数据
    open_interest: float = 0.0
    open_interest_value: float = 0.0
    oi_change_24h: float = 0.0

    # 资金费率
    funding_rate: float = 0.0
    funding_rate_annual: float = 0.0
    next_funding_time: int = 0

    # 价格和成交量
    mark_price: float = 0.0
    index_price: float = 0.0
    price_change_24h: float = 0.0
    price_change_percent: float = 0.0
    volume_24h: float = 0.0
    volume_usdt: float = 0.0

    # 统计数据
    high_24h: float = 0.0
    low_24h: float = 0.0
    weighted_avg_price: float = 0.0

    # 计算字段
    funding_velocity: float = 0.0  # 资金费率变化速度
    volume_rank: int = 0
    oi_rank: int = 0


@dataclass
class AnomalyScore:
    """异常评分结果"""
    symbol: str
    total_score: float
    components: Dict[str, float]  # 各因子得分
    signals: List[str]  # 触发信号说明
    timestamp: float

    def is_significant(self, threshold: float = 0.6) -> bool:
        """是否显著异常"""
        return self.total_score >= threshold


class BaselineLearner:
    """
    学习每个币种的正常波动范围
    用于自适应阈值调整
    """

    def __init__(self, history_size: int = 100):
        self.history: Dict[str, List[SymbolSnapshot]] = {}
        self.history_size = history_size
        self.baselines: Dict[str, Dict[str, float]] = {}

    def update(self, snapshot: SymbolSnapshot):
        """更新历史数据"""
        symbol = snapshot.symbol

        if symbol not in self.history:
            self.history[symbol] = []

        self.history[symbol].append(snapshot)

        # 限制历史数据大小
        if len(self.history[symbol]) > self.history_size:
            self.history[symbol] = self.history[symbol][-self.history_size:]

        # 更新基线
        self._update_baseline(symbol)

    def _update_baseline(self, symbol: str):
        """计算该币种的正常波动基线"""
        if symbol not in self.history or len(self.history[symbol]) < 10:
            return

        history = self.history[symbol]

        # 计算各项指标的标准差和均值
        oi_changes = [h.oi_change_24h for h in history if h.oi_change_24h != 0]
        funding_rates = [h.funding_rate for h in history]
        volumes = [h.volume_24h for h in history]

        import statistics

        self.baselines[symbol] = {
            'oi_change_mean': statistics.mean(oi_changes) if oi_changes else 0,
            'oi_change_std': statistics.stdev(oi_changes) if len(oi_changes) > 1 else 1,
            'funding_mean': statistics.mean(funding_rates) if funding_rates else 0,
            'funding_std': statistics.stdev(funding_rates) if len(funding_rates) > 1 else 0.0001,
            'volume_mean': statistics.mean(volumes) if volumes else 0,
            'volume_std': statistics.stdev(volumes) if len(volumes) > 1 else 1,
        }

    def is_anomalous(self, symbol: str, metric: str, value: float, z_threshold: float = 2.0) -> bool:
        """
        判断是否对该币种来说是异常的 (使用Z-score)

        Args:
            symbol: 币种
            metric: 指标名 (oi_change, funding, volume)
            value: 当前值
            z_threshold: Z-score阈值

        Returns:
            是否异常
        """
        if symbol not in self.baselines:
            return False  # 没有足够历史数据

        baseline = self.baselines[symbol]

        mapping = {
            'oi_change': ('oi_change_mean', 'oi_change_std'),
            'funding': ('funding_mean', 'funding_std'),
            'volume': ('volume_mean', 'volume_std'),
        }

        if metric not in mapping:
            return False

        mean_key, std_key = mapping[metric]
        mean = baseline[mean_key]
        std = baseline[std_key]

        if std == 0:
            return False

        z_score = abs(value - mean) / std
        return z_score > z_threshold

    def get_z_score(self, symbol: str, metric: str, value: float) -> float:
        """获取Z-score"""
        if symbol not in self.baselines:
            return 0.0

        baseline = self.baselines[symbol]

        mapping = {
            'oi_change': ('oi_change_mean', 'oi_change_std'),
            'funding': ('funding_mean', 'funding_std'),
            'volume': ('volume_mean', 'volume_std'),
        }

        if metric not in mapping:
            return 0.0

        mean_key, std_key = mapping[metric]
        mean = baseline[mean_key]
        std = baseline[std_key]

        if std == 0:
            return 0.0

        return (value - mean) / std


class MarketScreener:
    """
    市场筛选器 - 快速发现异常币种

    性能优化:
    - Light Scan: 仅2个API调用获取~300币种数据
    - 缓存机制: 避免重复请求
    - 自适应阈值: 根据币种历史调整敏感度
    """

    def __init__(
        self,
        client=None,
        criteria: Optional[ScreeningCriteria] = None,
        use_baseline: bool = True
    ):
        self.logger = logging.getLogger(__name__)
        self.client = client
        self.criteria = criteria or ScreeningCriteria()

        # 缓存
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl = 30  # 缓存30秒

        # 全量symbol列表
        self.all_symbols: Set[str] = set()
        self._last_symbol_update: float = 0
        self._symbol_cache_ttl = 3600  # 1小时更新一次symbol列表

        # 基线学习器
        self.use_baseline = use_baseline
        self.baseline_learner = BaselineLearner() if use_baseline else None

        # 本地状态维护 (用于WebSocket集成)
        self.local_state: Dict[str, SymbolSnapshot] = {}
        self.funding_history: Dict[str, List[tuple]] = {}  # symbol -> [(timestamp, rate)]
        self.oi_history: Dict[str, List[tuple]] = {}  # symbol -> [(timestamp, oi_value)]

    def _get_cached(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if key in self._cache:
            if time.time() - self._cache_time.get(key, 0) < self._cache_ttl:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any):
        """设置缓存"""
        self._cache[key] = value
        self._cache_time[key] = time.time()

    async def get_all_premium_index(self) -> List[Dict]:
        """
        一次性获取所有合约资金费率和标记价格

        API: GET /fapi/v1/premiumIndex (无symbol参数)
        Weight: 1
        """
        cached = self._get_cached('premium_index')
        if cached:
            return cached

        if not self.client:
            raise ValueError("BinanceAPIClient not provided")

        url = f"{self.client.FAPI_BASE}/fapi/v1/premiumIndex"

        try:
            data = await self.client._async_get(url)
            self._set_cache('premium_index', data)
            self.logger.debug(f"获取全量premiumIndex成功: {len(data)} 个合约")
            return data
        except Exception as e:
            self.logger.error(f"获取全量premiumIndex失败: {e}")
            raise

    async def get_all_24h_ticker(self) -> List[Dict]:
        """
        一次性获取所有合约24h统计

        API: GET /fapi/v1/ticker/24hr (无symbol参数)
        Weight: 1 (按IP限流, 每秒5次)
        """
        cached = self._get_cached('ticker_24h')
        if cached:
            return cached

        if not self.client:
            raise ValueError("BinanceAPIClient not provided")

        url = f"{self.client.FAPI_BASE}/fapi/v1/ticker/24hr"

        try:
            data = await self.client._async_get(url)
            self._set_cache('ticker_24h', data)
            self.logger.debug(f"获取全量24h ticker成功: {len(data)} 个合约")
            return data
        except Exception as e:
            self.logger.error(f"获取全量24h ticker失败: {e}")
            raise

    async def get_all_open_interest(self) -> List[Dict]:
        """
        获取所有合约的持仓量信息

        Note: 币安没有直接的全量OI接口, 需要通过其他方式获取
        目前从premiumIndex中提取sumOpenInterestValue
        """
        cached = self._get_cached('open_interest')
        if cached:
            return cached

        # 从premiumIndex获取OI信息
        premium_data = await self.get_all_premium_index()

        oi_data = []
        for item in premium_data:
            oi_data.append({
                'symbol': item['symbol'],
                'openInterest': item.get('openInterest', '0'),
                'openInterestValue': item.get('openInterestValue', '0'),
                'markPrice': item.get('markPrice', '0'),
            })

        self._set_cache('open_interest', oi_data)
        return oi_data

    async def refresh_all_symbols(self) -> Set[str]:
        """
        刷新全量symbol列表

        Returns:
            所有USDT永续合约的symbol集合
        """
        now = time.time()
        if now - self._last_symbol_update < self._symbol_cache_ttl and self.all_symbols:
            return self.all_symbols

        try:
            # 从24h ticker获取所有symbol
            ticker_data = await self.get_all_24h_ticker()

            # 过滤USDT永续合约
            symbols = set()
            for item in ticker_data:
                symbol = item.get('symbol', '')
                # 只保留USDT永续合约
                if symbol.endswith('USDT') and not symbol.endswith('BUSD'):
                    # 过滤掉不需要的symbol (如指数、测试等)
                    if '_' not in symbol and len(symbol) >= 6:
                        symbols.add(symbol)

            self.all_symbols = symbols
            self._last_symbol_update = now

            self.logger.info(f"刷新symbol列表: {len(symbols)} 个USDT合约")
            return symbols

        except Exception as e:
            self.logger.error(f"刷新symbol列表失败: {e}")
            # 返回缓存的symbol列表
            return self.all_symbols

    def _parse_snapshot(
        self,
        premium_item: Dict,
        ticker_item: Dict
    ) -> Optional[SymbolSnapshot]:
        """解析API数据为SymbolSnapshot"""
        try:
            symbol = premium_item['symbol']

            # 解析premiumIndex数据
            open_interest = float(premium_item.get('openInterest', 0))
            oi_value = float(premium_item.get('openInterestValue', 0))
            funding_rate = float(premium_item.get('lastFundingRate', 0))
            mark_price = float(premium_item.get('markPrice', 0))
            index_price = float(premium_item.get('indexPrice', 0))
            next_funding = premium_item.get('nextFundingTime', 0)

            # 计算年化资金费率 (每8小时结算, 乘以3×365)
            funding_annual = funding_rate * 3 * 365 * 100

            # 解析ticker数据
            volume = float(ticker_item.get('volume', 0))
            quote_volume = float(ticker_item.get('quoteVolume', 0))
            price_change = float(ticker_item.get('priceChange', 0))
            price_change_percent = float(ticker_item.get('priceChangePercent', 0))
            high_24h = float(ticker_item.get('highPrice', 0))
            low_24h = float(ticker_item.get('lowPrice', 0))
            weighted_avg = float(ticker_item.get('weightedAvgPrice', 0))

            # 计算OI变化率 (通过历史数据对比)
            oi_change = 0.0
            if symbol in self.oi_history and self.oi_history[symbol]:
                last_oi = self.oi_history[symbol][-1][1]
                if last_oi > 0:
                    oi_change = (open_interest - last_oi) / last_oi * 100

            # 更新OI历史
            if symbol not in self.oi_history:
                self.oi_history[symbol] = []
            self.oi_history[symbol].append((time.time(), open_interest))
            # 限制历史长度
            if len(self.oi_history[symbol]) > 50:
                self.oi_history[symbol] = self.oi_history[symbol][-50:]

            return SymbolSnapshot(
                symbol=symbol,
                timestamp=time.time(),
                open_interest=open_interest,
                open_interest_value=oi_value,
                oi_change_24h=oi_change,
                funding_rate=funding_rate * 100,  # 转为百分比
                funding_rate_annual=funding_annual,
                next_funding_time=next_funding,
                mark_price=mark_price,
                index_price=index_price,
                price_change_24h=price_change,
                price_change_percent=price_change_percent,
                volume_24h=volume,
                volume_usdt=quote_volume,
                high_24h=high_24h,
                low_24h=low_24h,
                weighted_avg_price=weighted_avg
            )

        except (KeyError, ValueError) as e:
            self.logger.warning(f"解析{premium_item.get('symbol', 'unknown')}数据失败: {e}")
            return None

    async def get_all_snapshots(self) -> List[SymbolSnapshot]:
        """
        获取所有币种的完整快照

        Returns:
            List[SymbolSnapshot]: 所有币种的快照数据
        """
        # 并行获取两个API
        premium_task = self.get_all_premium_index()
        ticker_task = self.get_all_24h_ticker()

        premium_data, ticker_data = await asyncio.gather(
            premium_task,
            ticker_task,
            return_exceptions=True
        )

        if isinstance(premium_data, Exception):
            self.logger.error(f"获取premiumIndex失败: {premium_data}")
            return []

        if isinstance(ticker_data, Exception):
            self.logger.error(f"获取ticker失败: {ticker_data}")
            return []

        # 建立symbol索引
        ticker_map = {item['symbol']: item for item in ticker_data}

        # 合并数据
        snapshots = []
        for premium_item in premium_data:
            symbol = premium_item['symbol']
            if symbol in ticker_map:
                snapshot = self._parse_snapshot(premium_item, ticker_map[symbol])
                if snapshot:
                    snapshots.append(snapshot)

        # 更新本地状态和基线
        for snapshot in snapshots:
            self.local_state[snapshot.symbol] = snapshot
            if self.baseline_learner:
                self.baseline_learner.update(snapshot)

        return snapshots

    def screen_anomalies(
        self,
        snapshots: List[SymbolSnapshot],
        min_score: float = 0.3
    ) -> List[AnomalyScore]:
        """
        筛选异常币种

        多因子评分系统:
        - OI异常增长 (30%)
        - 资金费率异常 (25%)
        - 成交量激增 (25%)
        - 价格波动 (20%)

        Returns:
            按异常评分排序的币种列表
        """
        scores = []

        # 计算排名数据
        sorted_by_volume = sorted(snapshots, key=lambda x: x.volume_usdt, reverse=True)
        sorted_by_oi = sorted(snapshots, key=lambda x: x.open_interest_value, reverse=True)

        volume_ranks = {s.symbol: i + 1 for i, s in enumerate(sorted_by_volume)}
        oi_ranks = {s.symbol: i + 1 for i, s in enumerate(sorted_by_oi)}

        for snapshot in snapshots:
            # 更新排名
            snapshot.volume_rank = volume_ranks.get(snapshot.symbol, 999)
            snapshot.oi_rank = oi_ranks.get(snapshot.symbol, 999)

            # 计算异常评分
            score = self._calculate_anomaly_score(snapshot)

            if score.total_score >= min_score:
                scores.append(score)

        # 按评分排序
        scores.sort(key=lambda x: x.total_score, reverse=True)
        return scores

    def _calculate_anomaly_score(self, snapshot: SymbolSnapshot) -> AnomalyScore:
        """
        计算单个币种的异常评分

        Returns:
            AnomalyScore: 包含总分和各因子得分的详细评分
        """
        components = {}
        signals = []

        criteria = self.criteria
        symbol = snapshot.symbol

        # 1. OI评分 (30%) - 所有币种都有基础分
        oi_score = 0.0

        # 1.1 OI变化率 (如果有明显变化)
        if abs(snapshot.oi_change_24h) >= 0.01:
            oi_change = abs(snapshot.oi_change_24h)
            threshold = criteria.adjust_for_market_cap(symbol, criteria.min_oi_change_percent)
            if oi_change > threshold:
                oi_score = min(0.6, oi_change / (threshold * 2))
                signals.append(f"OI变化: {snapshot.oi_change_24h:+.2f}%")

        # 1.2 OI市值排名 (所有币种都参与排名评分)
        if snapshot.oi_rank > 0:
            # 前300名都有分数，排名越靠前分数越高
            if snapshot.oi_rank <= 300:
                oi_rank_score = 0.35 * max(0, (1 - snapshot.oi_rank / 300))
                oi_score = max(oi_score, oi_rank_score)
                if oi_rank_score > 0.1:
                    signals.append(f"OI排名: #{snapshot.oi_rank}")

        # 1.3 OI绝对值（只要有持仓就有基础分）
        if snapshot.open_interest_value > 0:
            # 基于OI市值的对数评分，确保大小币种都有显示
            import math
            oi_value_millions = snapshot.open_interest_value / 1000000
            oi_value_score = min(0.25, math.log10(oi_value_millions + 1) / 4)
            oi_score = max(oi_score, oi_value_score)

        # 检查基线异常
        if self.baseline_learner and abs(snapshot.oi_change_24h) > 0.01:
            if self.baseline_learner.is_anomalous(symbol, 'oi_change', snapshot.oi_change_24h):
                z_score = self.baseline_learner.get_z_score(symbol, 'oi_change', snapshot.oi_change_24h)
                oi_score = max(oi_score, min(0.5, z_score / 4))
                signals.append(f"OI基线异常(Z:{z_score:.1f})")

        components['oi_change'] = min(1.0, oi_score)

        # 2. 资金费率评分 (25%)
        funding_score = 0.0
        funding_abs = abs(snapshot.funding_rate)

        if funding_abs > criteria.min_funding_rate:
            funding_score = min(1.0, funding_abs / (criteria.min_funding_rate * 3))
            direction = "多头付息" if snapshot.funding_rate > 0 else "空头付息"
            signals.append(f"资金费率: {snapshot.funding_rate:+.3f}% ({direction})")

        # 资金费率速度 (如果有历史数据)
        if symbol in self.funding_history and len(self.funding_history[symbol]) >= 2:
            history = self.funding_history[symbol]
            if len(history) >= 2:
                last_rate = history[-1][1]
                velocity = abs(snapshot.funding_rate - last_rate)
                if velocity > criteria.funding_velocity_threshold:
                    funding_score = max(funding_score, min(1.0, velocity / (criteria.funding_velocity_threshold * 2)))
                    signals.append(f"资金费率突变: {velocity:+.3f}%/h")

        components['funding'] = funding_score

        # 3. 成交量评分 (25%)
        volume_score = 0.0

        # 绝对成交量排名
        if snapshot.volume_rank <= 50:
            volume_score += 0.3 * (1 - snapshot.volume_rank / 50)

        # 相对历史的变化 (使用价格变化作为代理)
        price_change_abs = abs(snapshot.price_change_percent)
        if price_change_abs > criteria.min_price_change_24h:
            volume_score += min(0.7, price_change_abs / (criteria.min_price_change_24h * 2))
            signals.append(f"24h价格变化: {snapshot.price_change_percent:+.1f}%")

        components['volume'] = min(1.0, volume_score)

        # 4. 综合波动评分 (20%)
        volatility_score = 0.0

        # 日内波动
        if snapshot.high_24h > 0 and snapshot.low_24h > 0:
            intraday_volatility = (snapshot.high_24h - snapshot.low_24h) / snapshot.low_24h * 100
            if intraday_volatility > criteria.volatility_threshold:
                volatility_score = min(1.0, intraday_volatility / (criteria.volatility_threshold * 3))
                signals.append(f"日内波动: {intraday_volatility:.1f}%")

        components['volatility'] = volatility_score

        # 计算总分
        total_score = (
            components['oi_change'] * 0.30 +
            components['funding'] * 0.25 +
            components['volume'] * 0.25 +
            components['volatility'] * 0.20
        )

        return AnomalyScore(
            symbol=symbol,
            total_score=total_score,
            components=components,
            signals=signals,
            timestamp=snapshot.timestamp
        )

    def update_from_websocket(self, funding_data: Dict):
        """
        从WebSocket数据更新本地状态

        Args:
            funding_data: WebSocket推送的资金费率数据
                {
                    's': 'BTCUSDT',
                    'r': '0.00010000',
                    'T': 1698768000000
                }
        """
        try:
            symbol = funding_data.get('s')
            if not symbol:
                return

            funding_rate = float(funding_data.get('r', 0)) * 100  # 转为百分比
            timestamp = funding_data.get('T', 0)

            # 更新历史
            if symbol not in self.funding_history:
                self.funding_history[symbol] = []

            self.funding_history[symbol].append((timestamp, funding_rate))

            # 限制历史长度
            if len(self.funding_history[symbol]) > 100:
                self.funding_history[symbol] = self.funding_history[symbol][-100:]

            # 更新本地状态
            if symbol in self.local_state:
                snapshot = self.local_state[symbol]
                snapshot.funding_rate = funding_rate

                # 计算变化速度
                if len(self.funding_history[symbol]) >= 2:
                    prev_rate = self.funding_history[symbol][-2][1]
                    snapshot.funding_velocity = funding_rate - prev_rate

        except Exception as e:
            self.logger.warning(f"更新WebSocket数据失败: {e}")

    async def get_candidates_for_deep_scan(
        self,
        min_score: float = 0.5,
        top_n: Optional[int] = None
    ) -> List[str]:
        """
        获取深度扫描的候选币种列表

        This is the main entry point for Phase 1.

        Args:
            min_score: 最低异常评分
            top_n: 只返回前N个 (None=返回所有符合条件的)

        Returns:
            候选币种symbol列表
        """
        self.logger.info("执行Light Scan - 全量快速筛选...")

        # 1. 获取所有快照
        snapshots = await self.get_all_snapshots()
        self.logger.info(f"获取 {len(snapshots)} 个币种数据")

        if not snapshots:
            return []

        # 2. 筛选异常
        anomalies = self.screen_anomalies(snapshots, min_score=min_score)

        # 3. 取top_n
        if top_n:
            anomalies = anomalies[:top_n]

        symbols = [a.symbol for a in anomalies]

        self.logger.info(
            f"Light Scan完成: 发现 {len(anomalies)} 个异常币种 "
            f"(阈值: {min_score})"
        )

        for anomaly in anomalies[:10]:  # 只显示前10个
            self.logger.debug(
                f"  {anomaly.symbol}: 评分={anomaly.total_score:.2f}, "
                f"信号={', '.join(anomaly.signals[:2])}"
            )

        return symbols


class SymbolQueue:
    """
    币种优先级队列管理

    管理三个列表:
    - active_symbols: 高频监控 (有活跃信号的)
    - watch_list: 候选观察 (筛选出的异常)
    - all_symbols: 全量列表
    """

    def __init__(self):
        self.active_symbols: Set[str] = set()
        self.watch_list: Set[str] = set()
        self.all_symbols: Set[str] = set()

        # 每个币种的扫描计数
        self.scan_counts: Dict[str, int] = {}

        # 信号历史
        self.signal_history: Dict[str, List[datetime]] = {}

    def update_active_symbols(self, symbols: List[str]):
        """更新活跃币种列表"""
        self.active_symbols.update(symbols)

        # 更新扫描计数
        for symbol in symbols:
            self.scan_counts[symbol] = self.scan_counts.get(symbol, 0) + 1

    def update_watch_list(self, symbols: List[str]):
        """更新观察列表"""
        self.watch_list.update(symbols)

    def should_deep_scan(self, symbol: str, min_interval: int = 30) -> bool:
        """
        判断是否值得深度扫描

        Args:
            symbol: 币种
            min_interval: 最小扫描间隔(秒)

        Returns:
            是否应该深度扫描
        """
        # 活跃币种优先
        if symbol in self.active_symbols:
            return True

        # 观察列表次优先
        if symbol in self.watch_list:
            # 检查扫描间隔
            last_scan = self.signal_history.get(symbol, [None])[-1]
            if last_scan:
                elapsed = (datetime.now() - last_scan).total_seconds()
                return elapsed >= min_interval
            return True

        return False

    def record_scan(self, symbol: str):
        """记录扫描时间"""
        if symbol not in self.signal_history:
            self.signal_history[symbol] = []

        self.signal_history[symbol].append(datetime.now())

        # 限制历史长度
        if len(self.signal_history[symbol]) > 100:
            self.signal_history[symbol] = self.signal_history[symbol][-100:]

    def get_priority_symbols(self, max_count: int = 20) -> List[str]:
        """
        获取按优先级排序的币种

        Priority:
        1. 活跃币种 (有信号)
        2. 观察列表 (异常候选)
        3. 扫描次数少的 (确保覆盖)
        """
        priority = []

        # 1. 活跃币种
        priority.extend(sorted(self.active_symbols))

        # 2. 观察列表 (不在活跃列表中的)
        watch_only = self.watch_list - self.active_symbols
        priority.extend(sorted(watch_only))

        # 3. 其他symbol (按扫描次数排序, 少的优先)
        other = self.all_symbols - self.active_symbols - self.watch_list
        other_sorted = sorted(other, key=lambda s: self.scan_counts.get(s, 0))
        priority.extend(other_sorted)

        return priority[:max_count]


# 全局实例
screener = MarketScreener()
