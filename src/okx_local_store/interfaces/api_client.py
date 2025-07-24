"""API client interface for dependency inversion."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator, Callable
from datetime import datetime
import asyncio


class APIClientInterface(ABC):
    """Abstract interface for API client implementations."""
    
    @abstractmethod
    def get_available_symbols(self) -> List[str]:
        """Get all available trading symbols."""
        pass
    
    @abstractmethod
    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a trading symbol."""
        pass
    
    @abstractmethod
    def fetch_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        since: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV data from the API."""
        pass
    
    @abstractmethod
    def fetch_latest_candle(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest candle for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def fetch_historical_range(
        self, 
        symbol: str, 
        timeframe: str, 
        start_time: datetime, 
        end_time: datetime,
        max_requests: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch historical data for a specific time range."""
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the API connection is working."""
        pass
    
    @abstractmethod
    def get_exchange_status(self) -> Dict[str, Any]:
        """Get exchange status information."""
        pass
    
    # WebSocket-specific methods
    @abstractmethod
    async def watch_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> None:
        """Set up WebSocket watch for OHLCV data via callback."""
        pass
    
    @abstractmethod
    async def subscribe_symbol(self, symbol: str, timeframes: List[str]) -> bool:
        """Subscribe to WebSocket updates for a symbol and timeframes."""
        pass
    
    @abstractmethod
    async def unsubscribe_symbol(self, symbol: str, timeframes: Optional[List[str]] = None) -> bool:
        """Unsubscribe from WebSocket updates for a symbol."""
        pass
    
    @abstractmethod
    def get_websocket_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status information."""
        pass
    
    @abstractmethod
    async def start_websocket(self) -> bool:
        """Start WebSocket connection."""
        pass
    
    @abstractmethod
    async def stop_websocket(self) -> bool:
        """Stop WebSocket connection."""
        pass
    
    @abstractmethod
    def is_websocket_connected(self) -> bool:
        """Check if WebSocket is connected."""
        pass