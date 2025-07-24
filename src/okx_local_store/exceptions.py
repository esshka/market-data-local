"""Custom exceptions for OKX Local Store."""


class OKXStoreError(Exception):
    """Base exception for OKX Local Store errors."""
    pass


class ConfigurationError(OKXStoreError):
    """Configuration related errors."""
    pass


class APIError(OKXStoreError):
    """API related errors."""
    
    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class RateLimitError(APIError):
    """Rate limit exceeded error."""
    pass


class ConnectionError(APIError):
    """API connection error."""
    pass


class StorageError(OKXStoreError):
    """Storage related errors."""
    pass


class DatabaseError(StorageError):
    """Database specific errors."""
    pass


class SyncError(OKXStoreError):
    """Synchronization related errors."""
    pass


class ValidationError(OKXStoreError):
    """Data validation errors."""
    pass


class QueryError(OKXStoreError):
    """Query related errors."""
    pass


# WebSocket-specific exceptions
class WebSocketError(OKXStoreError):
    """Base WebSocket related errors."""
    pass


class WebSocketConnectionError(WebSocketError):
    """WebSocket connection failed."""
    
    def __init__(self, message: str, retry_count: int = 0, max_retries: int = 0):
        super().__init__(message)
        self.retry_count = retry_count
        self.max_retries = max_retries


class WebSocketSubscriptionError(WebSocketError):
    """WebSocket subscription failed."""
    
    def __init__(self, message: str, symbol: str = None, timeframe: str = None):
        super().__init__(message)
        self.symbol = symbol
        self.timeframe = timeframe


class WebSocketTimeoutError(WebSocketError):
    """WebSocket operation timed out."""
    pass


class WebSocketDataError(WebSocketError):
    """WebSocket data parsing or validation error."""
    
    def __init__(self, message: str, raw_data: dict = None):
        super().__init__(message)
        self.raw_data = raw_data or {}