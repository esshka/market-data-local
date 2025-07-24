"""WebSocket API client for real-time OKX data streaming."""

import asyncio
import json
import time
import websockets
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, AsyncIterator, Callable, Set
from dataclasses import dataclass, field
from loguru import logger
import hmac
import hashlib
import base64

from .interfaces.api_client import APIClientInterface
from .config import WebSocketConfig
from .exceptions import (
    WebSocketError, WebSocketConnectionError, WebSocketAuthenticationError,
    WebSocketSubscriptionError, WebSocketTimeoutError, WebSocketDataError
)


@dataclass
class SubscriptionState:
    """Track subscription state for symbols and timeframes."""
    symbol: str
    timeframes: Set[str] = field(default_factory=set)
    active: bool = False
    last_data: Optional[datetime] = None


class WebSocketAPIClient(APIClientInterface):
    """WebSocket-based client for real-time OKX data streaming."""
    
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None, 
        sandbox: bool = True,
        websocket_config: Optional[WebSocketConfig] = None
    ):
        """
        Initialize WebSocket API client.
        
        Args:
            api_key: OKX API key (optional for public endpoints)
            api_secret: OKX API secret
            passphrase: OKX API passphrase
            sandbox: Use sandbox environment
            websocket_config: WebSocket connection configuration
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.sandbox = sandbox
        
        self.config = websocket_config or WebSocketConfig()
        
        # WebSocket connection state
        self._websocket = None
        self._connection_task = None
        self._message_handler_task = None
        self._ping_task = None
        self._is_connected = False
        self._is_authenticated = False
        
        # Connection management
        self._reconnect_attempts = 0
        self._last_pong = time.time()
        self._connection_start_time = None
        
        # Subscription management
        self._subscriptions: Dict[str, SubscriptionState] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        
        # Message buffering during reconnection
        self._message_buffer: List[Dict[str, Any]] = []
        self._buffer_enabled = True
        
        # Event loop
        self._loop = None
        
        # URLs
        if sandbox:
            self._ws_url = "wss://wspap.okx.com:8443/ws/v5/public"
            self._ws_private_url = "wss://wspap.okx.com:8443/ws/v5/private"
        else:
            self._ws_url = "wss://ws.okx.com:8443/ws/v5/public"
            self._ws_private_url = "wss://ws.okx.com:8443/ws/v5/private"
    
    def _get_timestamp(self) -> str:
        """Get current timestamp for authentication."""
        return str(int(time.time()))
    
    def _generate_signature(self, timestamp: str, method: str = "GET", request_path: str = "/users/self/verify") -> str:
        """Generate signature for WebSocket authentication."""
        if not self.api_secret:
            raise WebSocketAuthenticationError("API secret required for authentication")
        
        message = timestamp + method + request_path
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return signature

    async def start_websocket(self) -> bool:
        """Start WebSocket connection."""
        try:
            if self._is_connected:
                logger.warning("WebSocket already connected")
                return True
            
            self._loop = asyncio.get_event_loop()
            self._connection_start_time = time.time()
            
            # Connect to public WebSocket
            logger.info(f"Connecting to WebSocket: {self._ws_url}")
            
            # Use asyncio.wait_for for timeout handling with more robust error handling
            try:
                self._websocket = await asyncio.wait_for(
                    websockets.connect(
                        self._ws_url,
                        compression="deflate" if self.config.enable_compression else None,
                        ping_interval=self.config.ping_interval,
                        ping_timeout=self.config.connection_timeout,
                        close_timeout=5.0,
                        max_size=2**20,  # 1MB max message size
                        max_queue=32     # Message queue size
                    ),
                    timeout=self.config.connection_timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"WebSocket connection timeout after {self.config.connection_timeout}s")
                return False
            except (ConnectionRefusedError, OSError) as e:
                logger.error(f"WebSocket connection failed: {e}")
                return False
            
            self._is_connected = True
            self._reconnect_attempts = 0
            
            # Start message handler with error handling
            try:
                self._message_handler_task = asyncio.create_task(self._handle_messages())
                self._ping_task = asyncio.create_task(self._ping_loop())
            except Exception as e:
                logger.error(f"Failed to start WebSocket tasks: {e}")
                self._is_connected = False
                if self._websocket:
                    await self._websocket.close()
                return False
            
            logger.info("WebSocket connected successfully")
            return True
            
        except asyncio.CancelledError:
            logger.info("WebSocket connection was cancelled during startup")
            return False
        except Exception as e:
            logger.error(f"Failed to start WebSocket: {e}")
            return False
    
    async def stop_websocket(self) -> bool:
        """Stop WebSocket connection."""
        try:
            logger.info("Stopping WebSocket connection...")
            
            self._is_connected = False
            
            # Cancel tasks
            if self._ping_task and not self._ping_task.done():
                self._ping_task.cancel()
                
            if self._message_handler_task and not self._message_handler_task.done():
                self._message_handler_task.cancel()
            
            # Close WebSocket connection
            if self._websocket:
                await self._websocket.close()
                self._websocket = None
            
            # Clear state
            self._is_authenticated = False
            self._subscriptions.clear()
            self._callbacks.clear()
            
            logger.info("WebSocket stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping WebSocket: {e}")
            return False
    
    async def _handle_messages(self):
        """Handle incoming WebSocket messages."""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse WebSocket message: {e}")
                    continue
                    
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
                    continue
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            await self._handle_connection_error()
            
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            await self._handle_connection_error()
    
    async def _process_message(self, data: Dict[str, Any]):
        """Process incoming WebSocket message."""
        try:
            # Handle different message types
            if "event" in data:
                await self._handle_event_message(data)
            elif "data" in data:
                await self._handle_data_message(data)
            else:
                logger.debug(f"Unknown message format: {data}")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise WebSocketDataError(f"Message processing failed: {e}", data)
    
    async def _handle_event_message(self, data: Dict[str, Any]):
        """Handle event messages (subscription confirmations, errors, etc.)."""
        event = data.get("event")
        
        if event == "subscribe":
            # Subscription confirmation
            arg = data.get("arg", {})
            channel = arg.get("channel")
            inst_id = arg.get("instId")
            
            if channel == "candle1m":  # TODO: Handle other timeframes
                logger.info(f"Subscribed to {inst_id} candles")
                
        elif event == "error":
            # Error message
            msg = data.get("msg", "Unknown error")
            code = data.get("code", "")
            logger.error(f"WebSocket error {code}: {msg}")
            
        else:
            logger.debug(f"Unhandled event: {event}")
    
    async def _handle_data_message(self, data: Dict[str, Any]):
        """Handle data messages (OHLCV updates)."""
        try:
            arg = data.get("arg", {})
            channel = arg.get("channel", "")
            inst_id = arg.get("instId", "")
            
            if channel.startswith("candle"):
                # Extract timeframe from channel (e.g., "candle1m" -> "1m")
                timeframe = channel.replace("candle", "")
                
                # Process candle data
                candles = data.get("data", [])
                for candle_data in candles:
                    await self._process_candle_data(inst_id, timeframe, candle_data)
                    
        except Exception as e:
            logger.error(f"Error handling data message: {e}")
    
    async def _process_candle_data(self, symbol: str, timeframe: str, candle_data: List):
        """Process individual candle data."""
        try:
            # OKX WebSocket candle format: [timestamp, open, high, low, close, volume, volCcy, volCcyQuote, confirm]
            if len(candle_data) < 6:
                logger.warning(f"Invalid candle data format: {candle_data}")
                return
            
            # Convert to our standard format
            normalized_data = {
                "timestamp": int(candle_data[0]),
                "open": float(candle_data[1]),
                "high": float(candle_data[2]),
                "low": float(candle_data[3]),
                "close": float(candle_data[4]),
                "volume": float(candle_data[5]),
                "vol_currency": float(candle_data[6]) if len(candle_data) > 6 else None,
                "symbol": symbol,
                "timeframe": timeframe,
                "is_confirmed": candle_data[8] == "1" if len(candle_data) > 8 else True
            }
            
            # Execute callbacks
            callback_key = f"{symbol}:{timeframe}"
            if callback_key in self._callbacks:
                for callback in self._callbacks[callback_key]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(normalized_data)
                        else:
                            callback(normalized_data)
                    except Exception as e:
                        logger.error(f"Error in callback: {e}")
            
            # Update subscription state
            if symbol in self._subscriptions:
                self._subscriptions[symbol].last_data = datetime.now(timezone.utc)
                
        except Exception as e:
            logger.error(f"Error processing candle data: {e}")
    
    async def _ping_loop(self):
        """Send periodic pings to keep connection alive."""
        try:
            while self._is_connected:
                await asyncio.sleep(self.config.ping_interval)
                
                if self._websocket and self._is_connected:
                    try:
                        await self._websocket.ping()
                        self._last_pong = time.time()
                    except Exception as e:
                        logger.error(f"Ping failed: {e}")
                        await self._handle_connection_error()
                        break
                        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in ping loop: {e}")
    
    async def _handle_connection_error(self):
        """Handle connection errors and attempt reconnection."""
        self._is_connected = False
        
        if self._reconnect_attempts >= self.config.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts ({self.config.max_reconnect_attempts}) reached")
            return
        
        self._reconnect_attempts += 1
        
        # Calculate exponential backoff delay
        delay = min(
            self.config.reconnect_delay_base * (2 ** (self._reconnect_attempts - 1)),
            self.config.reconnect_delay_max
        )
        
        logger.info(f"Reconnecting in {delay} seconds (attempt {self._reconnect_attempts})")
        await asyncio.sleep(delay)
        
        # Attempt reconnection
        success = await self.start_websocket()
        if success:
            # Resubscribe to previous subscriptions
            await self._resubscribe_all()
    
    async def _resubscribe_all(self):
        """Resubscribe to all previous subscriptions after reconnection."""
        for symbol, state in self._subscriptions.items():
            if state.active:
                try:
                    await self.subscribe_symbol(symbol, list(state.timeframes))
                except Exception as e:
                    logger.error(f"Failed to resubscribe to {symbol}: {e}")

    # Implement abstract methods from APIClientInterface
    async def watch_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Watch OHLCV data via WebSocket."""
        # Subscribe to symbol/timeframe
        success = await self.subscribe_symbol(symbol, [timeframe])
        if not success:
            raise WebSocketSubscriptionError(f"Failed to subscribe to {symbol}:{timeframe}")
        
        # Set up callback if provided
        if callback:
            callback_key = f"{symbol}:{timeframe}"
            if callback_key not in self._callbacks:
                self._callbacks[callback_key] = []
            self._callbacks[callback_key].append(callback)
        
        # This is a placeholder - actual implementation would yield data
        # For now, we'll implement this as subscription-based
        logger.info(f"Watching {symbol} {timeframe} via WebSocket")
        
        # In a full implementation, this would be an async generator
        # yielding real-time data. For now, we'll implement via callbacks.
        if False:  # Placeholder condition
            yield {}

    async def subscribe_symbol(self, symbol: str, timeframes: List[str]) -> bool:
        """Subscribe to WebSocket updates for a symbol and timeframes."""
        try:
            if not self._is_connected:
                await self.start_websocket()
            
            # Create subscription messages for each timeframe
            for timeframe in timeframes:
                # Convert timeframe format (e.g., "1m" -> "candle1m")
                channel = f"candle{timeframe}"
                
                subscribe_msg = {
                    "op": "subscribe",
                    "args": [{
                        "channel": channel,
                        "instId": symbol
                    }]
                }
                
                await self._websocket.send(json.dumps(subscribe_msg))
                logger.info(f"Subscribed to {symbol} {timeframe}")
            
            # Update subscription state
            if symbol not in self._subscriptions:
                self._subscriptions[symbol] = SubscriptionState(symbol=symbol)
            
            self._subscriptions[symbol].timeframes.update(timeframes)
            self._subscriptions[symbol].active = True
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {symbol}: {e}")
            raise WebSocketSubscriptionError(f"Subscription failed: {e}", symbol)
    
    async def unsubscribe_symbol(self, symbol: str, timeframes: Optional[List[str]] = None) -> bool:
        """Unsubscribe from WebSocket updates for a symbol."""
        try:
            if not self._is_connected:
                return True
            
            # Determine which timeframes to unsubscribe from
            if timeframes is None:
                # Unsubscribe from all timeframes for this symbol
                if symbol in self._subscriptions:
                    timeframes = list(self._subscriptions[symbol].timeframes)
                else:
                    return True
            
            # Create unsubscription messages
            for timeframe in timeframes:
                channel = f"candle{timeframe}"
                
                unsubscribe_msg = {
                    "op": "unsubscribe",
                    "args": [{
                        "channel": channel,
                        "instId": symbol
                    }]
                }
                
                await self._websocket.send(json.dumps(unsubscribe_msg))
                logger.info(f"Unsubscribed from {symbol} {timeframe}")
            
            # Update subscription state
            if symbol in self._subscriptions:
                if timeframes:
                    self._subscriptions[symbol].timeframes -= set(timeframes)
                    if not self._subscriptions[symbol].timeframes:
                        self._subscriptions[symbol].active = False
                else:
                    self._subscriptions[symbol].active = False
                    self._subscriptions[symbol].timeframes.clear()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to unsubscribe from {symbol}: {e}")
            return False
    
    def get_websocket_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status information."""
        connection_age = None
        if self._connection_start_time:
            connection_age = time.time() - self._connection_start_time
        
        return {
            "connected": self._is_connected,
            "authenticated": self._is_authenticated,
            "reconnect_attempts": self._reconnect_attempts,
            "max_reconnect_attempts": self.config.max_reconnect_attempts,
            "connection_age_seconds": connection_age,
            "last_pong_seconds_ago": time.time() - self._last_pong,
            "active_subscriptions": len([s for s in self._subscriptions.values() if s.active]),
            "total_subscriptions": len(self._subscriptions),
            "buffer_size": len(self._message_buffer),
            "websocket_url": self._ws_url
        }
    
    def is_websocket_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._is_connected
    
    # Placeholder implementations for REST API methods
    # (These would typically delegate to a REST client)
    
    def get_available_symbols(self) -> List[str]:
        """Get all available trading symbols."""
        # This should delegate to REST API client
        raise NotImplementedError("Use REST API client for symbol lookup")
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a trading symbol."""
        # This should delegate to REST API client
        raise NotImplementedError("Use REST API client for symbol info")
    
    def fetch_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        since: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV data from the API."""
        # This should delegate to REST API client
        raise NotImplementedError("Use REST API client for historical data")
    
    def fetch_latest_candle(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest candle for a symbol and timeframe."""
        # This should delegate to REST API client
        raise NotImplementedError("Use REST API client for latest candle")
    
    def fetch_historical_range(
        self, 
        symbol: str, 
        timeframe: str, 
        start_time: datetime, 
        end_time: datetime,
        max_requests: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch historical data for a specific time range."""
        # This should delegate to REST API client
        raise NotImplementedError("Use REST API client for historical range")
    
    def test_connection(self) -> bool:
        """Test if the API connection is working."""
        return self._is_connected
    
    def get_exchange_status(self) -> Dict[str, Any]:
        """Get exchange status information."""
        # This should delegate to REST API client
        raise NotImplementedError("Use REST API client for exchange status")