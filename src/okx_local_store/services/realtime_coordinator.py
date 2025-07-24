"""Real-time data coordinator for handling WebSocket events and business logic integration."""

import asyncio
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from loguru import logger
from enum import Enum

from ..interfaces.api_client import RealtimeClientInterface
from ..interfaces.storage import StorageInterface
from ..config import OKXConfig, InstrumentConfig
from ..events.realtime_events import (
    RealtimeEventBus, RealtimeEvent, CandleDataEvent, ConnectionStatusEvent, 
    ErrorEvent, create_candle_event, create_connection_event, create_error_event,
    EventHandler, RealtimeEventType
)
from ..services.websocket_service import WebSocketService


@dataclass
class RealtimeInstrumentState:
    """State tracking for real-time instrument synchronization."""
    symbol: str
    timeframes: Set[str]
    active: bool = False
    last_data_time: Optional[datetime] = None
    error_count: int = 0
    subscription_confirmed: bool = False


class RealtimeDataCoordinator(EventHandler):
    """
    Coordinates real-time data flow between WebSocket service and business logic.
    Implements event-driven architecture to decouple WebSocket concerns.
    """
    
    def __init__(
        self,
        config: OKXConfig,
        storage: StorageInterface,
        event_bus: RealtimeEventBus,
        websocket_service: Optional[WebSocketService] = None
    ):
        """Initialize real-time data coordinator."""
        self.config = config
        self.storage = storage
        self.event_bus = event_bus
        self.websocket_service = websocket_service
        
        # State management
        self._instrument_states: Dict[str, RealtimeInstrumentState] = {}
        self._is_running = False
        self._coordination_task: Optional[asyncio.Task] = None
        
        # Control
        self._shutdown_event = asyncio.Event()
        
        # Subscribe to relevant events
        self.event_bus.subscribe(RealtimeEventType.CANDLE_DATA, self)
        self.event_bus.subscribe(RealtimeEventType.CONNECTION_STATUS, self)
        self.event_bus.subscribe(RealtimeEventType.SUBSCRIPTION_STATUS, self)
        self.event_bus.subscribe(RealtimeEventType.ERROR, self)
    
    async def start(self) -> bool:
        """Start the real-time data coordinator."""
        if self._is_running:
            logger.warning("RealtimeDataCoordinator already running")
            return True
        
        try:
            # Initialize WebSocket service if not provided
            if not self.websocket_service:
                self.websocket_service = self._create_websocket_service()
            
            # Start WebSocket service
            if not await self.websocket_service.start():
                logger.error("Failed to start WebSocket service")
                return False
            
            # Initialize instrument states
            self._initialize_instrument_states()
            
            # Start coordination task
            self._coordination_task = asyncio.create_task(self._coordination_loop())
            
            # Subscribe to instruments
            await self._subscribe_all_instruments()
            
            self._is_running = True
            logger.info("RealtimeDataCoordinator started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start RealtimeDataCoordinator: {e}")
            await self.stop()
            return False
    
    async def stop(self) -> bool:
        """Stop the real-time data coordinator."""
        if not self._is_running:
            return True
        
        try:
            self._shutdown_event.set()
            self._is_running = False
            
            # Cancel coordination task
            if self._coordination_task and not self._coordination_task.done():
                self._coordination_task.cancel()
                try:
                    await self._coordination_task
                except asyncio.CancelledError:
                    pass
            
            # Stop WebSocket service
            if self.websocket_service:
                await self.websocket_service.stop()
            
            # Unsubscribe from events
            self.event_bus.unsubscribe(RealtimeEventType.CANDLE_DATA, self)
            self.event_bus.unsubscribe(RealtimeEventType.CONNECTION_STATUS, self)
            self.event_bus.unsubscribe(RealtimeEventType.SUBSCRIPTION_STATUS, self)
            self.event_bus.unsubscribe(RealtimeEventType.ERROR, self)
            
            logger.info("RealtimeDataCoordinator stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping RealtimeDataCoordinator: {e}")
            return False
    
    async def handle_event(self, event: RealtimeEvent) -> None:
        """Handle real-time events for business logic integration."""
        try:
            if event.event_type == RealtimeEventType.CANDLE_DATA:
                await self._handle_candle_data(event)
            elif event.event_type == RealtimeEventType.CONNECTION_STATUS:
                await self._handle_connection_status(event)
            elif event.event_type == RealtimeEventType.SUBSCRIPTION_STATUS:
                await self._handle_subscription_status(event)
            elif event.event_type == RealtimeEventType.ERROR:
                await self._handle_error_event(event)
                
        except Exception as e:
            logger.error(f"Error handling {event.event_type.value} event: {e}")
    
    async def subscribe_instrument(
        self, 
        symbol: str, 
        timeframes: List[str]
    ) -> bool:
        """Subscribe to real-time data for an instrument."""
        try:
            if not self.websocket_service:
                logger.error("WebSocket service not available")
                return False
            
            # Create callback that publishes to event bus
            callback = self._create_data_callback(symbol)
            
            # Subscribe via WebSocket service
            success = await self.websocket_service.subscribe_symbol(
                symbol, timeframes, callback
            )
            
            if success:
                # Update state
                if symbol not in self._instrument_states:
                    self._instrument_states[symbol] = RealtimeInstrumentState(
                        symbol=symbol,
                        timeframes=set(timeframes)
                    )
                else:
                    self._instrument_states[symbol].timeframes.update(timeframes)
                
                self._instrument_states[symbol].active = True
                logger.info(f"Subscribed to real-time data for {symbol} {timeframes}")
                
            return success
            
        except Exception as e:
            logger.error(f"Error subscribing to {symbol}: {e}")
            return False
    
    async def unsubscribe_instrument(
        self, 
        symbol: str, 
        timeframes: Optional[List[str]] = None
    ) -> bool:
        """Unsubscribe from real-time data for an instrument."""
        try:
            if not self.websocket_service:
                return False
            
            success = await self.websocket_service.unsubscribe_symbol(symbol, timeframes)
            
            if success and symbol in self._instrument_states:
                if timeframes:
                    # Remove specific timeframes
                    self._instrument_states[symbol].timeframes -= set(timeframes)
                    if not self._instrument_states[symbol].timeframes:
                        self._instrument_states[symbol].active = False
                else:
                    # Remove all timeframes
                    self._instrument_states[symbol].active = False
                    self._instrument_states[symbol].timeframes.clear()
                
                logger.info(f"Unsubscribed from real-time data for {symbol}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error unsubscribing from {symbol}: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get coordinator status."""
        ws_status = {}
        if self.websocket_service:
            ws_status = self.websocket_service.get_status()
        
        return {
            "running": self._is_running,
            "websocket_service": ws_status,
            "instrument_states": {
                symbol: {
                    "active": state.active,
                    "timeframes": list(state.timeframes),
                    "last_data_time": state.last_data_time.isoformat() if state.last_data_time else None,
                    "error_count": state.error_count,
                    "subscription_confirmed": state.subscription_confirmed
                }
                for symbol, state in self._instrument_states.items()
            }
        }
    
    def _create_websocket_service(self) -> WebSocketService:
        """Create WebSocket service with configuration."""
        creds = self.config.get_env_credentials()
        
        return WebSocketService(
            api_key=creds.get('api_key'),
            api_secret=creds.get('api_secret'),
            passphrase=creds.get('passphrase'),
            sandbox=self.config.sandbox,
            websocket_config=self.config.websocket_config
        )
    
    def _initialize_instrument_states(self):
        """Initialize states for configured instruments."""
        for instrument in self.config.instruments:
            if instrument.enabled and instrument.realtime_source == 'websocket':
                self._instrument_states[instrument.symbol] = RealtimeInstrumentState(
                    symbol=instrument.symbol,
                    timeframes=set(instrument.timeframes)
                )
                logger.debug(f"Initialized state for {instrument.symbol}")
    
    async def _subscribe_all_instruments(self):
        """Subscribe to all configured instruments."""
        for instrument in self.config.instruments:
            if (instrument.enabled and 
                instrument.realtime_source == 'websocket' and 
                instrument.timeframes):
                
                await self.subscribe_instrument(instrument.symbol, instrument.timeframes)
    
    async def _coordination_loop(self):
        """Main coordination loop for health monitoring and management."""
        while not self._shutdown_event.is_set():
            try:
                # Monitor instrument health
                await self._monitor_instrument_health()
                
                # Wait before next iteration
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in coordination loop: {e}")
                await asyncio.sleep(5)
    
    async def _monitor_instrument_health(self):
        """Monitor health of instrument subscriptions."""
        current_time = datetime.now(timezone.utc)
        
        for symbol, state in self._instrument_states.items():
            if not state.active:
                continue
            
            # Check for stale data
            if (state.last_data_time and 
                (current_time - state.last_data_time).total_seconds() > 300):  # 5 minutes
                
                logger.warning(f"Stale data detected for {symbol}, last: {state.last_data_time}")
                
                # Publish health event
                health_event = create_connection_event(
                    "stale_data",
                    symbol=symbol,
                    last_data_time=state.last_data_time.isoformat()
                )
                await self.event_bus.publish(health_event)
    
    def _create_data_callback(self, symbol: str):
        """Create callback function for WebSocket data."""
        async def callback(data: Dict[str, Any]):
            """Process WebSocket data and publish as events."""
            try:
                # Extract data fields
                symbol_data = data.get("symbol", symbol)
                timeframe = data.get("timeframe")
                raw_data = data.get("data", [])
                
                # Process each data point
                for item in raw_data:
                    if len(item) >= 6:  # Valid OHLCV data
                        # Create candle event
                        candle_event = create_candle_event(
                            symbol=symbol_data,
                            timeframe=timeframe,
                            timestamp=int(item[0]),
                            open_price=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            is_confirmed=item[8] == "1" if len(item) > 8 else True,
                            raw_data=item
                        )
                        
                        # Publish to event bus
                        await self.event_bus.publish(candle_event)
                        
            except Exception as e:
                logger.error(f"Error in data callback for {symbol}: {e}")
                # Publish error event
                error_event = create_error_event(
                    f"Data callback error: {e}",
                    symbol=symbol,
                    raw_data=data
                )
                await self.event_bus.publish(error_event)
        
        return callback
    
    async def _handle_candle_data(self, event: CandleDataEvent):
        """Handle candle data events for storage."""
        try:
            data = event.data
            symbol = data["symbol"]
            timeframe = data["timeframe"]
            
            # Update instrument state
            if symbol in self._instrument_states:
                self._instrument_states[symbol].last_data_time = datetime.now(timezone.utc)
                self._instrument_states[symbol].error_count = 0  # Reset on successful data
            
            # Store data using storage interface
            candle_dict = {
                "timestamp": data["timestamp"],
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "close": data["close"],
                "volume": data["volume"],
                "symbol": symbol,
                "timeframe": timeframe
            }
            
            # Use storage interface (assuming it has a method for real-time data)
            if hasattr(self.storage, 'store_realtime_candle'):
                self.storage.store_realtime_candle(symbol, timeframe, candle_dict)
            else:
                # Fallback to regular storage
                self.storage.store_ohlcv_data(symbol, timeframe, [candle_dict])
            
            logger.debug(f"Processed candle data for {symbol} {timeframe}")
            
        except Exception as e:
            logger.error(f"Error handling candle data: {e}")
    
    async def _handle_connection_status(self, event: ConnectionStatusEvent):
        """Handle connection status events."""
        status = event.data.get("status")
        logger.info(f"Connection status: {status}")
        
        # Update all instrument states based on connection status
        if status == "disconnected":
            for state in self._instrument_states.values():
                state.subscription_confirmed = False
        elif status == "connected":
            # Connection restored - may need to resubscribe
            await self._subscribe_all_instruments()
    
    async def _handle_subscription_status(self, event):
        """Handle subscription status events."""
        # Update relevant instrument state
        symbol = event.metadata.get("symbol")
        status = event.data.get("status")
        
        if symbol and symbol in self._instrument_states:
            self._instrument_states[symbol].subscription_confirmed = (status == "confirmed")
            logger.debug(f"Subscription {status} for {symbol}")
    
    async def _handle_error_event(self, event: ErrorEvent):
        """Handle error events."""
        error = event.data.get("error")
        symbol = event.metadata.get("symbol")
        
        # Update error count for specific instrument
        if symbol and symbol in self._instrument_states:
            self._instrument_states[symbol].error_count += 1
        
        logger.error(f"Real-time error for {symbol}: {error}")
        
        # Consider fallback logic here if needed
        if symbol and self._instrument_states[symbol].error_count > 5:
            logger.warning(f"Too many errors for {symbol}, considering fallback")
            # Could trigger fallback to polling mode