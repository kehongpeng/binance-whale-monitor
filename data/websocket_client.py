"""
WebSocket客户端 - 实时数据流
"""
import asyncio
import json
import logging
from typing import Callable, Dict, Any, Optional
import websockets

from config import config

logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    """币安WebSocket客户端"""

    FSTREAM_BASE = 'wss://fstream.binance.com/ws'
    STREAM_BASE = 'wss://stream.binance.com:9443/ws'

    def __init__(self, use_testnet: bool = False):
        self.use_testnet = use_testnet

        if use_testnet:
            self.FSTREAM_BASE = 'wss://stream.binancefuture.com/ws'
            self.STREAM_BASE = 'wss://testnet.binance.vision/ws'

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.subscriptions: Dict[str, Callable] = {}
        self.reconnect_interval = config.WS_RECONNECT_INTERVAL
        self._running = False

    async def connect(self, streams: list[str], on_message: Callable[[Dict], None]):
        """
        连接WebSocket并订阅流

        Args:
            streams: 流名称列表，如 ['btcusdt@aggTrade', 'btcusdt@markPrice']
            on_message: 消息处理回调
        """
        self._running = True
        stream_path = '/'.join(streams)
        uri = f"{self.FSTREAM_BASE}/{stream_path}"

        while self._running:
            try:
                logger.info(f'连接WebSocket: {uri}')
                async with websockets.connect(uri) as websocket:
                    self.websocket = websocket
                    self.is_connected = True
                    logger.info('WebSocket已连接')

                    async for message in websocket:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            await on_message(data)
                        except json.JSONDecodeError as e:
                            logger.error(f'解析消息失败: {e}')
                        except Exception as e:
                            logger.error(f'处理消息失败: {e}')

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f'WebSocket连接关闭: {e}')
            except Exception as e:
                logger.error(f'WebSocket错误: {e}')
            finally:
                self.is_connected = False
                self.websocket = None

            if self._running:
                logger.info(f'{self.reconnect_interval}秒后重连...')
                await asyncio.sleep(self.reconnect_interval)

    async def disconnect(self):
        """断开连接"""
        self._running = False
        if self.websocket:
            await self.websocket.close()
        logger.info('WebSocket已断开')

    async def subscribe_agg_trades(
        self,
        symbol: str,
        on_trade: Callable[[Dict], None],
        min_quantity: float = 0.0
    ):
        """
        订阅聚合交易流（检测大单）

        Args:
            symbol: 交易对
            on_trade: 交易回调
            min_quantity: 最小数量阈值（用于过滤大单）
        """
        stream_name = f"{symbol.lower()}@aggTrade"

        async def handler(data: Dict):
            if data.get('e') == 'aggTrade':
                quantity = float(data.get('q', 0))
                if quantity >= min_quantity:
                    await on_trade({
                        'symbol': data['s'],
                        'price': float(data['p']),
                        'quantity': quantity,
                        'is_buyer_maker': data['m'],
                        'timestamp': data['T'],
                        'type': 'large_sell' if data['m'] else 'large_buy'
                    })

        await self.connect([stream_name], handler)

    async def subscribe_mark_price(self, symbol: str, on_price: Callable[[Dict], None]):
        """
        订阅标记价格流

        Args:
            symbol: 交易对
            on_price: 价格回调
        """
        stream_name = f"{symbol.lower()}@markPrice"

        async def handler(data: Dict):
            if data.get('e') == 'markPriceUpdate':
                await on_price({
                    'symbol': data['s'],
                    'mark_price': float(data['p']),
                    'index_price': float(data['i']),
                    'funding_rate': float(data['r']),
                    'next_funding_time': data['T'],
                    'timestamp': data['E']
                })

        await self.connect([stream_name], handler)

    async def subscribe_klines(
        self,
        symbol: str,
        interval: str,
        on_kline: Callable[[Dict], None]
    ):
        """
        订阅K线数据

        Args:
            symbol: 交易对
            interval: 周期 (1m, 5m, 15m, 1h, 4h, 1d)
            on_kline: K线回调
        """
        stream_name = f"{symbol.lower()}@kline_{interval}"

        async def handler(data: Dict):
            if data.get('e') == 'kline':
                k = data['k']
                await on_kline({
                    'symbol': data['s'],
                    'interval': k['i'],
                    'open': float(k['o']),
                    'high': float(k['h']),
                    'low': float(k['l']),
                    'close': float(k['c']),
                    'volume': float(k['v']),
                    'is_closed': k['x'],
                    'timestamp': data['E']
                })

        await self.connect([stream_name], handler)

    async def subscribe_multi_stream(
        self,
        symbols: list[str],
        on_data: Callable[[str, Dict], None]
    ):
        """
        订阅多个交易对的聚合流

        Args:
            symbols: 交易对列表
            on_data: 数据回调 (symbol, data)
        """
        streams = [f"{s.lower()}@markPrice" for s in symbols]
        stream_name = '/'.join(streams)
        uri = f"{self.FSTREAM_BASE}/{stream_name}"

        while self._running:
            try:
                async with websockets.connect(uri) as websocket:
                    self.websocket = websocket
                    self.is_connected = True

                    async for message in websocket:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            symbol = data.get('s', '')
                            await on_data(symbol, data)
                        except Exception as e:
                            logger.error(f'处理多流消息失败: {e}')

            except Exception as e:
                logger.error(f'多流WebSocket错误: {e}')
                await asyncio.sleep(self.reconnect_interval)


# 全局WebSocket客户端
ws_client = BinanceWebSocketClient()
