"""
告警管理器 - 信号阈值判断和告警推送
"""
import logging
import asyncio
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

from config import config
from signals.calculator import SignalResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    """告警对象"""
    id: str
    symbol: str
    alert_type: str  # 'distribution', 'accumulation'
    severity: str  # 'strong', 'medium', 'weak'
    message: str
    timestamp: datetime
    signal_data: Dict[str, Any]


@dataclass
class AlertConfig:
    """告警配置"""
    enabled: bool = True
    min_confidence: str = 'weak'  # 'strong', 'medium', 'weak'
    dedup_minutes: int = config.ALERT_DEDUP_MINUTES

    # 渠道配置
    console_enabled: bool = True
    telegram_enabled: bool = False
    telegram_bot_token: str = ''
    telegram_chat_id: str = ''
    webhook_enabled: bool = False
    webhook_url: str = ''


class AlertManager:
    """告警管理器"""

    CONFIDENCE_LEVELS = {
        'strong': 3,
        'medium': 2,
        'weak': 1,
        'none': 0
    }

    def __init__(self, alert_config: Optional[AlertConfig] = None):
        self.config = alert_config or AlertConfig()
        self.alert_history: List[Alert] = []
        self.last_alert_time: Dict[str, datetime] = defaultdict(
            lambda: datetime.min
        )
        self.handlers: List[Callable[[Alert], None]] = []

        # 注册默认处理器
        if self.config.console_enabled:
            self.add_handler(self._console_handler)

    def add_handler(self, handler: Callable[[Alert], None]):
        """添加告警处理器"""
        self.handlers.append(handler)

    def remove_handler(self, handler: Callable[[Alert], None]):
        """移除告警处理器"""
        if handler in self.handlers:
            self.handlers.remove(handler)

    def _should_alert(self, symbol: str, confidence: str) -> bool:
        """
        判断是否应当触发告警（去重逻辑）

        Args:
            symbol: 交易对
            confidence: 信号置信度

        Returns:
            是否应当告警
        """
        if not self.config.enabled:
            return False

        # 检查置信度阈值
        if self.CONFIDENCE_LEVELS[confidence] < self.CONFIDENCE_LEVELS[self.config.min_confidence]:
            return False

        # 检查去重时间
        last_time = self.last_alert_time[symbol]
        cooldown = timedelta(minutes=self.config.dedup_minutes)

        if datetime.now() - last_time < cooldown:
            return False

        return True

    def _generate_alert_id(self, symbol: str, alert_type: str) -> str:
        """生成告警ID"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        return f"{symbol}_{alert_type}_{timestamp}"

    def _format_alert_message(self, signal: SignalResult) -> str:
        """格式化告警消息"""
        emoji_map = {
            'distribution': '🚨',
            'accumulation': '💎',
            'none': '➖'
        }

        type_map = {
            'distribution': '【主力出货】',
            'accumulation': '【主力吸筹】',
            'none': '【无信号】'
        }

        emoji = emoji_map.get(signal.signal_type, '⚠️')
        type_str = type_map.get(signal.signal_type, '【未知】')

        message = f"""
{emoji} {type_str} {signal.symbol}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 信号强度: {signal.signal_strength:.2%} ({signal.confidence})
📈 OI变化: {signal.oi_change_rate:+.2f}%
💰 资金费率: {signal.funding_rate:.4%}
📉 期现价差: {signal.basis_rate:.3f}%
🌊 现货流向: {signal.spot_flow_signal}

🔍 详细评分:
  • OI分量: {signal.oi_score:.2f}
  • 资金费率分量: {signal.funding_score:.2f}
  • 基差分量: {signal.basis_score:.2f}
  • 流向分量: {signal.flow_score:.2f}

