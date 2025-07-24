"""SQLite storage manager for OHLCV data."""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timezone
import threading
from contextlib import contextmanager
from loguru import logger


class OHLCVStorage:
    """SQLite-based storage for OHLCV candlestick data."""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._connections: Dict[str, sqlite3.Connection] = {}
        self._lock = threading.RLock()

    def _get_db_path(self, symbol: str) -> Path:
        """Get database path for a symbol."""
        safe_symbol = symbol.replace('/', '-').replace(':', '-')
        return self.data_dir / f"{safe_symbol}.db"

    @contextmanager
    def _get_connection(self, symbol: str):
        """Get thread-safe database connection for a symbol."""
        with self._lock:
            db_path = self._get_db_path(symbol)
            conn_key = str(db_path)
            
            if conn_key not in self._connections:
                self._connections[conn_key] = sqlite3.connect(
                    db_path, 
                    check_same_thread=False,
                    timeout=30.0
                )
                self._connections[conn_key].execute("PRAGMA journal_mode=WAL")
                self._connections[conn_key].execute("PRAGMA synchronous=NORMAL")
                self._connections[conn_key].execute("PRAGMA cache_size=10000")
            
            yield self._connections[conn_key]

    def _create_table(self, conn: sqlite3.Connection, timeframe: str) -> None:
        """Create table for a specific timeframe if it doesn't exist."""
        table_name = f"ohlcv_{timeframe.replace('/', '_')}"
        
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                timestamp INTEGER PRIMARY KEY,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                vol_currency REAL,
                updated_at INTEGER NOT NULL,
                UNIQUE(timestamp)
            )
        """)
        
        # Create indexes for better query performance
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp 
            ON {table_name}(timestamp)
        """)
        
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_updated_at 
            ON {table_name}(updated_at)
        """)
        
        conn.commit()

    def _table_name(self, timeframe: str) -> str:
        """Get table name for timeframe."""
        return f"ohlcv_{timeframe.replace('/', '_')}"

    def store_ohlcv_data(self, symbol: str, timeframe: str, data: List[Dict[str, Any]]) -> int:
        """
        Store OHLCV data for a symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-USDT')
            timeframe: Candlestick timeframe (e.g., '1m', '1h', '1d')
            data: List of OHLCV dictionaries with keys: timestamp, open, high, low, close, volume, vol_currency
        
        Returns:
            Number of records inserted/updated
        """
        if not data:
            return 0

        with self._get_connection(symbol) as conn:
            self._create_table(conn, timeframe)
            table_name = self._table_name(timeframe)
            
            current_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            # Prepare data for insertion
            records = []
            for candle in data:
                records.append((
                    int(candle['timestamp']),
                    float(candle['open']),
                    float(candle['high']),
                    float(candle['low']),
                    float(candle['close']),
                    float(candle['volume']),
                    float(candle.get('vol_currency', 0)),
                    current_time
                ))
            
            # Use INSERT OR REPLACE for upsert behavior
            conn.executemany(f"""
                INSERT OR REPLACE INTO {table_name} 
                (timestamp, open, high, low, close, volume, vol_currency, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            
            conn.commit()
            
            logger.info(f"Stored {len(records)} candles for {symbol} {timeframe}")
            return len(records)

    def get_ohlcv_data(
        self, 
        symbol: str, 
        timeframe: str, 
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Retrieve OHLCV data for a symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            start_time: Start datetime (UTC)
            end_time: End datetime (UTC)
            limit: Maximum number of records to return
        
        Returns:
            Pandas DataFrame with OHLCV data
        """
        with self._get_connection(symbol) as conn:
            table_name = self._table_name(timeframe)
            
            # Check if table exists
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return pd.DataFrame(columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'vol_currency'
                ])
            
            # Build query
            query = f"SELECT timestamp, open, high, low, close, volume, vol_currency FROM {table_name}"
            params = []
            conditions = []
            
            if start_time:
                conditions.append("timestamp >= ?")
                params.append(int(start_time.timestamp() * 1000))
            
            if end_time:
                conditions.append("timestamp <= ?")
                params.append(int(end_time.timestamp() * 1000))
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY timestamp ASC"
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            # Execute query and return DataFrame
            df = pd.read_sql_query(query, conn, params=params)
            
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df.set_index('timestamp', inplace=True)
            
            return df

    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get the latest timestamp for a symbol and timeframe."""
        with self._get_connection(symbol) as conn:
            table_name = self._table_name(timeframe)
            
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return None
            
            cursor = conn.execute(f"""
                SELECT MAX(timestamp) FROM {table_name}
            """)
            
            result = cursor.fetchone()[0]
            if result:
                return datetime.fromtimestamp(result / 1000, tz=timezone.utc)
            
            return None

    def get_earliest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get the earliest timestamp for a symbol and timeframe."""
        with self._get_connection(symbol) as conn:
            table_name = self._table_name(timeframe)
            
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return None
            
            cursor = conn.execute(f"""
                SELECT MIN(timestamp) FROM {table_name}
            """)
            
            result = cursor.fetchone()[0]
            if result:
                return datetime.fromtimestamp(result / 1000, tz=timezone.utc)
            
            return None

    def get_record_count(self, symbol: str, timeframe: str) -> int:
        """Get the number of records for a symbol and timeframe."""
        with self._get_connection(symbol) as conn:
            table_name = self._table_name(timeframe)
            
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return 0
            
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cursor.fetchone()[0]

    def find_gaps(self, symbol: str, timeframe: str, expected_interval_ms: int) -> List[Tuple[datetime, datetime]]:
        """
        Find gaps in the data where candles are missing.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe  
            expected_interval_ms: Expected interval between candles in milliseconds
        
        Returns:
            List of (start_time, end_time) tuples representing gaps
        """
        with self._get_connection(symbol) as conn:
            table_name = self._table_name(timeframe)
            
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return []
            
            # Find gaps by comparing consecutive timestamps
            cursor = conn.execute(f"""
                SELECT timestamp, 
                       LAG(timestamp) OVER (ORDER BY timestamp) as prev_timestamp
                FROM {table_name}
                ORDER BY timestamp
            """)
            
            gaps = []
            for row in cursor:
                if row[1] is not None:  # Skip first row
                    gap_size = row[0] - row[1]
                    if gap_size > expected_interval_ms * 1.5:  # Allow some tolerance
                        gap_start = datetime.fromtimestamp((row[1] + expected_interval_ms) / 1000, tz=timezone.utc)
                        gap_end = datetime.fromtimestamp((row[0] - expected_interval_ms) / 1000, tz=timezone.utc)
                        gaps.append((gap_start, gap_end))
            
            return gaps

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = {
            'total_symbols': 0,
            'total_records': 0,
            'symbols': {}
        }
        
        for db_file in self.data_dir.glob("*.db"):
            symbol = db_file.stem.replace('-', '/')
            stats['total_symbols'] += 1
            
            symbol_stats = {
                'timeframes': {},
                'total_records': 0,
                'file_size_mb': db_file.stat().st_size / (1024 * 1024)
            }
            
            with self._get_connection(symbol) as conn:
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name LIKE 'ohlcv_%'
                """)
                
                for (table_name,) in cursor:
                    timeframe = table_name.replace('ohlcv_', '').replace('_', '/')
                    
                    count_cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = count_cursor.fetchone()[0]
                    
                    symbol_stats['timeframes'][timeframe] = count
                    symbol_stats['total_records'] += count
            
            stats['symbols'][symbol] = symbol_stats
            stats['total_records'] += symbol_stats['total_records']
        
        return stats

    def close_all_connections(self):
        """Close all database connections."""
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()

    def __del__(self):
        """Cleanup when storage is destroyed."""
        try:
            self.close_all_connections()
        except:
            pass