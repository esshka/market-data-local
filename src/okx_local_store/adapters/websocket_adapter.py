"""WebSocket data adapter for transforming WebSocket messages into standardized events."""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timezone
from loguru import logger
from dataclasses import dataclass
from enum import Enum

from ..events.realtime_events import (
    RealtimeEvent, CandleDataEvent, TickerDataEvent, ConnectionStatusEvent,
    SubscriptionStatusEvent, ErrorEvent, create_candle_event, 
    create_connection_event, create_error_event, RealtimeEventType
)


class OKXMessageType(Enum):
    """OKX WebSocket message types."""
    CANDLE = "candle"
    TICKER = "ticker"
    SUBSCRIPTION = "subscribe"
    UNSUBSCRIPTION = "unsubscribe"
    ERROR = "error"
    PONG = "pong"
    UNKNOWN = "unknown"


@dataclass
class WebSocketMessageContext:
    """Context information for WebSocket message processing."""
    timestamp: float
    channel: str
    instrument_id: str
    message_type: OKXMessageType
    raw_message: Dict[str, Any]


class WebSocketMessageAdapter(ABC):
    """Abstract base class for WebSocket message adapters."""
    
    @abstractmethod
    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this adapter can handle the given message."""
        pass
    
    @abstractmethod
    def adapt(self, message: Dict[str, Any], context: WebSocketMessageContext) -> List[RealtimeEvent]:
        """Adapt WebSocket message to standardized events."""
        pass


class OKXCandleAdapter(WebSocketMessageAdapter):
    """Adapter for OKX candle (OHLCV) data messages."""
    
    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message contains candle data."""
        if not isinstance(message, dict):
            return False
        
        arg = message.get("arg", {})
        channel = arg.get("channel", "")
        
        return channel.startswith("candle")
    
    def adapt(self, message: Dict[str, Any], context: WebSocketMessageContext) -> List[RealtimeEvent]:
        """Transform OKX candle message to CandleDataEvent."""
        events = []
        
        try:
            arg = message.get("arg", {})
            data = message.get("data", [])
            
            channel = arg.get("channel", "")
            inst_id = arg.get("instId", "")
            
            # Extract timeframe from channel (e.g., "candle1m" -> "1m")
            timeframe = self._extract_timeframe_from_channel(channel)
            
            if not timeframe:
                logger.warning(f"Could not extract timeframe from channel: {channel}")
                return events
            
            # Process each candle in the data array
            for candle_data in data:
                if not isinstance(candle_data, list) or len(candle_data) < 6:
                    logger.warning(f"Invalid candle data format: {candle_data}")
                    continue
                
                try:
                    # Create candle event using factory function
                    candle_event = create_candle_event(
                        symbol=inst_id,
                        timeframe=timeframe,
                        timestamp=int(candle_data[0]),
                        open_price=float(candle_data[1]),
                        high=float(candle_data[2]),
                        low=float(candle_data[3]),
                        close=float(candle_data[4]),
                        volume=float(candle_data[5]),
                        # Additional OKX-specific fields
                        vol_currency=float(candle_data[6]) if len(candle_data) > 6 else None,
                        vol_currency_quote=float(candle_data[7]) if len(candle_data) > 7 else None,
                        is_confirmed=candle_data[8] == "1" if len(candle_data) > 8 else True,
                        # Store raw data for debugging/analysis
                        raw_candle_data=candle_data,
                        channel=channel,
                        source="okx_websocket"
                    )
                    
                    events.append(candle_event)
                    
                except (ValueError, IndexError) as e:
                    logger.error(f"Error processing candle data {candle_data}: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error adapting candle message: {e}")
            # Create error event
            error_event = create_error_event(
                f"Candle adapter error: {e}",
                channel=context.channel,
                instrument_id=context.instrument_id,
                raw_message=message
            )
            events.append(error_event)
        
        return events
    
    def _extract_timeframe_from_channel(self, channel: str) -> Optional[str]:
        """Extract timeframe from OKX channel name."""
        if not channel.startswith("candle"):
            return None
        
        # Remove "candle" prefix to get timeframe
        timeframe = channel[6:]  # len("candle") = 6
        
        # Map OKX timeframes to standard format
        timeframe_map = {
            "1m": "1m",
            "3m": "3m", 
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1H": "1h",
            "2H": "2h",
            "4H": "4h",
            "6H": "6h",
            "12H": "12h",
            "1D": "1d",
            "1W": "1w",
            "1M": "1M"
        }
        
        return timeframe_map.get(timeframe, timeframe)