⏰ 时间: {signal.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
"""
        return message.strip()

    def process_signal(self, signal: SignalResult) -> Optional[Alert]:
        """
        处理信号，生成告警

        Args:
            signal: 信号结果

        Returns:
            告警对象（如果不触发则返回None）
        """
        if signal.signal_type == 'none':
            return None

        if not self._should_alert(signal.symbol, signal.confidence):
            return None

        # 创建告警
        alert = Alert(
            id=self._generate_alert_id(signal.symbol, signal.signal_type),
            symbol=signal.symbol,
            alert_type=signal.signal_type,
            severity=signal.confidence,
            message=self._format_alert_message(signal),
            timestamp=signal.timestamp,
            signal_data={
                'signal_strength': signal.signal_strength,
                'oi_change_rate': signal.oi_change_rate,
                'funding_rate': signal.funding_rate,
                'basis_rate': signal.basis_rate,
                'spot_flow_signal': signal.spot_flow_signal,
                'oi_score': signal.oi_score,
                'funding_score': signal.funding_score,
                'basis_score': signal.basis_score,
                'flow_score': signal.flow_score
            }
        )

        # 更新最后告警时间
        self.last_alert_time[signal.symbol] = signal.timestamp

        # 添加到历史
        self.alert_history.append(alert)

        # 限制历史大小
        if len(self.alert_history) > 1000:
            self.alert_history = self.alert_history[-1000:]

        # 触发处理器
        for handler in self.handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f'告警处理器执行失败: {e}')

        return alert

    def process_signals_batch(self, signals: List[SignalResult]) -> List[Alert]:
        """
        批量处理信号

        Args:
            signals: 信号结果列表

        Returns:
            触发的告警列表
        """
        alerts = []
        for signal in signals:
            alert = self.process_signal(signal)
            if alert:
                alerts.append(alert)
        return alerts

    # ========== 告警处理器 ==========

    def _console_handler(self, alert: Alert):
        """控制台告警处理器"""
        print(f"\n{'=' * 60}")
        print(alert.message)
        print(f"{'=' * 60}\n")
        logger.info(f'告警触发: {alert.symbol} - {alert.alert_type}')

    async def _telegram_handler(self, alert: Alert):
        """Telegram告警处理器"""
        if not self.config.telegram_enabled:
            return

        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            payload = {
                'chat_id': self.config.telegram_chat_id,
                'text': alert.message,
                'parse_mode': 'HTML'
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        logger.error(f'Telegram发送失败: {await response.text()}')

        except Exception as e:
            logger.error(f'Telegram告警失败: {e}')

    async def _webhook_handler(self, alert: Alert):
        """Webhook告警处理器"""
        if not self.config.webhook_enabled:
            return

        try:
            import aiohttp

            payload = {
                'id': alert.id,
                'symbol': alert.symbol,
                'type': alert.alert_type,
                'severity': alert.severity,
                'message': alert.message,
                'timestamp': alert.timestamp.isoformat(),
                'data': alert.signal_data
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.config.webhook_url,
                    json=payload
                ) as response:
                    if response.status >= 400:
                        logger.error(f'Webhook发送失败: {await response.text()}')

        except Exception as e:
            logger.error(f'Webhook告警失败: {e}')

    # ========== 查询方法 ==========

    def get_recent_alerts(
        self,
        symbol: Optional[str] = None,
        alert_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Alert]:
        """
        获取最近告警

        Args:
            symbol: 过滤交易对
            alert_type: 过滤类型
            limit: 返回数量

        Returns:
            告警列表
        """
        alerts = self.alert_history

        if symbol:
            alerts = [a for a in alerts if a.symbol == symbol]

        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]

        return sorted(alerts, key=lambda x: x.timestamp, reverse=True)[:limit]

    def get_alert_stats(self) -> Dict[str, Any]:
        """获取告警统计"""
        if not self.alert_history:
            return {
                'total_alerts': 0,
                'distribution_count': 0,
                'accumulation_count': 0,
                'by_symbol': {},
                'by_severity': {}
            }

        total = len(self.alert_history)
        distribution = sum(1 for a in self.alert_history if a.alert_type == 'distribution')
        accumulation = sum(1 for a in self.alert_history if a.alert_type == 'accumulation')

        by_symbol = defaultdict(int)
        by_severity = defaultdict(int)

        for alert in self.alert_history:
            by_symbol[alert.symbol] += 1
            by_severity[alert.severity] += 1

        return {
            'total_alerts': total,
            'distribution_count': distribution,
            'accumulation_count': accumulation,
            'by_symbol': dict(by_symbol),
            'by_severity': dict(by_severity)
        }


# 全局告警管理器
alert_manager = AlertManager()
