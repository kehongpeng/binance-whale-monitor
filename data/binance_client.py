"""
币安API客户端 - 统一封装币安API调用
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any
import aiohttp
import requests

from config import config

logger = logging.getLogger(__name__)


class BinanceAPIClient:
    """币安API客户端"""

    # API端点
    FAPI_BASE = 'https://fapi.binance.com'
    API_BASE = 'https://api.binance.com'

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        use_testnet: bool = False
    ):
        self.api_key = api_key or config.BINANCE_API_KEY
        self.api_secret = api_secret or config.BINANCE_API_SECRET
        self.use_testnet = use_testnet or config.USE_TESTNET

        if self.use_testnet:
            self.FAPI_BASE = 'https://testnet.binancefuture.com'
            self.API_BASE = 'https://testnet.binance.vision'

    def _get_futures_headers(self) -> Dict[str, str]:
        """获取期货API请求头"""
        return {
            'X-MBX-APIKEY': self.api_key
        }

    async def _async_get(self, url: str, params: Optional[Dict] = None) -> Any:
        """异步GET请求"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()

    def _sync_get(self, url: str, params: Optional[Dict] = None) -> Any:
        """同步GET请求"""
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    # ========== Open Interest (持仓量) ==========

    async def get_open_interest(self, symbol: str) -> Dict[str, Any]:
        """
        获取当前持仓量

        Args:
            symbol: 交易对，如 BTCUSDT

        Returns:
            {
                "symbol": "BTCUSDT",
                "openInterest": "10000.000",
                "time": 1589437530011
            }
        """
        url = f"{self.FAPI_BASE}/fapi/v1/openInterest"
        params = {'symbol': symbol}

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取OI失败 {symbol}: {e}')
            raise

    async def get_open_interest_hist(
        self,
        symbol: str,
        period: str = '5m',
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        获取历史持仓量数据

        Args:
            symbol: 交易对
            period: 周期 (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d)
            limit: 返回条数，默认30，最大500

        Returns:
            [
                {
                    "symbol": "BTCUSDT",
                    "sumOpenInterest": "20403.63700000",
                    "sumOpenInterestValue": "150123456.12345678",
                    "timestamp": 1583127900000
                }
            ]
        """
        url = f"{self.FAPI_BASE}/futures/data/openInterestHist"
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取历史OI失败 {symbol}: {e}')
            raise

    # ========== Funding Rate (资金费率) ==========

    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """
        获取当前资金费率

        Args:
            symbol: 交易对

        Returns:
            {
                "symbol": "BTCUSDT",
                "markPrice": "11000.00000000",
                "indexPrice": "11000.12345678",
                "estimatedSettlePrice": "11000.12345678",
                "lastFundingRate": "0.00010000",
                "interestRate": "0.00010000",
                "nextFundingTime": 1592569200000,
                "time": 1592568512000
            }
        """
        url = f"{self.FAPI_BASE}/fapi/v1/premiumIndex"
        params = {'symbol': symbol}

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取资金费率失败 {symbol}: {e}')
            raise

    async def get_funding_rate_history(
        self,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取历史资金费率

        Args:
            symbol: 交易对
            limit: 返回条数

        Returns:
            [
                {
                    "symbol": "BTCUSDT",
                    "fundingRate": "0.00010000",
                    "fundingTime": 1570608000000
                }
            ]
        """
        url = f"{self.FAPI_BASE}/fapi/v1/fundingRate"
        params = {
            'symbol': symbol,
            'limit': limit
        }

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取历史资金费率失败 {symbol}: {e}')
            raise

    # ========== Price Data (价格数据) ==========

    async def get_mark_price(self, symbol: str) -> Dict[str, Any]:
        """获取期货标记价格"""
        url = f"{self.FAPI_BASE}/fapi/v1/premiumIndex"
        params = {'symbol': symbol}

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取标记价格失败 {symbol}: {e}')
            raise

    async def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        """获取现货价格"""
        url = f"{self.API_BASE}/api/v3/ticker/price"
        params = {'symbol': symbol}

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取现货价格失败 {symbol}: {e}')
            raise

    # ========== Long/Short Ratio (多空比) ==========

    async def get_long_short_ratio(
        self,
        symbol: str,
        period: str = '5m',
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        获取大户账户多空比

        Args:
            symbol: 交易对
            period: 周期
            limit: 返回条数

        Returns:
            [
                {
                    "symbol": "BTCUSDT",
                    "longShortRatio": "0.1960",
                    "longAccount": "0.6622",
                    "shortAccount": "0.3378",
                    "timestamp": 1592870400000
                }
            ]
        """
        url = f"{self.FAPI_BASE}/futures/data/topLongShortAccountRatio"
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取多空比失败 {symbol}: {e}')
            raise

    async def get_global_long_short_ratio(
        self,
        symbol: str,
        period: str = '5m',
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """获取全账户多空比"""
        url = f"{self.FAPI_BASE}/futures/data/globalLongShortAccountRatio"
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取全局多空比失败 {symbol}: {e}')
            raise

    # ========== Taker Buy/Sell Volume (买卖量) ==========

    async def get_taker_volume(
        self,
        symbol: str,
        period: str = '5m',
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        获取主动买卖量

        Returns:
            [
                {
                    "buySellRatio": "1.000",
                    "sellVol": "2000.000",
                    "buyVol": "2000.000",
                    "timestamp": 1591251300000
                }
            ]
        """
        url = f"{self.FAPI_BASE}/futures/data/takerBuySellVol"
        params = {
            'symbol': symbol,
            'period': period,
            'limit': limit
        }

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取买卖量失败 {symbol}: {e}')
            raise

    # ========== Liquidation Data (强平数据) ==========

    async def get_liquidation_orders(
        self,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取强平订单数据

        Returns:
            [
                {
                    "symbol": "BTCUSDT",
                    "price": "9425.23",
                    "origQty": "0.501",
                    "executedQty": "0.501",
                    "averagePrice": "9425.23",
                    "status": "FILLED",
                    "timeInForce": "IOC",
                    "type": "LIMIT",
                    "side": "SELL",
                    "time": 1591440469120
                }
            ]
        """
        url = f"{self.FAPI_BASE}/fapi/v1/forceOrders"
        params = {
            'symbol': symbol,
            'limit': limit
        }

        try:
            return await self._async_get(url, params)
        except Exception as e:
            logger.error(f'获取强平数据失败 {symbol}: {e}')
            raise

    # ========== Batch Operations (批量操作) ==========

    async def get_all_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        获取单个交易对的所有市场数据

        Returns:
            包含OI、资金费率、价格、多空比等的综合数据
        """
        try:
            # 并行获取所有数据
            oi_task = self.get_open_interest(symbol)
            funding_task = self.get_funding_rate(symbol)
            mark_price_task = self.get_mark_price(symbol)
            spot_price_task = self.get_spot_price(symbol)
            ratio_task = self.get_long_short_ratio(symbol, limit=1)

            oi, funding, mark_price, spot_price, ratio = await asyncio.gather(
                oi_task,
                funding_task,
                mark_price_task,
                spot_price_task,
                ratio_task,
                return_exceptions=True
            )

            return {
                'symbol': symbol,
                'open_interest': oi if not isinstance(oi, Exception) else None,
                'funding_rate': funding if not isinstance(funding, Exception) else None,
                'mark_price': mark_price if not isinstance(mark_price, Exception) else None,
                'spot_price': spot_price if not isinstance(spot_price, Exception) else None,
                'long_short_ratio': ratio[0] if not isinstance(ratio, Exception) and ratio else None,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f'获取综合数据失败 {symbol}: {e}')
            raise


# 全局客户端实例
client = BinanceAPIClient()