class OKXTickerAdapter(WebSocketMessageAdapter):
    """Adapter for OKX ticker data messages."""
    
    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message contains ticker data."""
        if not isinstance(message, dict):
            return False
        
        arg = message.get("arg", {})
        channel = arg.get("channel", "")
        
        return channel == "tickers"
    
    def adapt(self, message: Dict[str, Any], context: WebSocketMessageContext) -> List[RealtimeEvent]:
        """Transform OKX ticker message to TickerDataEvent."""
        events = []
        
        try:
            arg = message.get("arg", {})
            data = message.get("data", [])
            
            inst_id = arg.get("instId", "")
            
            # Process each ticker in the data array
            for ticker_data in data:
                if not isinstance(ticker_data, dict):
                    logger.warning(f"Invalid ticker data format: {ticker_data}")
                    continue
                
                try:
                    ticker_event = TickerDataEvent(
                        data={
                            "symbol": inst_id,
                            "last_price": float(ticker_data.get("last", 0)),
                            "bid_price": float(ticker_data.get("bidPx", 0)),
                            "ask_price": float(ticker_data.get("askPx", 0)),
                            "volume_24h": float(ticker_data.get("vol24h", 0)),
                            "high_24h": float(ticker_data.get("high24h", 0)),
                            "low_24h": float(ticker_data.get("low24h", 0)),
                            "change_24h": float(ticker_data.get("change24h", 0)),
                            "timestamp": int(ticker_data.get("ts", context.timestamp * 1000)),
                            "source": "okx_websocket",
                            "raw_ticker_data": ticker_data
                        }
                    )
                    
                    events.append(ticker_event)
                    
                except (ValueError, KeyError) as e:
                    logger.error(f"Error processing ticker data {ticker_data}: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error adapting ticker message: {e}")
            error_event = create_error_event(
                f"Ticker adapter error: {e}",
                channel=context.channel,
                instrument_id=context.instrument_id,
                raw_message=message
            )
            events.append(error_event)
        
        return events


class OKXEventAdapter(WebSocketMessageAdapter):
    """Adapter for OKX event messages (subscriptions, errors, etc.)."""
    
    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message is an event message."""
        return isinstance(message, dict) and "event" in message
    
    def adapt(self, message: Dict[str, Any], context: WebSocketMessageContext) -> List[RealtimeEvent]:
        """Transform OKX event message to appropriate events."""
        events = []
        
        try:
            event_type = message.get("event")
            
            if event_type == "subscribe":
                events.append(self._create_subscription_event(message, True))
            elif event_type == "unsubscribe":
                events.append(self._create_subscription_event(message, False))
            elif event_type == "error":
                events.append(self._create_error_event(message))
            elif event_type == "pong":
                events.append(self._create_connection_event("pong_received"))
            else:
                logger.debug(f"Unhandled event type: {event_type}")
        
        except Exception as e:
            logger.error(f"Error adapting event message: {e}")
            error_event = create_error_event(
                f"Event adapter error: {e}",
                raw_message=message
            )
            events.append(error_event)
        
        return events
    
    def _create_subscription_event(self, message: Dict[str, Any], subscribed: bool) -> SubscriptionStatusEvent:
        """Create subscription status event."""
        arg = message.get("arg", {})
        channel = arg.get("channel", "")
        inst_id = arg.get("instId", "")
        
        return SubscriptionStatusEvent(
            data={
                "status": "confirmed" if subscribed else "cancelled",
                "channel": channel,
                "symbol": inst_id,
                "action": "subscribe" if subscribed else "unsubscribe"
            },
            metadata={
                "symbol": inst_id,
                "channel": channel
            }
        )
    
    def _create_error_event(self, message: Dict[str, Any]) -> ErrorEvent:
        """Create error event from OKX error message."""
        error_msg = message.get("msg", "Unknown error")
        error_code = message.get("code", "")
        
        return create_error_event(
            f"OKX WebSocket error {error_code}: {error_msg}",
            error_code=error_code,
            error_message=error_msg,
            raw_message=message
        )
    
    def _create_connection_event(self, status: str) -> ConnectionStatusEvent:
        """Create connection status event."""
        return create_connection_event(status)


