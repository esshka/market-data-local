"""Real-time event bus for decoupling WebSocket events from business logic."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, Union, Protocol
from enum import Enum
from loguru import logger
import time


class RealtimeEventType(Enum):
    """Types of real-time events."""
    CANDLE_DATA = "candle_data"
    TICKER_DATA = "ticker_data"
    CONNECTION_STATUS = "connection_status"
    SUBSCRIPTION_STATUS = "subscription_status"
    ERROR = "error"
    HEALTH_CHECK = "health_check"


@dataclass
class RealtimeEvent:
    """Base real-time event structure."""
    event_type: RealtimeEventType
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: f"evt_{int(time.time() * 1000000)}")
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "data": self.data,
            "metadata": self.metadata
        }


@dataclass
class CandleDataEvent(RealtimeEvent):
    """Event for OHLCV candle data."""
    event_type: RealtimeEventType = RealtimeEventType.CANDLE_DATA
    
    def __post_init__(self):
        """Validate candle data structure."""
        required_fields = ["symbol", "timeframe", "timestamp", "open", "high", "low", "close", "volume"]
        for field in required_fields:
            if field not in self.data:
                raise ValueError(f"Missing required field in candle data: {field}")


@dataclass  
class TickerDataEvent(RealtimeEvent):
    """Event for ticker/price data."""
    event_type: RealtimeEventType = RealtimeEventType.TICKER_DATA


@dataclass
class ConnectionStatusEvent(RealtimeEvent):
    """Event for connection status changes."""
    event_type: RealtimeEventType = RealtimeEventType.CONNECTION_STATUS
    
    def __post_init__(self):
        """Validate connection status data."""
        if "status" not in self.data:
            raise ValueError("Connection status event must have 'status' field")


@dataclass
class SubscriptionStatusEvent(RealtimeEvent):
    """Event for subscription status changes."""
    event_type: RealtimeEventType = RealtimeEventType.SUBSCRIPTION_STATUS


@dataclass
class ErrorEvent(RealtimeEvent):
    """Event for errors."""
    event_type: RealtimeEventType = RealtimeEventType.ERROR
    
    def __post_init__(self):
        """Validate error data."""
        if "error" not in self.data:
            raise ValueError("Error event must have 'error' field")


class EventHandler(Protocol):
    """Protocol for event handlers."""
    async def handle_event(self, event: RealtimeEvent) -> None:
        """Handle a real-time event."""
        ...


class RealtimeEventBus:
    """Event bus for real-time data using async queues for decoupling."""
    
    def __init__(self, max_queue_size: int = 10000):
        """Initialize event bus with async queues."""
        self._max_queue_size = max_queue_size
        
        # Event queues by type for efficient routing
        self._event_queues: Dict[RealtimeEventType, asyncio.Queue] = {}
        self._global_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        
        # Event handlers by type
        self._handlers: Dict[RealtimeEventType, List[EventHandler]] = {}
        self._global_handlers: List[EventHandler] = []
        
        # Processing tasks
        self._processor_tasks: Dict[RealtimeEventType, asyncio.Task] = {}
        self._global_processor_task: Optional[asyncio.Task] = None
        
        # Control
        self._shutdown_event = asyncio.Event()
        self._running = False
        
        # Metrics
        self._events_processed = 0
        self._events_dropped = 0
        self._last_event_time = 0.0
        
        # Initialize queues for all event types
        for event_type in RealtimeEventType:
            self._event_queues[event_type] = asyncio.Queue(maxsize=max_queue_size)
            self._handlers[event_type] = []
    
    async def start(self) -> None:
        """Start the event bus processing."""
        if self._running:
            return
        
        self._running = True
        self._shutdown_event.clear()
        
        # Start processors for each event type
        for event_type in RealtimeEventType:
            self._processor_tasks[event_type] = asyncio.create_task(
                self._process_event_type(event_type)
            )
        
        # Start global processor
        self._global_processor_task = asyncio.create_task(self._process_global_events())
        
        logger.info("RealtimeEventBus started")
    
    async def stop(self) -> None:
        """Stop the event bus processing."""
        if not self._running:
            return
        
        self._shutdown_event.set()
        self._running = False
        
        # Cancel all processor tasks
        all_tasks = list(self._processor_tasks.values())
        if self._global_processor_task:
            all_tasks.append(self._global_processor_task)
        
        for task in all_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to complete
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        
        logger.info("RealtimeEventBus stopped")
    
    async def publish(self, event: RealtimeEvent) -> bool:
        """Publish an event to the appropriate queues."""
        if not self._running:
            logger.warning("Cannot publish event - event bus not running")
            return False
        
        try:
            # Update metrics
            self._last_event_time = time.time()
            
            # Route to type-specific queue
            type_queue = self._event_queues[event.event_type]
            try:
                type_queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"Type queue full for {event.event_type.value}, dropping event")
                self._events_dropped += 1
                return False
            
            # Route to global queue for global handlers
            if self._global_handlers:
                try:
                    self._global_queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("Global queue full, dropping event")
                    # Don't return False here as type-specific delivery succeeded
            
            return True
            
        except Exception as e:
            logger.error(f"Error publishing event: {e}")
            return False
    
    def subscribe(
        self, 
        event_type: RealtimeEventType, 
        handler: EventHandler
    ) -> None:
        """Subscribe to events of a specific type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append(handler)
        logger.debug(f"Handler subscribed to {event_type.value}")
    
    def subscribe_global(self, handler: EventHandler) -> None:
        """Subscribe to all events globally."""
        self._global_handlers.append(handler)
        logger.debug("Global handler subscribed")
    
    def unsubscribe(
        self, 
        event_type: RealtimeEventType, 
        handler: EventHandler
    ) -> bool:
        """Unsubscribe from events of a specific type."""
        try:
            self._handlers[event_type].remove(handler)
            logger.debug(f"Handler unsubscribed from {event_type.value}")
            return True
        except (KeyError, ValueError):
            logger.warning(f"Handler not found for unsubscription from {event_type.value}")
            return False
    
    def unsubscribe_global(self, handler: EventHandler) -> bool:
        """Unsubscribe from global events."""
        try:
            self._global_handlers.remove(handler)
            logger.debug("Global handler unsubscribed")
            return True
        except ValueError:
            logger.warning("Global handler not found for unsubscription")
            return False
    
    async def _process_event_type(self, event_type: RealtimeEventType) -> None:
        """Process events for a specific type."""
        queue = self._event_queues[event_type]
        handlers = self._handlers[event_type]
        
        while not self._shutdown_event.is_set():
            try:
                # Wait for events with timeout to allow shutdown
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process event with all registered handlers
                await self._dispatch_to_handlers(event, handlers)
                
                # Mark task as done
                queue.task_done()
                self._events_processed += 1
                
            except Exception as e:
                logger.error(f"Error processing {event_type.value} events: {e}")
                continue
    
    async def _process_global_events(self) -> None:
        """Process global events."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for events with timeout to allow shutdown
                try:
                    event = await asyncio.wait_for(self._global_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process event with global handlers
                await self._dispatch_to_handlers(event, self._global_handlers)
                
                # Mark task as done
                self._global_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error processing global events: {e}")
                continue
    
    async def _dispatch_to_handlers(
        self, 
        event: RealtimeEvent, 
        handlers: List[EventHandler]
    ) -> None:
        """Dispatch event to a list of handlers concurrently."""
        if not handlers:
            return
        
        # Create tasks for all handlers to run concurrently
        tasks = []
        for handler in handlers:
            task = asyncio.create_task(self._safe_handle_event(handler, event))
            tasks.append(task)
        
        # Wait for all handlers to complete
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _safe_handle_event(self, handler: EventHandler, event: RealtimeEvent) -> None:
        """Safely handle event to prevent one handler from blocking others."""
        try:
            await handler.handle_event(event)
        except Exception as e:
            logger.error(f"Handler error for {event.event_type.value}: {e}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get event bus metrics."""
        queue_sizes = {
            event_type.value: queue.qsize() 
            for event_type, queue in self._event_queues.items()
        }
        
        return {
            "running": self._running,
            "events_processed": self._events_processed,
            "events_dropped": self._events_dropped,
            "last_event_time": self._last_event_time,
            "global_queue_size": self._global_queue.qsize(),
            "type_queue_sizes": queue_sizes,
            "handler_counts": {
                event_type.value: len(handlers)
                for event_type, handlers in self._handlers.items()
            },
            "global_handler_count": len(self._global_handlers)
        }
    
    async def wait_for_empty_queues(self, timeout: float = 10.0) -> bool:
        """Wait for all queues to be empty."""
        try:
            # Wait for all type-specific queues
            for queue in self._event_queues.values():
                await asyncio.wait_for(queue.join(), timeout=timeout)
            
            # Wait for global queue
            await asyncio.wait_for(self._global_queue.join(), timeout=timeout)
            
            return True
            
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for queues to empty")
            return False


