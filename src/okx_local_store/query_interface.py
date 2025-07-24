"""Query interface for fast local OHLCV data access."""

import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Union, Any
from functools import lru_cache
import threading
from loguru import logger

from .interfaces.storage import StorageInterface
from .interfaces.config import ConfigurationProviderInterface
from .interfaces.query import QueryInterface
from .utils.timeframes import get_timeframe_duration_minutes
from .exceptions import QueryError


class OHLCVQueryInterface(QueryInterface):
    """High-level interface for querying local OHLCV data."""
    
    def __init__(self, storage: StorageInterface, config: ConfigurationProviderInterface):
        self.storage = storage
        self.config = config
        self._cache_lock = threading.RLock()
        
        # Clear cache periodically to avoid stale data
        self._cache_clear_interval = 300  # 5 minutes

    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[pd.Series]:
        """
        Get the most recent candle for a symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            
        Returns:
            Latest candle as pandas Series or None if no data
        """
        try:
            df = self.storage.get_ohlcv_data(
                symbol=symbol,
                timeframe=timeframe,
                limit=1
            )
            
            if not df.empty:
                return df.iloc[-1]
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest candle for {symbol} {timeframe}: {e}")
            return None

    def get_recent_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        count: int = 100
    ) -> pd.DataFrame:
        """
        Get the most recent N candles.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            count: Number of recent candles to retrieve
            
        Returns:
            DataFrame with recent candles
        """
        try:
            return self.storage.get_ohlcv_data(
                symbol=symbol,
                timeframe=timeframe,
                limit=count
            )
        except Exception as e:
            logger.error(f"Error getting recent candles for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def get_candles_by_date_range(
        self, 
        symbol: str, 
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Get candles within a specific date range.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)
            
        Returns:
            DataFrame with candles in the specified range
        """
        try:
            return self.storage.get_ohlcv_data(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_date,
                end_time=end_date
            )
        except Exception as e:
            logger.error(f"Error getting candles by date range for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def get_candles_since(
        self, 
        symbol: str, 
        timeframe: str,
        since: datetime,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get candles since a specific datetime.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            since: Start datetime (UTC)
            limit: Optional limit on number of candles
            
        Returns:
            DataFrame with candles since the specified time
        """
        try:
            return self.storage.get_ohlcv_data(
                symbol=symbol,
                timeframe=timeframe,
                start_time=since,
                limit=limit
            )
        except Exception as e:
            logger.error(f"Error getting candles since {since} for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def get_daily_summary(self, symbol: str, date: datetime) -> Optional[Dict[str, float]]:
        """
        Get daily trading summary for a specific date.
        
        Args:
            symbol: Trading pair symbol
            date: Date to get summary for
            
        Returns:
            Dictionary with daily trading statistics
        """
        try:
            # Get 1-minute data for the entire day
            start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)
            
            df = self.get_candles_by_date_range(symbol, '1m', start_date, end_date)
            
            if df.empty:
                return None
            
            return {
                'date': date.date(),
                'open': float(df.iloc[0]['open']),
                'high': float(df['high'].max()),
                'low': float(df['low'].min()),
                'close': float(df.iloc[-1]['close']),
                'volume': float(df['volume'].sum()),
                'vol_currency': float(df['vol_currency'].sum()),
                'candle_count': len(df),
                'price_change': float(df.iloc[-1]['close'] - df.iloc[0]['open']),
                'price_change_pct': float((df.iloc[-1]['close'] - df.iloc[0]['open']) / df.iloc[0]['open'] * 100)
            }
            
        except Exception as e:
            logger.error(f"Error getting daily summary for {symbol} on {date}: {e}")
            return None

    def get_multiple_symbols(
        self, 
        symbols: List[str], 
        timeframe: str,
        count: int = 100
    ) -> Dict[str, pd.DataFrame]:
        """
        Get recent candles for multiple symbols at once.
        
        Args:
            symbols: List of trading pair symbols
            timeframe: Candlestick timeframe
            count: Number of recent candles per symbol
            
        Returns:
            Dictionary mapping symbols to their DataFrames
        """
        result = {}
        
        for symbol in symbols:
            try:
                df = self.get_recent_candles(symbol, timeframe, count)
                if not df.empty:
                    result[symbol] = df
            except Exception as e:
                logger.error(f"Error getting data for {symbol}: {e}")
                result[symbol] = pd.DataFrame()
        
        return result

    def calculate_returns(
        self, 
        symbol: str, 
        timeframe: str,
        periods: int = 100
    ) -> pd.Series:
        """
        Calculate price returns for a symbol.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            periods: Number of periods to calculate returns for
            
        Returns:
            Series with calculated returns
        """
        try:
            df = self.get_recent_candles(symbol, timeframe, periods + 1)
            
            if len(df) < 2:
                return pd.Series(dtype=float)
            
            returns = df['close'].pct_change().dropna()
            return returns
            
        except Exception as e:
            logger.error(f"Error calculating returns for {symbol} {timeframe}: {e}")
            return pd.Series(dtype=float)

    def calculate_volatility(
        self, 
        symbol: str, 
        timeframe: str,
        window: int = 20
    ) -> Optional[float]:
        """
        Calculate rolling volatility for a symbol.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            window: Rolling window size
            
        Returns:
            Current volatility value
        """
        try:
            returns = self.calculate_returns(symbol, timeframe, window + 10)
            
            if len(returns) < window:
                return None
            
            volatility = returns.rolling(window=window).std().iloc[-1]
            return float(volatility) if pd.notna(volatility) else None
            
        except Exception as e:
            logger.error(f"Error calculating volatility for {symbol} {timeframe}: {e}")
            return None

    def get_price_at_time(
        self, 
        symbol: str, 
        timeframe: str,
        target_time: datetime,
        price_type: str = 'close'
    ) -> Optional[float]:
        """
        Get price at a specific time (or closest available).
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            target_time: Target datetime
            price_type: Price type ('open', 'high', 'low', 'close')
            
        Returns:
            Price at target time or None if no data
        """
        try:
            # Get data around the target time
            start_time = target_time - timedelta(hours=1)
            end_time = target_time + timedelta(hours=1)
            
            df = self.get_candles_by_date_range(symbol, timeframe, start_time, end_time)
            
            if df.empty:
                return None
            
            # Find the candle closest to target time
            time_diffs = abs(df.index - target_time)
            closest_idx = time_diffs.idxmin()
            
            return float(df.loc[closest_idx, price_type])
            
        except Exception as e:
            logger.error(f"Error getting price at time for {symbol} {timeframe}: {e}")
            return None

    def get_data_coverage(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """
        Get information about data coverage for a symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            
        Returns:
            Dictionary with coverage information
        """
        try:
            earliest = self.storage.get_earliest_timestamp(symbol, timeframe)
            latest = self.storage.get_latest_timestamp(symbol, timeframe)
            count = self.storage.get_record_count(symbol, timeframe)
            
            coverage = {
                'symbol': symbol,
                'timeframe': timeframe,
                'earliest_data': earliest,
                'latest_data': latest,
                'record_count': count,
                'data_span_days': None,
                'completeness_pct': None
            }
            
            if earliest and latest:
                data_span = (latest - earliest).total_seconds() / 86400  # Days
                coverage['data_span_days'] = data_span
                
                # Estimate expected number of candles
                tf_minutes = self._timeframe_to_minutes(timeframe)
                if tf_minutes:
                    expected_candles = int(data_span * 24 * 60 / tf_minutes)
                    if expected_candles > 0:
                        coverage['completeness_pct'] = min(100, (count / expected_candles) * 100)
            
            return coverage
            
        except Exception as e:
            logger.error(f"Error getting data coverage for {symbol} {timeframe}: {e}")
            return {}

    def _timeframe_to_minutes(self, timeframe: str) -> Optional[int]:
        """Convert timeframe string to minutes."""
        return get_timeframe_duration_minutes(timeframe)

    def export_to_csv(
        self, 
        symbol: str, 
        timeframe: str,
        output_path: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> bool:
        """
        Export OHLCV data to CSV file.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            output_path: Path to output CSV file
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            True if export successful, False otherwise
        """
        try:
            if start_date and end_date:
                df = self.get_candles_by_date_range(symbol, timeframe, start_date, end_date)
            else:
                df = self.storage.get_ohlcv_data(symbol, timeframe)
            
            if df.empty:
                logger.warning(f"No data to export for {symbol} {timeframe}")
                return False
            
            # Reset index to include timestamp as column
            df_export = df.reset_index()
            df_export.to_csv(output_path, index=False)
            
            logger.info(f"Exported {len(df_export)} candles to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting data to CSV: {e}")
            return False

    def get_market_overview(self) -> Dict[str, Any]:
        """
        Get overview of all tracked symbols with latest prices.
        
        Returns:
            Dictionary with market overview data
        """
        overview = {
            'symbols': {},
            'total_symbols': 0,
            'last_updated': datetime.now(timezone.utc)
        }
        
        for instrument in self.config.instruments:
            if not instrument.enabled:
                continue
            
            symbol_data = {
                'timeframes': {},
                'latest_price': None,
                'data_coverage': {}
            }
            
            for timeframe in instrument.timeframes:
                try:
                    # Get latest candle
                    latest = self.get_latest_candle(instrument.symbol, timeframe)
                    if latest is not None:
                        symbol_data['timeframes'][timeframe] = {
                            'latest_time': latest.name,
                            'close_price': float(latest['close']),
                            'volume': float(latest['volume'])
                        }
                        
                        # Use daily close as latest price if available
                        if timeframe == '1d' or (symbol_data['latest_price'] is None and timeframe == '1h'):
                            symbol_data['latest_price'] = float(latest['close'])
                    
                    # Get data coverage
                    coverage = self.get_data_coverage(instrument.symbol, timeframe)
                    symbol_data['data_coverage'][timeframe] = coverage
                    
                except Exception as e:
                    logger.error(f"Error getting overview for {instrument.symbol} {timeframe}: {e}")
            
            if symbol_data['timeframes']:
                overview['symbols'][instrument.symbol] = symbol_data
                overview['total_symbols'] += 1
        
        return overview

    @lru_cache(maxsize=128)
    def _cached_get_recent_candles(self, symbol: str, timeframe: str, count: int, cache_key: int) -> pd.DataFrame:
        """Cached version of get_recent_candles (cache_key used for cache invalidation)."""
        return self.storage.get_ohlcv_data(symbol=symbol, timeframe=timeframe, limit=count)

    def clear_cache(self):
        """Clear query cache."""
        with self._cache_lock:
            self._cached_get_recent_candles.cache_clear()
            logger.debug("Query cache cleared")