"""Sync engine interface for dependency inversion."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime


class SyncEngineInterface(ABC):
    """Abstract interface for sync engine implementations."""
    
    @abstractmethod
    def start(self) -> None:
        """Start the sync engine."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the sync engine."""
        pass
    
    @abstractmethod
    def sync_all_instruments(self) -> None:
        """Sync all enabled instruments."""
        pass
    
    @abstractmethod
    def sync_instrument(self, symbol: str) -> None:
        """Sync all timeframes for a specific instrument."""
        pass
    
    @abstractmethod
    def sync_timeframe(self, symbol: str, timeframe: str) -> None:
        """Sync a specific symbol and timeframe."""
        pass
    
    @abstractmethod
    def backfill_historical_data(
        self, 
        symbol: str, 
        timeframe: str, 
        start_date: datetime, 
        end_date: Optional[datetime] = None
    ) -> None:
        """Backfill historical data for a specific time range."""
        pass
    
    @abstractmethod
    def detect_and_fill_gaps(self, symbol: str, timeframe: str, max_gap_days: int = 7) -> None:
        """Detect gaps in local data and fill them."""
        pass
    
    @abstractmethod
    def force_sync_now(self, symbol: Optional[str] = None) -> None:
        """Force immediate sync for a symbol or all symbols."""
        pass
    
    @abstractmethod
    def add_instrument_sync(self, symbol: str, timeframes: List[str], sync_interval: int = 60) -> None:
        """Add a new instrument to sync schedule."""
        pass
    
    @abstractmethod
    def remove_instrument_sync(self, symbol: str) -> None:
        """Remove an instrument from sync schedule."""
        pass
    
    @abstractmethod
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        pass
    
    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Check if sync engine is running."""
        pass