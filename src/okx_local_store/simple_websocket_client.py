"""Minimal WebSocket client for OKX real-time data streaming."""

import asyncio
import json
import time
import websockets
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, Set
from enum import Enum
from dataclasses import dataclass, field
from loguru import logger

from .config import WebSocketConfig
from .exceptions import (
    WebSocketError, WebSocketConnectionError, WebSocketSubscriptionError
)


class ConnectionState(Enum):
    """Simple connection state machine."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class Subscription:
    """Track active subscriptions."""
    symbol: str
    timeframes: Set[str]
    callback: Callable[[Dict[str, Any]], None]
    last_data: Optional[datetime] = None


class SimpleWebSocketClient:
    """Minimal WebSocket client for OKX real-time data streaming."""
    
    def __init__(
        self,
        sandbox: bool = True,
        websocket_config: Optional[WebSocketConfig] = None
    ):
        """Initialize simplified WebSocket client."""
        self.config = websocket_config or WebSocketConfig()
        self.base_url = (
            "wss://wspap.okx.com:8443/ws/v5/business" if not sandbox 
            else "wss://ws.okx.com:8443/ws/v5/business"
        )
        
        # Simple state
        self.state = ConnectionState.DISCONNECTED
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.subscriptions: Dict[str, Subscription] = {}
        
        # Connection management
        self.connection_task: Optional[asyncio.Task] = None
        self.message_task: Optional[asyncio.Task] = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = self.config.max_reconnect_attempts
        
        # Statistics
        self.messages_received = 0
        self.last_message_time = 0.0

    async def connect(self) -> bool:
        """Connect to WebSocket."""
        if self.state in [ConnectionState.CONNECTED, ConnectionState.CONNECTING]:
            return True
            
        self.state = ConnectionState.CONNECTING
        
        try:
            logger.info(f"Connecting to {self.base_url}")
            self.websocket = await websockets.connect(
                self.base_url,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
                open_timeout=self.config.connection_timeout,
                close_timeout=10  # Use fixed close timeout since it's not in config
            )
            
            self.state = ConnectionState.CONNECTED
            self.reconnect_attempts = 0
            
            # Start message processing
            self.message_task = asyncio.create_task(self._message_loop())
            
            logger.info("WebSocket connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.state = ConnectionState.DISCONNECTED
            raise WebSocketConnectionError(f"Connection failed: {e}")

    async def disconnect(self):
        """Disconnect WebSocket."""
        self.state = ConnectionState.DISCONNECTED
        
        # Cancel tasks
        if self.message_task:
            self.message_task.cancel()
            try:
                await self.message_task
            except asyncio.CancelledError:
                pass
                
        # Close WebSocket
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        logger.info("WebSocket disconnected")

    async def subscribe(
        self,
        symbol: str,
        timeframes: List[str],
        callback: Callable[[Dict[str, Any]], None]
    ) -> bool:
        """Subscribe to symbol data with callback."""
        if self.state != ConnectionState.CONNECTED:
            if not await self.connect():
                return False
        
        # Create subscription
        sub_key = f"{symbol}:{':'.join(sorted(timeframes))}"
        self.subscriptions[sub_key] = Subscription(
            symbol=symbol,
            timeframes=set(timeframes),
            callback=callback
        )
        
        # Send subscription message for each timeframe
        for timeframe in timeframes:
            # Map timeframe to OKX WebSocket channel format
            channel = self._get_okx_channel(timeframe)
            message = {
                "op": "subscribe",
                "args": [{
                    "channel": channel,
                    "instId": symbol
                }]
            }
            
            try:
                await self.websocket.send(json.dumps(message))
                logger.debug(f"Subscribed to {symbol} {timeframe}")
            except Exception as e:
                logger.error(f"Subscription failed for {symbol} {timeframe}: {e}")
                return False
        
        return True

    async def unsubscribe(self, symbol: str, timeframes: List[str]) -> bool:
        """Unsubscribe from symbol data."""
        if self.state != ConnectionState.CONNECTED:
            return False
        
        # Remove subscription
        sub_key = f"{symbol}:{':'.join(sorted(timeframes))}"
        if sub_key in self.subscriptions:
            del self.subscriptions[sub_key]
        
        # Send unsubscription message
        for timeframe in timeframes:
            # Map timeframe to OKX WebSocket channel format
            channel = self._get_okx_channel(timeframe)
            message = {
                "op": "unsubscribe", 
                "args": [{
                    "channel": channel,
                    "instId": symbol
                }]
            }
            
            try:
                await self.websocket.send(json.dumps(message))
                logger.debug(f"Unsubscribed from {symbol} {timeframe}")
            except Exception as e:
                logger.error(f"Unsubscription failed for {symbol} {timeframe}: {e}")
                return False
        
        return True

    async def _message_loop(self):
        """Main message processing loop."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                    
                    self.messages_received += 1
                    self.last_message_time = time.time()
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON received: {e}")
                except Exception as e:
                    logger.error(f"Message processing error: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            await self._handle_disconnect()
        except Exception as e:
            logger.error(f"Message loop error: {e}")
            await self._handle_disconnect()

    async def _process_message(self, data: Dict[str, Any]):
        """Process incoming WebSocket message."""
        # Handle subscription confirmations
        if data.get("event") == "subscribe":
            logger.info(f"Subscription confirmed: {data.get('arg', {})}")
            return
            
        # Handle errors
        if data.get("event") == "error":
            error_msg = data.get("msg", "Unknown error")
            logger.error(f"WebSocket error: {error_msg}")
            return
        
        # Handle data messages
        if "data" in data and data["data"]:
            arg = data.get("arg", {})
            channel = arg.get("channel", "")
            inst_id = arg.get("instId", "")
            
            if channel.startswith("candle") and inst_id:
                # Extract timeframe from OKX channel format
                timeframe = self._get_timeframe_from_channel(channel)
                
                if not timeframe:
                    logger.warning(f"Could not extract timeframe from channel: {channel}")
                    return
                
                # Find matching subscription
                for sub in self.subscriptions.values():
                    if sub.symbol == inst_id and timeframe in sub.timeframes:
                        # Parse candle data
                        for candle_data in data["data"]:
                            ohlcv = self._parse_candle_data(candle_data, inst_id, timeframe)
                            if ohlcv:
                                # Update subscription timestamp
                                sub.last_data = datetime.now(timezone.utc)
                                
                                # Call callback
                                try:
                                    sub.callback(ohlcv)
                                except Exception as e:
                                    logger.error(f"Callback error for {inst_id}: {e}")

    def _parse_candle_data(self, candle_data: List[str], symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Parse OKX candle data format."""
        try:
            if len(candle_data) < 6:
                return None
                
            timestamp = int(candle_data[0])
            open_price = float(candle_data[1])
            high_price = float(candle_data[2])
            low_price = float(candle_data[3])
            close_price = float(candle_data[4])
            volume = float(candle_data[5])
            
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": timestamp,
                "datetime": datetime.fromtimestamp(timestamp / 1000, timezone.utc),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume
            }
            
        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse candle data: {e}")
            return None

    async def _handle_disconnect(self):
        """Handle connection disconnect with reconnection."""
        if self.state == ConnectionState.DISCONNECTED:
            return
            
        self.state = ConnectionState.RECONNECTING
        self.websocket = None
        
        # Attempt reconnection
        while (self.state == ConnectionState.RECONNECTING and 
               self.reconnect_attempts < self.max_reconnect_attempts):
            
            self.reconnect_attempts += 1
            wait_time = min(2 ** self.reconnect_attempts, 60)  # Exponential backoff
            
            logger.info(f"Reconnecting in {wait_time}s (attempt {self.reconnect_attempts})")
            await asyncio.sleep(wait_time)
            
            try:
                if await self.connect():
                    # Resubscribe to all channels
                    await self._resubscribe_all()
                    return
            except Exception as e:
                logger.error(f"Reconnection attempt {self.reconnect_attempts} failed: {e}")
        
        # Max attempts reached
        logger.error("Max reconnection attempts reached, giving up")
        self.state = ConnectionState.DISCONNECTED

    async def _resubscribe_all(self):
        """Resubscribe to all active subscriptions after reconnection."""
        for sub in self.subscriptions.values():
            try:
                await self.subscribe(sub.symbol, list(sub.timeframes), sub.callback)
            except Exception as e:
                logger.error(f"Failed to resubscribe to {sub.symbol}: {e}")

    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.state == ConnectionState.CONNECTED

    def _get_okx_channel(self, timeframe: str) -> str:
        """Map internal timeframe to OKX WebSocket channel format."""
        # OKX WebSocket channels use specific formats
        okx_channel_mapping = {
            '1m': 'candle1m',
            '3m': 'candle3m', 
            '5m': 'candle5m',
            '15m': 'candle15m',
            '30m': 'candle30m',
            '1h': 'candle1H',  # Note: OKX uses uppercase H
            '1H': 'candle1H',
            '2H': 'candle2H',
            '4H': 'candle4H', 
            '6H': 'candle6H',
            '12H': 'candle12H',
            '1d': 'candle1D',  # Note: OKX uses uppercase D
            '1D': 'candle1D',
            '1w': 'candle1W',  # Note: OKX uses uppercase W
            '1W': 'candle1W',
            '1M': 'candle1M',
            '3M': 'candle3M'
        }
        
        okx_channel = okx_channel_mapping.get(timeframe)
        if not okx_channel:
            logger.warning(f"Unknown timeframe {timeframe}, using candle{timeframe}")
            okx_channel = f"candle{timeframe}"
            
        return okx_channel

    def _get_timeframe_from_channel(self, channel: str) -> Optional[str]:
        """Extract timeframe from OKX WebSocket channel."""
        if not channel.startswith("candle"):
            return None
            
        # Extract timeframe part (e.g., "candle1H" -> "1H")
        okx_timeframe = channel.replace("candle", "")
        
        # Map back to internal format
        internal_mapping = {
            '1m': '1m',
            '3m': '3m',
            '5m': '5m', 
            '15m': '15m',
            '30m': '30m',
            '1H': '1h',  # Map OKX 1H back to internal 1h
            '2H': '2H',
            '4H': '4H',
            '6H': '6H',
            '12H': '12H',
            '1D': '1d',  # Map OKX 1D back to internal 1d
            '1W': '1w',  # Map OKX 1W back to internal 1w
            '1M': '1M',
            '3M': '3M'
        }
        
        return internal_mapping.get(okx_timeframe, okx_timeframe)

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "state": self.state.value,
            "messages_received": self.messages_received,
            "last_message_time": self.last_message_time,
            "subscriptions": len(self.subscriptions),
            "reconnect_attempts": self.reconnect_attempts
        }