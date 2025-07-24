"""WebSocket API client for real-time OKX data streaming."""

# For backward compatibility, import the simplified client
from .simple_websocket_client import SimpleWebSocketClient, ConnectionState, Subscription

# Alias for existing code compatibility  
WebSocketAPIClient = SimpleWebSocketClient

# Re-export for existing imports
__all__ = ['WebSocketAPIClient', 'SimpleWebSocketClient', 'ConnectionState', 'Subscription']