class BusinessLogicEventHandler:
    """Example event handler that demonstrates business logic decoupling."""
    
    def __init__(self, storage_service: Any = None):
        """Initialize with business dependencies."""
        self.storage = storage_service
    
    async def handle_event(self, event: RealtimeEvent) -> None:
        """Handle events for business logic processing."""
        if event.event_type == RealtimeEventType.CANDLE_DATA:
            await self._handle_candle_data(event)
        elif event.event_type == RealtimeEventType.CONNECTION_STATUS:
            await self._handle_connection_status(event)
        elif event.event_type == RealtimeEventType.ERROR:
            await self._handle_error(event)
    
    async def _handle_candle_data(self, event: CandleDataEvent) -> None:
        """Handle candle data for storage and processing."""
        try:
            # Extract business data
            candle_data = event.data
            
            # Business logic: store data, trigger alerts, etc.
            if self.storage:
                # This would call storage service
                logger.debug(f"Processing candle data for {candle_data.get('symbol')}")
            
        except Exception as e:
            logger.error(f"Error handling candle data: {e}")
    
    async def _handle_connection_status(self, event: ConnectionStatusEvent) -> None:
        """Handle connection status changes."""
        status = event.data.get("status")
        logger.info(f"Connection status changed: {status}")
    
    async def _handle_error(self, event: ErrorEvent) -> None:
        """Handle error events."""
        error = event.data.get("error")
        logger.error(f"Real-time error: {error}")


# Factory functions for easy event creation
def create_candle_event(
    symbol: str,
    timeframe: str, 
    timestamp: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    **kwargs
) -> CandleDataEvent:
    """Create a candle data event."""
    data = {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        **kwargs
    }
    
    return CandleDataEvent(data=data)


def create_connection_event(status: str, **metadata) -> ConnectionStatusEvent:
    """Create a connection status event."""
    return ConnectionStatusEvent(
        data={"status": status},
        metadata=metadata
    )


def create_error_event(error: str, **metadata) -> ErrorEvent:
    """Create an error event."""
    return ErrorEvent(
        data={"error": error},
        metadata=metadata
    )