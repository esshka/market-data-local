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