"""Enhanced storage manager optimized for real-time WebSocket data ingestion."""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Set
from datetime import datetime, timezone
import threading
import time
import queue
from contextlib import contextmanager
from dataclasses import dataclass, field
from loguru import logger

from .storage import OHLCVStorage
from .interfaces.storage import StorageInterface
from .utils.database import DatabaseHelper
from .exceptions import StorageError, DatabaseError


@dataclass
class BatchedWrite:
    """Represents a batched write operation."""
    symbol: str
    timeframe: str
    data: List[Dict[str, Any]]
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"


@dataclass
class RealtimeStorageStats:
    """Statistics for real-time storage operations."""
    total_writes: int = 0
    batched_writes: int = 0
    websocket_writes: int = 0
    polling_writes: int = 0
    deduplicated_records: int = 0
    failed_writes: int = 0
    last_write_time: Optional[datetime] = None
    buffer_size: int = 0


class RealtimeOHLCVStorage(OHLCVStorage):
    """
    Enhanced SQLite storage optimized for real-time WebSocket data ingestion.
    
    Features:
    - Batched write operations for high-frequency updates
    - Data source tracking (WebSocket vs REST)
    - Optimized indexes for real-time queries
    - Automatic data deduplication
    - Write buffering and background processing
    """
    
    def __init__(
        self, 
        data_dir: Path, 
        batch_size: int = 100,
        batch_timeout: float = 5.0,
        enable_batching: bool = True
    ):
        """
        Initialize real-time storage with batching capabilities.
        
        Args:
            data_dir: Directory for database files
            batch_size: Maximum records per batch
            batch_timeout: Maximum seconds to wait before flushing batch
            enable_batching: Enable batched writes for performance
        """
        super().__init__(data_dir)
        
        # Batching configuration
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.enable_batching = enable_batching
        
        # Batching infrastructure
        self._write_queue: queue.Queue = queue.Queue()
        self._batch_buffer: Dict[str, List[BatchedWrite]] = {}
        self._batch_lock = threading.Lock()
        self._batch_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        
        # Statistics tracking
        self._stats = RealtimeStorageStats()
        self._stats_lock = threading.Lock()
        
        # Enhanced connection settings for real-time performance
        self._enhanced_pragma_settings = {
            "journal_mode": "WAL",
            "synchronous": "NORMAL", 
            "cache_size": 20000,  # Increased cache
            "temp_store": "memory",
            "mmap_size": 268435456,  # 256MB memory map
            "wal_autocheckpoint": 1000,
            "optimize": True
        }
        
        # Start batch processing if enabled
        if self.enable_batching:
            self._start_batch_processor()
        
        logger.info(f"Real-time storage initialized (batching: {enable_batching}, batch_size: {batch_size})")
    
    def _start_batch_processor(self):
        """Start background batch processing thread."""
        self._batch_thread = threading.Thread(target=self._batch_processor, daemon=True)
        self._batch_thread.start()
        logger.info("Batch processor started")
    
    def _batch_processor(self):
        """Background thread for processing batched writes."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    # Process queued writes
                    self._process_write_queue()
                    
                    # Flush timed-out batches
                    self._flush_timed_out_batches()
                    
                    # Sleep briefly
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error in batch processor: {e}")
                    time.sleep(1)
                    
        except Exception as e:
            logger.error(f"Batch processor crashed: {e}")
    
    def _process_write_queue(self):
        """Process pending writes from the queue."""
        processed_count = 0
        
        while not self._write_queue.empty() and processed_count < 100:
            try:
                batch_write = self._write_queue.get_nowait()
                self._add_to_batch(batch_write)
                processed_count += 1
                
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error processing write queue: {e}")
    
    def _add_to_batch(self, batch_write: BatchedWrite):
        """Add write operation to batch buffer."""
        with self._batch_lock:
            batch_key = f"{batch_write.symbol}:{batch_write.timeframe}"
            
            if batch_key not in self._batch_buffer:
                self._batch_buffer[batch_key] = []
            
            self._batch_buffer[batch_key].append(batch_write)
            
            # Check if batch is ready to flush
            if len(self._batch_buffer[batch_key]) >= self.batch_size:
                self._flush_batch(batch_key)
    
    def _flush_timed_out_batches(self):
        """Flush batches that have exceeded timeout."""
        current_time = time.time()
        
        with self._batch_lock:
            keys_to_flush = []
            
            for batch_key, batch_writes in self._batch_buffer.items():
                if batch_writes:
                    oldest_write = min(batch_writes, key=lambda x: x.timestamp)
                    if current_time - oldest_write.timestamp >= self.batch_timeout:
                        keys_to_flush.append(batch_key)
            
            for batch_key in keys_to_flush:
                self._flush_batch(batch_key)
    
    def _flush_batch(self, batch_key: str):
        """Flush a specific batch to database."""
        if batch_key not in self._batch_buffer or not self._batch_buffer[batch_key]:
            return
        
        batch_writes = self._batch_buffer[batch_key]
        self._batch_buffer[batch_key] = []
        
        try:
            # Group by symbol and timeframe
            symbol = batch_writes[0].symbol
            timeframe = batch_writes[0].timeframe
            
            # Combine all data
            all_data = []
            sources = set()
            
            for batch_write in batch_writes:
                all_data.extend(batch_write.data)
                sources.add(batch_write.source)
            
            # Write to database
            if all_data:
                stored_count = self._store_ohlcv_batch(symbol, timeframe, all_data, sources)
                
                # Update statistics
                with self._stats_lock:
                    self._stats.batched_writes += 1
                    self._stats.total_writes += stored_count
                    self._stats.buffer_size = sum(len(b) for b in self._batch_buffer.values())
                    self._stats.last_write_time = datetime.now(timezone.utc)
                    
                    for source in sources:
                        if source == "websocket":
                            self._stats.websocket_writes += stored_count
                        elif source == "polling":
                            self._stats.polling_writes += stored_count
                
                logger.debug(f"Flushed batch: {symbol} {timeframe} ({stored_count} records from {sources})")
                
        except Exception as e:
            logger.error(f"Error flushing batch {batch_key}: {e}")
            with self._stats_lock:
                self._stats.failed_writes += len(batch_writes)

    @contextmanager
    def _get_enhanced_connection(self, symbol: str):
        """Get database connection with enhanced real-time settings."""
        with self._lock:
            db_path = self._get_db_path(symbol)
            conn_key = str(db_path)
            
            if conn_key not in self._connections:
                conn = sqlite3.connect(
                    db_path, 
                    check_same_thread=False,
                    timeout=60.0  # Increased timeout for real-time operations
                )
                
                # Apply enhanced PRAGMA settings
                for pragma, value in self._enhanced_pragma_settings.items():
                    if isinstance(value, bool):
                        conn.execute(f"PRAGMA {pragma}={int(value)}")
                    else:
                        conn.execute(f"PRAGMA {pragma}={value}")
                
                self._connections[conn_key] = conn
            
            yield self._connections[conn_key]
    
    def _create_enhanced_table(self, conn: sqlite3.Connection, timeframe: str) -> None:
        """Create table with enhanced schema for real-time data."""
        table_name = f"ohlcv_{timeframe.replace('/', '_')}"
        
        # Enhanced schema with data source tracking
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
                data_source TEXT DEFAULT 'unknown',
                is_confirmed BOOLEAN DEFAULT 1,
                created_at INTEGER DEFAULT (strftime('%s','now') * 1000),
                UNIQUE(timestamp)
            )
        """)
        
        # Enhanced indexes for real-time queries
        indexes = [
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp ON {table_name}(timestamp)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_updated_at ON {table_name}(updated_at)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_data_source ON {table_name}(data_source)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_confirmed ON {table_name}(is_confirmed)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_recent ON {table_name}(timestamp DESC, data_source)",
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
        
        conn.commit()
    
    def _store_ohlcv_batch(
        self, 
        symbol: str, 
        timeframe: str, 
        data: List[Dict[str, Any]], 
        sources: Set[str]
    ) -> int:
        """Store batched OHLCV data with deduplication."""
        if not data:
            return 0
        
        try:
            with self._get_enhanced_connection(symbol) as conn:
                self._create_enhanced_table(conn, timeframe)
                table_name = self._table_name(timeframe)
                
                current_time = int(datetime.now(timezone.utc).timestamp() * 1000)
                
                # Deduplicate data by timestamp
                deduped_data = {}
                duplicate_count = 0
                
                for candle in data:
                    timestamp = int(candle['timestamp'])
                    
                    if timestamp in deduped_data:
                        # Keep the most recent update (higher updated_at)
                        existing_updated = deduped_data[timestamp].get('updated_at', 0)
                        new_updated = candle.get('updated_at', current_time)
                        
                        if new_updated > existing_updated:
                            deduped_data[timestamp] = candle
                        duplicate_count += 1
                    else:
                        deduped_data[timestamp] = candle
                
                if duplicate_count > 0:
                    with self._stats_lock:
                        self._stats.deduplicated_records += duplicate_count
                    logger.debug(f"Deduplicated {duplicate_count} records for {symbol} {timeframe}")
                
                # Prepare records for insertion
                records = []
                for timestamp, candle in deduped_data.items():
                    try:
                        # Determine data source
                        data_source = candle.get('data_source', 'unknown')
                        if not data_source or data_source == 'unknown':
                            data_source = list(sources)[0] if sources else 'unknown'
                        
                        records.append((
                            timestamp,
                            float(candle['open']),
                            float(candle['high']),
                            float(candle['low']),
                            float(candle['close']),
                            float(candle['volume']),
                            float(candle.get('vol_currency', 0)),
                            candle.get('updated_at', current_time),
                            data_source,
                            candle.get('is_confirmed', True),
                            current_time
                        ))
                    except (KeyError, ValueError, TypeError) as e:
                        logger.warning(f"Invalid candle data for {symbol} {timeframe}: {e}")
                        continue
                
                if not records:
                    logger.warning(f"No valid records to store for {symbol} {timeframe}")
                    return 0
                
                # Batch insert with conflict resolution
                with DatabaseHelper.transaction(conn):
                    conn.executemany(f"""
                        INSERT OR REPLACE INTO {table_name} 
                        (timestamp, open, high, low, close, volume, vol_currency, 
                         updated_at, data_source, is_confirmed, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, records)
                
                logger.debug(f"Stored {len(records)} candles for {symbol} {timeframe}")
                return len(records)
                
        except Exception as e:
            logger.error(f"Error storing batch OHLCV data for {symbol} {timeframe}: {e}")
            raise StorageError(f"Failed to store batch data for {symbol} {timeframe}: {e}")
    
    def store_realtime_data(
        self, 
        symbol: str, 
        timeframe: str, 
        data: List[Dict[str, Any]], 
        source: str = "websocket"
    ) -> int:
        """
        Store real-time data with batching optimization.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            data: List of OHLCV dictionaries
            source: Data source identifier (websocket, polling, etc.)
        
        Returns:
            Number of records queued for storage
        """
        if not data:
            return 0
        
        # Add source information to data
        enhanced_data = []
        for candle in data:
            enhanced_candle = candle.copy()
            enhanced_candle['data_source'] = source
            enhanced_data.append(enhanced_candle)
        
        if self.enable_batching:
            # Queue for batched processing
            batch_write = BatchedWrite(
                symbol=symbol,
                timeframe=timeframe,
                data=enhanced_data,
                source=source
            )
            
            try:
                self._write_queue.put_nowait(batch_write)
                logger.debug(f"Queued {len(data)} records for {symbol} {timeframe} ({source})")
                return len(data)
                
            except queue.Full:
                logger.warning(f"Write queue full, falling back to direct write for {symbol} {timeframe}")
                return self._store_ohlcv_batch(symbol, timeframe, enhanced_data, {source})
        else:
            # Direct write
            return self._store_ohlcv_batch(symbol, timeframe, enhanced_data, {source})
    
    def store_ohlcv_data(self, symbol: str, timeframe: str, data: List[Dict[str, Any]]) -> int:
        """
        Override parent method to use enhanced storage.
        
        This maintains compatibility with existing code while providing enhancements.
        """
        return self.store_realtime_data(symbol, timeframe, data, source="polling")
    
    def get_latest_by_source(
        self, 
        symbol: str, 
        timeframe: str, 
        source: str, 
        limit: int = 1
    ) -> List[Dict[str, Any]]:
        """Get latest candles from specific data source."""
        try:
            with self._get_enhanced_connection(symbol) as conn:
                table_name = self._table_name(timeframe)
                
                cursor = conn.execute(f"""
                    SELECT timestamp, open, high, low, close, volume, vol_currency, 
                           updated_at, data_source, is_confirmed
                    FROM {table_name}
                    WHERE data_source = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (source, limit))
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        'timestamp': row[0],
                        'open': row[1],
                        'high': row[2],
                        'low': row[3],
                        'close': row[4],
                        'volume': row[5],
                        'vol_currency': row[6],
                        'updated_at': row[7],
                        'data_source': row[8],
                        'is_confirmed': bool(row[9])
                    })
                
                return results
                
        except Exception as e:
            logger.error(f"Error getting latest data by source for {symbol} {timeframe} {source}: {e}")
            return []
    
    def get_data_sources(self, symbol: str, timeframe: str) -> List[str]:
        """Get list of data sources available for symbol/timeframe."""
        try:
            with self._get_enhanced_connection(symbol) as conn:
                table_name = self._table_name(timeframe)
                
                cursor = conn.execute(f"""
                    SELECT DISTINCT data_source 
                    FROM {table_name}
                    WHERE data_source IS NOT NULL
                    ORDER BY data_source
                """)
                
                return [row[0] for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting data sources for {symbol} {timeframe}: {e}")
            return []
    
    def get_source_stats(self, symbol: str, timeframe: str) -> Dict[str, int]:
        """Get record counts by data source."""
        try:
            with self._get_enhanced_connection(symbol) as conn:
                table_name = self._table_name(timeframe)
                
                cursor = conn.execute(f"""
                    SELECT data_source, COUNT(*) as count
                    FROM {table_name}
                    GROUP BY data_source
                    ORDER BY count DESC
                """)
                
                return {row[0]: row[1] for row in cursor.fetchall()}
                
        except Exception as e:
            logger.error(f"Error getting source stats for {symbol} {timeframe}: {e}")
            return {}
    
    def force_flush_batches(self):
        """Force flush all pending batches immediately."""
        if not self.enable_batching:
            return
        
        with self._batch_lock:
            batch_keys = list(self._batch_buffer.keys())
            
        for batch_key in batch_keys:
            self._flush_batch(batch_key)
        
        logger.info(f"Force flushed {len(batch_keys)} batches")
    
    def get_realtime_stats(self) -> Dict[str, Any]:
        """Get real-time storage statistics."""
        with self._stats_lock:
            return {
                'total_writes': self._stats.total_writes,
                'batched_writes': self._stats.batched_writes,
                'websocket_writes': self._stats.websocket_writes,
                'polling_writes': self._stats.polling_writes,
                'deduplicated_records': self._stats.deduplicated_records,
                'failed_writes': self._stats.failed_writes,
                'last_write_time': self._stats.last_write_time,
                'current_buffer_size': self._stats.buffer_size,
                'write_queue_size': self._write_queue.qsize(),
                'batching_enabled': self.enable_batching,
                'batch_size': self.batch_size,
                'batch_timeout': self.batch_timeout
            }
    
    def close_all_connections(self):
        """Close all connections and cleanup resources."""
        # Stop batch processor
        if self.enable_batching:
            self._shutdown_event.set()
            
            if self._batch_thread and self._batch_thread.is_alive():
                self._batch_thread.join(timeout=5)
            
            # Flush any remaining batches
            self.force_flush_batches()
        
        # Close parent connections
        super().close_all_connections()
        
        logger.info("Real-time storage closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close_all_connections()