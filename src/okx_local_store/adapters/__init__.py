"""Adapters for transforming external data formats into internal representations."""

from .websocket_adapter import (
    WebSocketDataAdapter, WebSocketMessageAdapter,
    OKXCandleAdapter, OKXTickerAdapter, OKXEventAdapter,
    create_okx_websocket_adapter
)

__all__ = [
    'WebSocketDataAdapter', 'WebSocketMessageAdapter',
    'OKXCandleAdapter', 'OKXTickerAdapter', 'OKXEventAdapter', 
    'create_okx_websocket_adapter'
]