"""Isolated WebSocket service with async task and queue architecture."""

import asyncio
import json
import time
import websockets
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, Set
from dataclasses import dataclass, field
from loguru import logger
import hmac
import hashlib
import base64

from ..interfaces.api_client import RealtimeClientInterface
from ..config import WebSocketConfig
from ..exceptions import (
    WebSocketError, WebSocketConnectionError, WebSocketAuthenticationError,
    WebSocketSubscriptionError, WebSocketTimeoutError, WebSocketDataError
)


@dataclass
class WebSocketMessage:
    """Represents a WebSocket message for queue processing."""
    message_type: str  # 'event', 'data', 'control'
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass 
class SubscriptionRequest:
    """Represents a subscription request for queue processing."""
    action: str  # 'subscribe', 'unsubscribe'
    symbol: str
    timeframes: List[str]
    callback: Optional[Callable] = None


class WebSocketService:
    """Isolated WebSocket service using async tasks and queues."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        sandbox: bool = True,
        websocket_config: Optional[WebSocketConfig] = None
    ):
        """Initialize WebSocket service with async task architecture."""
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.sandbox = sandbox
        
        self.config = websocket_config or WebSocketConfig()
        
        # Async queues for decoupled processing
        self._message_queue: asyncio.Queue[WebSocketMessage] = asyncio.Queue()
        self._subscription_queue: asyncio.Queue[SubscriptionRequest] = asyncio.Queue()
        self._outbound_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        
        # Connection state
        self._websocket = None
        self._is_connected = False
        self._is_authenticated = False
        
        # Async tasks for isolated processing
        self._connection_task: Optional[asyncio.Task] = None
        self._message_processor_task: Optional[asyncio.Task] = None
        self._subscription_processor_task: Optional[asyncio.Task] = None
        self._outbound_processor_task: Optional[asyncio.Task] = None
        self._health_monitor_task: Optional[asyncio.Task] = None
        
        # State management
        self._subscriptions: Dict[str, Set[str]] = {}  # symbol -> timeframes
        self._callbacks: Dict[str, List[Callable]] = {}  # symbol_timeframe -> callbacks
        self._reconnect_attempts = 0
        self._last_pong = time.time()
        
        # Control flags
        self._shutdown_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        
        # URLs
        if sandbox:
            self._ws_url = "wss://wspap.okx.com:8443/ws/v5/public"
            self._ws_private_url = "wss://wspap.okx.com:8443/ws/v5/private"
        else:
            self._ws_url = "wss://ws.okx.com:8443/ws/v5/public"
            self._ws_private_url = "wss://wspap.okx.com:8443/ws/v5/private"
    
    async def start(self) -> bool:
        """Start the WebSocket service with all async tasks."""
        try:
            # Start all processing tasks
            self._connection_task = asyncio.create_task(self._connection_manager())
            self._message_processor_task = asyncio.create_task(self._message_processor())
            self._subscription_processor_task = asyncio.create_task(self._subscription_processor())
            self._outbound_processor_task = asyncio.create_task(self._outbound_processor())
            self._health_monitor_task = asyncio.create_task(self._health_monitor())
            
            # Wait for connection to be established
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=self.config.connection_timeout)
                logger.info("WebSocket service started successfully")
                return True
            except asyncio.TimeoutError:
                logger.error("WebSocket service startup timeout")
                await self.stop()
                return False
                
        except Exception as e:
            logger.error(f"Failed to start WebSocket service: {e}")
            await self.stop()
            return False
    
    async def stop(self) -> bool:
        """Stop the WebSocket service and all tasks."""
        try:
            self._shutdown_event.set()
            
            # Cancel all tasks
            tasks = [
                self._connection_task,
                self._message_processor_task,
                self._subscription_processor_task,
                self._outbound_processor_task,
                self._health_monitor_task
            ]
            
            for task in tasks:
                if task and not task.done():
                    task.cancel()
            
            # Wait for tasks to complete
            if tasks:
                await asyncio.gather(*[t for t in tasks if t], return_exceptions=True)
            
            # Close WebSocket connection
            if self._websocket:
                await self._websocket.close()
                self._websocket = None
            
            self._is_connected = False
            logger.info("WebSocket service stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping WebSocket service: {e}")
            return False
    
    async def subscribe_symbol(self, symbol: str, timeframes: List[str], callback: Optional[Callable] = None) -> bool:
        """Queue subscription request for async processing."""
        request = SubscriptionRequest(
            action="subscribe",
            symbol=symbol,
            timeframes=timeframes,
            callback=callback
        )
        
        try:
            await self._subscription_queue.put(request)
            return True
        except Exception as e:
            logger.error(f"Failed to queue subscription: {e}")
            return False
    
    async def unsubscribe_symbol(self, symbol: str, timeframes: Optional[List[str]] = None) -> bool:
        """Queue unsubscription request for async processing."""
        request = SubscriptionRequest(
            action="unsubscribe",
            symbol=symbol,
            timeframes=timeframes or [],
        )
        
        try:
            await self._subscription_queue.put(request)
            return True
        except Exception as e:
            logger.error(f"Failed to queue unsubscription: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get WebSocket service status."""
        return {
            "connected": self._is_connected,
            "authenticated": self._is_authenticated,
            "subscriptions": dict(self._subscriptions),
            "message_queue_size": self._message_queue.qsize(),
            "subscription_queue_size": self._subscription_queue.qsize(),
            "outbound_queue_size": self._outbound_queue.qsize(),
            "last_pong": self._last_pong,
            "reconnect_attempts": self._reconnect_attempts
        }
    
    async def _connection_manager(self):
        """Manage WebSocket connection lifecycle."""
        while not self._shutdown_event.is_set():
            try:
                if not self._is_connected:
                    await self._establish_connection()
                
                # Handle messages from WebSocket
                if self._websocket and self._is_connected:
                    async for message in self._websocket:
                        try:
                            data = json.loads(message)
                            ws_message = WebSocketMessage(
                                message_type=self._classify_message(data),
                                data=data
                            )
                            await self._message_queue.put(ws_message)
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse WebSocket message: {e}")
                            continue
                        
                        except Exception as e:
                            logger.error(f"Error queuing WebSocket message: {e}")
                            continue
                            
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                self._is_connected = False
                await self._handle_reconnection()
                
            except Exception as e:
                logger.error(f"Connection manager error: {e}")
                self._is_connected = False
                await self._handle_reconnection()
    
    async def _message_processor(self):
        """Process messages from the message queue."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for messages with timeout to allow shutdown
                try:
                    message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process message based on type
                if message.message_type == "event":
                    await self._handle_event_message(message.data)
                elif message.message_type == "data":
                    await self._handle_data_message(message.data)
                elif message.message_type == "control":
                    await self._handle_control_message(message.data)
                
                # Mark task as done
                self._message_queue.task_done()
                
            except Exception as e:
                logger.error(f"Message processor error: {e}")
                continue
    
    async def _subscription_processor(self):
        """Process subscription requests from the subscription queue."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for subscription requests
                try:
                    request = await asyncio.wait_for(
                        self._subscription_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                if request.action == "subscribe":
                    await self._handle_subscribe_request(request)
                elif request.action == "unsubscribe":
                    await self._handle_unsubscribe_request(request)
                
                self._subscription_queue.task_done()
                
            except Exception as e:
                logger.error(f"Subscription processor error: {e}")
                continue
    
    async def _outbound_processor(self):
        """Process outbound messages to WebSocket."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for outbound messages
                try:
                    message = await asyncio.wait_for(
                        self._outbound_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                if self._websocket and self._is_connected:
                    await self._websocket.send(json.dumps(message))
                
                self._outbound_queue.task_done()
                
            except Exception as e:
                logger.error(f"Outbound processor error: {e}")
                continue
    
    async def _health_monitor(self):
        """Monitor connection health and handle ping/pong."""
        while not self._shutdown_event.is_set():
            try:
                if self._is_connected:
                    # Send ping periodically
                    if time.time() - self._last_pong > self.config.ping_interval:
                        ping_message = {"op": "ping"}
                        await self._outbound_queue.put(ping_message)
                    
                    # Check for connection timeout
                    if time.time() - self._last_pong > self.config.ping_timeout:
                        logger.warning("WebSocket ping timeout, reconnecting")
                        self._is_connected = False
                
                await asyncio.sleep(self.config.ping_interval)
                
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(1)
    
    async def _establish_connection(self):
        """Establish WebSocket connection."""
        try:
            self._websocket = await websockets.connect(
                self._ws_url,
                ping_interval=None,  # We handle pings manually
                close_timeout=10
            )
            
            self._is_connected = True
            self._reconnect_attempts = 0
            self._last_pong = time.time()
            self._ready_event.set()
            
            logger.info("WebSocket connection established")
            
        except Exception as e:
            logger.error(f"Failed to establish WebSocket connection: {e}")
            raise WebSocketConnectionError(f"Connection failed: {e}")
    
    async def _handle_reconnection(self):
        """Handle reconnection logic with exponential backoff."""
        if self._shutdown_event.is_set():
            return
        
        self._reconnect_attempts += 1
        delay = min(2 ** self._reconnect_attempts, 60)  # Max 60 seconds
        
        logger.info(f"Reconnecting in {delay} seconds (attempt {self._reconnect_attempts})")
        await asyncio.sleep(delay)
    
    def _classify_message(self, data: Dict[str, Any]) -> str:
        """Classify message type for queue routing."""
        if "event" in data:
            return "event"
        elif "data" in data:
            return "data"
        elif "op" in data:
            return "control"
        else:
            return "unknown"
    
    async def _handle_subscribe_request(self, request: SubscriptionRequest):
        """Handle subscription request."""
        try:
            # Update internal state
            if request.symbol not in self._subscriptions:
                self._subscriptions[request.symbol] = set()
            
            self._subscriptions[request.symbol].update(request.timeframes)
            
            # Register callback if provided
            if request.callback:
                for timeframe in request.timeframes:
                    key = f"{request.symbol}_{timeframe}"
                    if key not in self._callbacks:
                        self._callbacks[key] = []
                    self._callbacks[key].append(request.callback)
            
            # Send WebSocket subscription
            for timeframe in request.timeframes:
                channel = self._timeframe_to_channel(timeframe)
                sub_message = {
                    "op": "subscribe",
                    "args": [{
                        "channel": channel,
                        "instId": request.symbol
                    }]
                }
                await self._outbound_queue.put(sub_message)
            
            logger.info(f"Subscribed to {request.symbol} {request.timeframes}")
            
        except Exception as e:
            logger.error(f"Error handling subscription request: {e}")
    
    async def _handle_unsubscribe_request(self, request: SubscriptionRequest):
        """Handle unsubscription request."""
        try:
            if request.symbol in self._subscriptions:
                if request.timeframes:
                    # Remove specific timeframes
                    self._subscriptions[request.symbol] -= set(request.timeframes)
                    if not self._subscriptions[request.symbol]:
                        del self._subscriptions[request.symbol]
                else:
                    # Remove all timeframes for symbol
                    request.timeframes = list(self._subscriptions[request.symbol])
                    del self._subscriptions[request.symbol]
                
                # Send WebSocket unsubscription
                for timeframe in request.timeframes:
                    channel = self._timeframe_to_channel(timeframe)
                    unsub_message = {
                        "op": "unsubscribe", 
                        "args": [{
                            "channel": channel,
                            "instId": request.symbol
                        }]
                    }
                    await self._outbound_queue.put(unsub_message)
                
                logger.info(f"Unsubscribed from {request.symbol} {request.timeframes}")
            
        except Exception as e:
            logger.error(f"Error handling unsubscription request: {e}")
    
    async def _handle_event_message(self, data: Dict[str, Any]):
        """Handle event messages (subscription confirmations, errors)."""
        event = data.get("event")
        
        if event == "subscribe":
            arg = data.get("arg", {})
            channel = arg.get("channel")
            inst_id = arg.get("instId")
            logger.info(f"Subscription confirmed: {inst_id} {channel}")
            
        elif event == "error":
            msg = data.get("msg", "Unknown error")
            code = data.get("code", "")
            logger.error(f"WebSocket error {code}: {msg}")
            
        elif event == "pong":
            self._last_pong = time.time()
    
    async def _handle_data_message(self, data: Dict[str, Any]):
        """Handle data messages and distribute to callbacks."""
        try:
            arg = data.get("arg", {})
            channel = arg.get("channel", "")
            inst_id = arg.get("instId", "")
            
            # Convert channel back to timeframe
            timeframe = self._channel_to_timeframe(channel)
            if not timeframe:
                return
            
            # Process data and call callbacks
            callback_key = f"{inst_id}_{timeframe}"
            if callback_key in self._callbacks:
                message_data = data.get("data", [])
                for callback in self._callbacks[callback_key]:
                    try:
                        # Call callback in a separate task to avoid blocking
                        asyncio.create_task(self._safe_callback(callback, {
                            "symbol": inst_id,
                            "timeframe": timeframe,
                            "data": message_data,
                            "raw": data
                        }))
                    except Exception as e:
                        logger.error(f"Error calling callback: {e}")
            
        except Exception as e:
            logger.error(f"Error handling data message: {e}")
    
    async def _handle_control_message(self, data: Dict[str, Any]):
        """Handle control messages (ping, pong, etc.)."""
        op = data.get("op")
        
        if op == "pong":
            self._last_pong = time.time()
    
    async def _safe_callback(self, callback: Callable, data: Dict[str, Any]):
        """Safely execute callback to prevent blocking."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            logger.error(f"Callback error: {e}")
    
    def _timeframe_to_channel(self, timeframe: str) -> str:
        """Convert timeframe to WebSocket channel."""
        # Map common timeframes to OKX channels
        channel_map = {
            "1m": "candle1m",
            "3m": "candle3m", 
            "5m": "candle5m",
            "15m": "candle15m",
            "30m": "candle30m",
            "1h": "candle1H",
            "1H": "candle1H",
            "2h": "candle2H",
            "2H": "candle2H",
            "4h": "candle4H",
            "4H": "candle4H",
            "6h": "candle6H",
            "6H": "candle6H",
            "12h": "candle12H",
            "12H": "candle12H",
            "1d": "candle1D",
            "1D": "candle1D",
            "1w": "candle1W",
            "1W": "candle1W",
            "1M": "candle1M"
        }
        return channel_map.get(timeframe, f"candle{timeframe}")
    
    def _channel_to_timeframe(self, channel: str) -> Optional[str]:
        """Convert WebSocket channel back to timeframe."""
        if channel.startswith("candle"):
            return channel[6:]  # Remove "candle" prefix
        return None