class WebSocketDataAdapter:
    """Main adapter that coordinates all WebSocket message adapters."""
    
    def __init__(self):
        """Initialize with default OKX adapters."""
        self.adapters: List[WebSocketMessageAdapter] = [
            OKXCandleAdapter(),
            OKXTickerAdapter(),
            OKXEventAdapter()
        ]
        
        self.stats = {
            "messages_processed": 0,
            "events_created": 0,
            "errors": 0,
            "unknown_messages": 0
        }
    
    def add_adapter(self, adapter: WebSocketMessageAdapter) -> None:
        """Add custom adapter."""
        self.adapters.append(adapter)
    
    def remove_adapter(self, adapter: WebSocketMessageAdapter) -> bool:
        """Remove adapter."""
        try:
            self.adapters.remove(adapter)
            return True
        except ValueError:
            return False
    
    def adapt_message(self, message: Dict[str, Any]) -> List[RealtimeEvent]:
        """Transform WebSocket message into standardized events."""
        self.stats["messages_processed"] += 1
        
        try:
            # Create context for message processing
            context = self._create_context(message)
            
            # Find appropriate adapter
            adapter = self._find_adapter(message)
            
            if adapter:
                events = adapter.adapt(message, context)
                self.stats["events_created"] += len(events)
                
                # Add adapter metadata to events
                for event in events:
                    event.metadata["adapter"] = adapter.__class__.__name__
                    event.metadata["message_type"] = context.message_type.value
                
                return events
            else:
                # No adapter found - create unknown message event
                logger.debug(f"No adapter found for message: {message}")
                self.stats["unknown_messages"] += 1
                
                error_event = create_error_event(
                    "No adapter found for WebSocket message",
                    message_type="unknown",
                    raw_message=message
                )
                return [error_event]
                
        except Exception as e:
            logger.error(f"Error in message adaptation: {e}")
            self.stats["errors"] += 1
            
            error_event = create_error_event(
                f"Message adaptation error: {e}",
                raw_message=message
            )
            return [error_event]
    
    def _create_context(self, message: Dict[str, Any]) -> WebSocketMessageContext:
        """Create processing context for message."""
        import time
        
        arg = message.get("arg", {})
        channel = arg.get("channel", "")
        inst_id = arg.get("instId", "")
        
        # Determine message type
        message_type = OKXMessageType.UNKNOWN
        if "event" in message:
            message_type = OKXMessageType.SUBSCRIPTION
        elif channel.startswith("candle"):
            message_type = OKXMessageType.CANDLE
        elif channel == "tickers":
            message_type = OKXMessageType.TICKER
        
        return WebSocketMessageContext(
            timestamp=time.time(),
            channel=channel,
            instrument_id=inst_id,
            message_type=message_type,
            raw_message=message
        )
    
    def _find_adapter(self, message: Dict[str, Any]) -> Optional[WebSocketMessageAdapter]:
        """Find appropriate adapter for message."""
        for adapter in self.adapters:
            if adapter.can_handle(message):
                return adapter
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adaptation statistics."""
        return self.stats.copy()
    
    def reset_stats(self) -> None:
        """Reset adaptation statistics."""
        for key in self.stats:
            self.stats[key] = 0


# Factory function for easy usage
def create_okx_websocket_adapter() -> WebSocketDataAdapter:
    """Create WebSocket adapter configured for OKX messages."""
    return WebSocketDataAdapter()