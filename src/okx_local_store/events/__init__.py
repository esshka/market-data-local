"""Event-driven architecture components for decoupled communication."""

from .realtime_events import (
    RealtimeEventBus, RealtimeEvent, CandleDataEvent, TickerDataEvent,
    ConnectionStatusEvent, SubscriptionStatusEvent, ErrorEvent,
    create_candle_event, create_connection_event, create_error_event,
    BusinessLogicEventHandler
)

__all__ = [
    'RealtimeEventBus', 'RealtimeEvent', 'CandleDataEvent', 'TickerDataEvent',
    'ConnectionStatusEvent', 'SubscriptionStatusEvent', 'ErrorEvent',
    'create_candle_event', 'create_connection_event', 'create_error_event',
    'BusinessLogicEventHandler'
]