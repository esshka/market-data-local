"""OKX API client using CCXT for fetching OHLCV data."""

import ccxt
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple, Callable, AsyncIterator
from loguru import logger
import pandas as pd

from .interfaces.api_client import APIClientInterface
from .utils.timeframes import get_timeframe_duration_ms
from .exceptions import APIError, RateLimitError, ConnectionError


class OKXAPIClient(APIClientInterface):
    """CCXT-based client for OKX API operations."""
    
    def __init__(self, sandbox: bool = True, rate_limit_per_minute: int = 240):
        """
        Initialize OKX API client for public endpoints only.
        
        Args:
            sandbox: Use sandbox environment
            rate_limit_per_minute: Maximum requests per minute
        """
        self.exchange = ccxt.okx({
            'sandbox': sandbox,
            'rateLimit': 250,  # Milliseconds between requests
            'enableRateLimit': True,
        })
        
        self._last_request_time = 0
        self._request_count = 0
        self._rate_limit_window_start = time.time()
        self._max_requests_per_minute = rate_limit_per_minute

    def _check_rate_limit(self):
        """Ensure we don't exceed rate limits."""
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self._rate_limit_window_start > 60:
            self._request_count = 0
            self._rate_limit_window_start = current_time
        
        # If we're approaching the limit, wait
        if self._request_count >= self._max_requests_per_minute:
            sleep_time = 60 - (current_time - self._rate_limit_window_start)
            if sleep_time > 0:
                logger.info(f"Rate limit reached, sleeping for {sleep_time:.1f} seconds")
                time.sleep(sleep_time)
                self._request_count = 0
                self._rate_limit_window_start = time.time()
            else:
                # Reset if window has passed
                self._request_count = 0
                self._rate_limit_window_start = current_time
        
        self._request_count += 1

    def get_available_symbols(self) -> List[str]:
        """Get all available trading symbols from OKX."""
        try:
            self._check_rate_limit()
            markets = self.exchange.load_markets()
            symbols = [symbol for symbol in markets.keys() if markets[symbol]['active']]
            logger.info(f"Retrieved {len(symbols)} available symbols")
            return symbols
        except Exception as e:
            logger.error(f"Error fetching available symbols: {e}")
            raise APIError(f"Failed to fetch available symbols: {e}")

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a trading symbol."""
        try:
            self._check_rate_limit()
            markets = self.exchange.load_markets()
            if symbol in markets:
                return markets[symbol]
            else:
                logger.warning(f"Symbol {symbol} not found")
                return None
        except Exception as e:
            logger.error(f"Error fetching symbol info for {symbol}: {e}")
            raise APIError(f"Failed to fetch symbol info for {symbol}: {e}")

    def fetch_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        since: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV data from OKX API.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-USDT')
            timeframe: Candlestick timeframe (e.g., '1m', '1h', '1d')
            since: Start datetime (UTC)
            limit: Maximum number of candles to fetch (max 1000)
        
        Returns:
            List of OHLCV dictionaries
        """
        try:
            self._check_rate_limit()
            
            # Convert since to milliseconds timestamp
            since_ms = None
            if since:
                since_ms = int(since.timestamp() * 1000)
            
            # Fetch OHLCV data
            ohlcv_data = self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since_ms,
                limit=min(limit, 1000)  # OKX max limit is typically 1000
            )
            
            # Convert to our standard format
            candles = []
            for ohlcv in ohlcv_data:
                candles.append({
                    'timestamp': ohlcv[0],  # Timestamp in milliseconds
                    'open': ohlcv[1],
                    'high': ohlcv[2],
                    'low': ohlcv[3],
                    'close': ohlcv[4],
                    'volume': ohlcv[5],
                    'vol_currency': ohlcv[5] * ohlcv[4] if len(ohlcv) < 7 else ohlcv[6]  # Volume in quote currency
                })
            
            logger.info(f"Fetched {len(candles)} candles for {symbol} {timeframe}")
            return candles
            
        except Exception as e:
            logger.error(f"Error fetching OHLCV data for {symbol} {timeframe}: {e}")
            raise APIError(f"Failed to fetch OHLCV data for {symbol} {timeframe}: {e}")

    def fetch_latest_candle(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest candle for a symbol and timeframe."""
        candles = self.fetch_ohlcv(symbol, timeframe, limit=1)
        return candles[0] if candles else None

    def fetch_historical_range(
        self, 
        symbol: str, 
        timeframe: str, 
        start_time: datetime, 
        end_time: datetime,
        max_requests: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical data for a specific time range.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            start_time: Start datetime (UTC)
            end_time: End datetime (UTC)
            max_requests: Maximum number of API requests to make
        
        Returns:
            List of OHLCV dictionaries covering the requested range
        """
        all_candles = []
        current_time = start_time
        request_count = 0
        
        # Get timeframe duration using centralized utility
        tf_ms = get_timeframe_duration_ms(timeframe)
        
        while current_time < end_time and request_count < max_requests:
            # Calculate how many candles we can fetch in one request
            remaining_time_ms = int((end_time - current_time).total_seconds() * 1000)
            max_candles_for_range = min(1000, remaining_time_ms // tf_ms + 1)
            
            if max_candles_for_range <= 0:
                break
            
            candles = self.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=current_time,
                limit=max_candles_for_range
            )
            
            if not candles:
                break
            
            # Filter candles within our time range
            for candle in candles:
                candle_time = datetime.fromtimestamp(candle['timestamp'] / 1000, tz=timezone.utc)
                if start_time <= candle_time <= end_time:
                    all_candles.append(candle)
            
            # Move to next batch
            if candles:
                last_candle_time = datetime.fromtimestamp(candles[-1]['timestamp'] / 1000, tz=timezone.utc)
                current_time = last_candle_time + timedelta(milliseconds=tf_ms)
            else:
                break
            
            request_count += 1
            
            # Add small delay between requests
            time.sleep(0.1)
        
        # Remove duplicates and sort
        unique_candles = {}
        for candle in all_candles:
            unique_candles[candle['timestamp']] = candle
        
        sorted_candles = sorted(unique_candles.values(), key=lambda x: x['timestamp'])
        
        logger.info(f"Fetched {len(sorted_candles)} historical candles for {symbol} {timeframe} "
                   f"from {start_time} to {end_time} in {request_count} requests")
        
        return sorted_candles

    def get_timeframe_duration_ms(self, timeframe: str) -> int:
        """Get the duration of a timeframe in milliseconds."""
        return get_timeframe_duration_ms(timeframe)

    def test_connection(self) -> bool:
        """Test if the API connection is working."""
        try:
            self._check_rate_limit()
            # Try to fetch server time or basic market info
            self.exchange.load_markets()
            logger.info("OKX API connection test successful")
            return True
        except Exception as e:
            logger.error(f"OKX API connection test failed: {e}")
            raise ConnectionError(f"API connection test failed: {e}")

    def get_exchange_status(self) -> Dict[str, Any]:
        """Get exchange status information."""
        try:
            self._check_rate_limit()
            status = self.exchange.fetch_status()
            return {
                'status': status.get('status', 'unknown'),
                'updated': datetime.now(timezone.utc)
            }
        except Exception as e:
            logger.error(f"Error fetching exchange status: {e}")
            raise APIError(f"Failed to fetch exchange status: {e}")

    # WebSocket stub methods (not implemented in REST-only client)
    async def watch_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> None:
        """WebSocket OHLCV streaming not supported in REST-only client."""
        raise NotImplementedError(
            "WebSocket functionality not available in REST-only API client. "
            "Use WebSocketAPIClient or configure realtime_mode='hybrid' for WebSocket support."
        )
    
    async def subscribe_symbol(self, symbol: str, timeframes: List[str]) -> bool:
        """WebSocket symbol subscription not supported in REST-only client."""
        raise NotImplementedError(
            "WebSocket functionality not available in REST-only API client. "
            "Use WebSocketAPIClient or configure realtime_mode='hybrid' for WebSocket support."
        )
    
    async def unsubscribe_symbol(self, symbol: str, timeframes: Optional[List[str]] = None) -> bool:
        """WebSocket symbol unsubscription not supported in REST-only client."""
        raise NotImplementedError(
            "WebSocket functionality not available in REST-only API client. "
            "Use WebSocketAPIClient or configure realtime_mode='hybrid' for WebSocket support."
        )
    
    def get_websocket_status(self) -> Dict[str, Any]:
        """Get WebSocket status (always disconnected for REST-only client)."""
        return {
            'connected': False,
            'client_type': 'REST-only',
            'message': 'WebSocket not available in REST-only API client'
        }
    
    async def start_websocket(self) -> bool:
        """WebSocket start not supported in REST-only client."""
        raise NotImplementedError(
            "WebSocket functionality not available in REST-only API client. "
            "Use WebSocketAPIClient or configure realtime_mode='hybrid' for WebSocket support."
        )
    
    async def stop_websocket(self) -> bool:
        """WebSocket stop not supported in REST-only client."""
        raise NotImplementedError(
            "WebSocket functionality not available in REST-only API client. "
            "Use WebSocketAPIClient or configure realtime_mode='hybrid' for WebSocket support."
        )
    
    def is_websocket_connected(self) -> bool:
        """WebSocket connection status (always False for REST-only client)."""
        return False