"""Mock WebSocket client for testing WebSocket functionality."""

import asyncio
import json
import time
from typing import Dict, List, Any, Optional, AsyncIterator, Callable, Set
from unittest.mock import AsyncMock, Mock
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.okx_local_store.interfaces.api_client import APIClientInterface
from src.okx_local_store.config import WebSocketConfig
from src.okx_local_store.exceptions import (
    WebSocketError, WebSocketConnectionError, WebSocketAuthenticationError,
    WebSocketSubscriptionError, WebSocketTimeoutError, WebSocketDataError
)


@dataclass
class MockSubscription:
    """Mock subscription state."""
    symbol: str
    timeframes: Set[str] = field(default_factory=set)
    active: bool = False
    callback: Optional[Callable] = None


@dataclass
class MockCandle:
    """Mock candle data."""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    vol_currency: Optional[float] = None
    symbol: str = "BTC-USDT"
    timeframe: str = "1m"
    is_confirmed: bool = True


class MockWebSocketClient(APIClientInterface):
    """
    Mock WebSocket client for testing.
    
    Simulates WebSocket behavior including:
    - Connection management
    - Subscription/unsubscription
    - Data generation and callbacks
    - Error scenarios
    - Connection failures and recovery
    """
    
    def __init__(
        self,
        sandbox: bool = True,
        websocket_config: Optional[WebSocketConfig] = None,
        simulate_failures: bool = False,
        failure_rate: float = 0.1
    ):
        """
        Initialize mock WebSocket client.
        
        Args:
            simulate_failures: Whether to simulate connection failures
            failure_rate: Probability of simulated failures (0.0-1.0)
        """
        self.sandbox = sandbox
        self.config = websocket_config or WebSocketConfig()
        
        # Mock state
        self._is_connected = False
        self._subscriptions: Dict[str, MockSubscription] = {}
        self._connection_start_time: Optional[float] = None
        self._reconnect_attempts = 0
        
        # Data generation
        self._data_generators: Dict[str, asyncio.Task] = {}
        self._stop_generation = False
        
        # Failure simulation
        self.simulate_failures = simulate_failures
        self.failure_rate = failure_rate
        self._forced_disconnect = False
        
        # Tracking for test assertions
        self.connection_attempts = 0
        self.subscription_attempts = []
        self.unsubscription_attempts = []
        self.generated_data_count = 0
        self.callbacks_called = 0
        
        # Mock market data
        self._base_prices = {
            "BTC-USDT": 50000.0,
            "ETH-USDT": 3000.0,
            "SOL-USDT": 100.0
        }
        
        # Event loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def start_websocket(self) -> bool:
        """Start mock WebSocket connection."""
        self.connection_attempts += 1
        
        # Simulate connection failure
        if self.simulate_failures and self._should_simulate_failure():
            self._reconnect_attempts += 1
            raise WebSocketConnectionError(
                "Simulated connection failure",
                retry_count=self._reconnect_attempts,
                max_retries=self.config.max_reconnect_attempts
            )
        
        # Simulate connection delay
        await asyncio.sleep(0.1)
        
        self._is_connected = True
        self._connection_start_time = time.time()
        self._reconnect_attempts = 0
        self._stop_generation = False
        
        # Get current event loop
        self._loop = asyncio.get_event_loop()
        
        return True
    
    async def stop_websocket(self) -> bool:
        """Stop mock WebSocket connection."""
        self._is_connected = False
        self._stop_generation = True
        
        # Stop all data generators
        for task in self._data_generators.values():
            if not task.done():
                task.cancel()
        
        self._data_generators.clear()
        self._subscriptions.clear()
        
        return True
    
    async def subscribe_symbol(self, symbol: str, timeframes: List[str]) -> bool:
        """Subscribe to mock WebSocket updates."""
        self.subscription_attempts.append((symbol, timeframes))
        
        if not self._is_connected:
            raise WebSocketConnectionError("Not connected")
        
        # Simulate subscription failure
        if self.simulate_failures and self._should_simulate_failure():
            raise WebSocketSubscriptionError(
                f"Simulated subscription failure for {symbol}",
                symbol=symbol
            )
        
        # Create subscription
        if symbol not in self._subscriptions:
            self._subscriptions[symbol] = MockSubscription(symbol=symbol)
        
        subscription = self._subscriptions[symbol]
        subscription.timeframes.update(timeframes)
        subscription.active = True
        
        # Start data generation for this symbol/timeframe combination
        for timeframe in timeframes:
            key = f"{symbol}:{timeframe}"
            if key not in self._data_generators:
                task = asyncio.create_task(self._generate_data(symbol, timeframe))
                self._data_generators[key] = task
        
        return True
    
    async def unsubscribe_symbol(self, symbol: str, timeframes: Optional[List[str]] = None) -> bool:
        """Unsubscribe from mock WebSocket updates."""
        self.unsubscription_attempts.append((symbol, timeframes))
        
        if symbol not in self._subscriptions:
            return True
        
        subscription = self._subscriptions[symbol]
        
        if timeframes is None:
            # Unsubscribe from all timeframes
            timeframes_to_remove = list(subscription.timeframes)
        else:
            timeframes_to_remove = timeframes
        
        # Stop data generation
        for timeframe in timeframes_to_remove:
            key = f"{symbol}:{timeframe}"
            if key in self._data_generators:
                self._data_generators[key].cancel()
                del self._data_generators[key]
        
        # Update subscription
        subscription.timeframes -= set(timeframes_to_remove)
        if not subscription.timeframes:
            subscription.active = False
        
        return True
    
    async def watch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Watch mock OHLCV data."""
        if not self._is_connected:
            raise WebSocketConnectionError("Not connected")
        
        # Set up callback if provided
        if callback:
            if symbol in self._subscriptions:
                self._subscriptions[symbol].callback = callback
        
        # This is a placeholder for the async iterator
        # In practice, this would yield real-time data
        if False:  # Placeholder condition
            yield {}
    
    async def _generate_data(self, symbol: str, timeframe: str):
        """Generate mock market data."""
        try:
            base_price = self._base_prices.get(symbol, 1000.0)
            current_price = base_price
            
            # Get timeframe duration in seconds
            timeframe_seconds = self._get_timeframe_seconds(timeframe)
            
            while not self._stop_generation and self._is_connected:
                # Generate realistic price movement
                price_change = (asyncio.get_event_loop().time() % 1) * 0.002 - 0.001  # -0.1% to +0.1%
                current_price *= (1 + price_change)
                
                # Generate OHLCV data
                open_price = current_price
                high_price = current_price * (1 + abs(price_change))
                low_price = current_price * (1 - abs(price_change))
                close_price = current_price
                volume = 100.0 + (time.time() % 100)
                
                timestamp = int(time.time() * 1000)
                
                candle_data = {
                    'timestamp': timestamp,
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price,
                    'volume': volume,
                    'vol_currency': volume * close_price,
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'is_confirmed': True
                }
                
                # Call callback if subscription exists
                if symbol in self._subscriptions:
                    subscription = self._subscriptions[symbol]
                    if subscription.callback and subscription.active:
                        try:
                            if asyncio.iscoroutinefunction(subscription.callback):
                                await subscription.callback(candle_data)
                            else:
                                subscription.callback(candle_data)
                            self.callbacks_called += 1
                        except Exception as e:
                            print(f"Error in callback: {e}")
                
                self.generated_data_count += 1
                
                # Wait based on timeframe (scaled down for testing)
                await asyncio.sleep(min(timeframe_seconds / 10, 1.0))
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error generating data: {e}")
    
    def _get_timeframe_seconds(self, timeframe: str) -> int:
        """Convert timeframe to seconds."""
        timeframe_map = {
            '1m': 60,
            '3m': 180,
            '5m': 300,
            '15m': 900,
            '30m': 1800,
            '1h': 3600,
            '1H': 3600,
            '2H': 7200,
            '4H': 14400,
            '6H': 21600,
            '12H': 43200,
            '1d': 86400,
            '1D': 86400,
            '1w': 604800,
            '1W': 604800
        }
        return timeframe_map.get(timeframe, 60)
    
    def _should_simulate_failure(self) -> bool:
        """Determine if should simulate a failure."""
        import random
        return random.random() < self.failure_rate
    
    def force_disconnect(self):
        """Force a disconnection for testing."""
        self._forced_disconnect = True
        self._is_connected = False
        self._stop_generation = True
    
    def get_websocket_status(self) -> Dict[str, Any]:
        """Get mock WebSocket status."""
        connection_age = None
        if self._connection_start_time:
            connection_age = time.time() - self._connection_start_time
        
        return {
            "connected": self._is_connected,
            "authenticated": True,  # Always authenticated for public endpoints
            "reconnect_attempts": self._reconnect_attempts,
            "max_reconnect_attempts": self.config.max_reconnect_attempts,
            "connection_age_seconds": connection_age,
            "last_pong_seconds_ago": 0,  # Mock value
            "active_subscriptions": len([s for s in self._subscriptions.values() if s.active]),
            "total_subscriptions": len(self._subscriptions),
            "buffer_size": 0,  # Mock value
            "websocket_url": "wss://mock.websocket.com/ws/v5/public"
        }
    
    def is_websocket_connected(self) -> bool:
        """Check if mock WebSocket is connected."""
        return self._is_connected and not self._forced_disconnect
    
    # Mock implementations for REST API methods
    
    def get_available_symbols(self) -> List[str]:
        """Get mock available symbols."""
        return ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOT-USDT", "ADA-USDT"]
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get mock symbol info."""
        if symbol in self._base_prices:
            return {
                "symbol": symbol,
                "base": symbol.split("-")[0],
                "quote": symbol.split("-")[1],
                "active": True
            }
        return None
    
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Generate mock historical OHLCV data."""
        if symbol not in self._base_prices:
            return []
        
        base_price = self._base_prices[symbol]
        timeframe_seconds = self._get_timeframe_seconds(timeframe)
        
        # Generate historical data
        data = []
        current_time = int(time.time() * 1000)
        start_time = since.timestamp() * 1000 if since else current_time - (limit * timeframe_seconds * 1000)
        
        for i in range(limit):
            timestamp = int(start_time + (i * timeframe_seconds * 1000))
            price_variation = 0.02 * (i % 10 - 5) / 5  # ±2% variation
            price = base_price * (1 + price_variation)
            
            data.append({
                'timestamp': timestamp,
                'open': price * 0.999,
                'high': price * 1.001,
                'low': price * 0.998,
                'close': price,
                'volume': 100.0 + (i % 50),
                'vol_currency': (100.0 + (i % 50)) * price,
                'updated_at': current_time
            })
        
        return data
    
    def fetch_latest_candle(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Get mock latest candle."""
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
        """Fetch mock historical range."""
        duration = (end_time - start_time).total_seconds()
        timeframe_seconds = self._get_timeframe_seconds(timeframe)
        limit = min(int(duration / timeframe_seconds), 1000)
        
        return self.fetch_ohlcv(symbol, timeframe, since=start_time, limit=limit)
    
    def test_connection(self) -> bool:
        """Test mock connection."""
        return self._is_connected
    
    def get_exchange_status(self) -> Dict[str, Any]:
        """Get mock exchange status."""
        return {
            "status": "ok",
            "timestamp": int(time.time() * 1000)
        }


def create_mock_websocket_client(**kwargs) -> MockWebSocketClient:
    """Factory function to create mock WebSocket client."""
    return MockWebSocketClient(**kwargs)


def create_failing_websocket_client(**kwargs) -> MockWebSocketClient:
    """Factory function to create mock WebSocket client that simulates failures."""
    kwargs.setdefault('simulate_failures', True)
    kwargs.setdefault('failure_rate', 0.3)  # 30% failure rate
    return MockWebSocketClient(**kwargs)


def create_reliable_websocket_client(**kwargs) -> MockWebSocketClient:
    """Factory function to create reliable mock WebSocket client."""
    kwargs.setdefault('simulate_failures', False)
    kwargs.setdefault('failure_rate', 0.0)
    return MockWebSocketClient(**kwargs)