"""Query interface for dependency inversion."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd


class QueryInterface(ABC):
    """Abstract interface for query implementations."""
    
    @abstractmethod
    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[pd.Series]:
        """Get the most recent candle for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def get_recent_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        count: int = 100
    ) -> pd.DataFrame:
        """Get the most recent N candles."""
        pass
    
    @abstractmethod
    def get_candles_by_date_range(
        self, 
        symbol: str, 
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Get candles within a specific date range."""
        pass
    
    @abstractmethod
    def get_candles_since(
        self, 
        symbol: str, 
        timeframe: str,
        since: datetime,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """Get candles since a specific datetime."""
        pass
    
    @abstractmethod
    def get_daily_summary(self, symbol: str, date: datetime) -> Optional[Dict[str, float]]:
        """Get daily trading summary for a specific date."""
        pass
    
    @abstractmethod
    def get_multiple_symbols(
        self, 
        symbols: List[str], 
        timeframe: str,
        count: int = 100
    ) -> Dict[str, pd.DataFrame]:
        """Get recent candles for multiple symbols at once."""
        pass
    
    @abstractmethod
    def calculate_returns(
        self, 
        symbol: str, 
        timeframe: str,
        periods: int = 100
    ) -> pd.Series:
        """Calculate price returns for a symbol."""
        pass
    
    @abstractmethod
    def calculate_volatility(
        self, 
        symbol: str, 
        timeframe: str,
        window: int = 20
    ) -> Optional[float]:
        """Calculate rolling volatility for a symbol."""
        pass
    
    @abstractmethod
    def get_price_at_time(
        self, 
        symbol: str, 
        timeframe: str,
        target_time: datetime,
        price_type: str = 'close'
    ) -> Optional[float]:
        """Get price at a specific time (or closest available)."""
        pass
    
    @abstractmethod
    def get_data_coverage(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """Get information about data coverage for a symbol and timeframe."""
        pass
    
    @abstractmethod
    def export_to_csv(
        self, 
        symbol: str, 
        timeframe: str,
        output_path: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> bool:
        """Export OHLCV data to CSV file."""
        pass
    
    @abstractmethod
    def get_market_overview(self) -> Dict[str, Any]:
        """Get overview of all tracked symbols with latest prices."""
        pass
    
    @abstractmethod
    def clear_cache(self) -> None:
        """Clear query cache."""
        pass