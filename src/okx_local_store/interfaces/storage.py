"""Storage interface for dependency inversion."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import pandas as pd


class StorageInterface(ABC):
    """Abstract interface for storage implementations."""
    
    @abstractmethod
    def store_ohlcv_data(self, symbol: str, timeframe: str, data: List[Dict[str, Any]]) -> int:
        """Store OHLCV data for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def get_ohlcv_data(
        self, 
        symbol: str, 
        timeframe: str, 
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """Retrieve OHLCV data for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get the latest timestamp for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def get_earliest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get the earliest timestamp for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def get_record_count(self, symbol: str, timeframe: str) -> int:
        """Get the number of records for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def find_gaps(self, symbol: str, timeframe: str, expected_interval_ms: int) -> List[Tuple[datetime, datetime]]:
        """Find gaps in the data where candles are missing."""
        pass
    
    @abstractmethod
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        pass
    
    @abstractmethod
    def close_all_connections(self) -> None:
        """Close all storage connections."""
        pass