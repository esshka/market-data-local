"""Database utility functions for SQLite operations."""

import sqlite3
from typing import Optional, List, Tuple
from contextlib import contextmanager
from pathlib import Path


class DatabaseHelper:
    """Helper class for common SQLite database operations."""
    
    @staticmethod
    def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        """Check if a table exists in the database."""
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """, (table_name,))
        return cursor.fetchone() is not None
    
    @staticmethod
    def get_table_schema(conn: sqlite3.Connection, table_name: str) -> List[Tuple[str, str]]:
        """Get table schema as list of (column_name, column_type) tuples."""
        if not DatabaseHelper.table_exists(conn, table_name):
            return []
        
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        return [(row[1], row[2]) for row in cursor.fetchall()]
    
    @staticmethod
    def create_ohlcv_table(conn: sqlite3.Connection, table_name: str) -> None:
        """Create OHLCV table with standard schema."""
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
        
        # Create performance indexes
        DatabaseHelper.create_ohlcv_indexes(conn, table_name)
        conn.commit()
    
    @staticmethod
    def create_ohlcv_indexes(conn: sqlite3.Connection, table_name: str) -> None:
        """Create performance indexes for OHLCV table."""
        indexes = [
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp ON {table_name}(timestamp)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_updated_at ON {table_name}(updated_at)"
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
    
    @staticmethod
    def optimize_database(conn: sqlite3.Connection) -> None:
        """Apply SQLite optimizations for better performance."""
        optimizations = [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL", 
            "PRAGMA cache_size=10000",
            "PRAGMA temp_store=memory",
            "PRAGMA mmap_size=268435456",  # 256MB
        ]
        
        for pragma in optimizations:
            conn.execute(pragma)
    
    @staticmethod
    def get_safe_table_name(timeframe: str) -> str:
        """Generate safe table name from timeframe."""
        return f"ohlcv_{timeframe.replace('/', '_').replace(':', '_')}"
    
    @staticmethod
    def get_database_info(conn: sqlite3.Connection) -> dict:
        """Get database information and statistics."""
        info = {}
        
        # Get database size
        cursor = conn.execute("PRAGMA page_count")
        page_count = cursor.fetchone()[0]
        cursor = conn.execute("PRAGMA page_size")
        page_size = cursor.fetchone()[0]
        info['size_bytes'] = page_count * page_size
        info['size_mb'] = info['size_bytes'] / (1024 * 1024)
        
        # Get table count
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """)
        info['table_count'] = cursor.fetchone()[0]
        
        # Get journal mode
        cursor = conn.execute("PRAGMA journal_mode")
        info['journal_mode'] = cursor.fetchone()[0]
        
        return info
    
    @staticmethod
    @contextmanager
    def transaction(conn: sqlite3.Connection):
        """Context manager for database transactions with proper rollback."""
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    @staticmethod
    def vacuum_database(conn: sqlite3.Connection) -> None:
        """Vacuum database to reclaim space and optimize performance."""
        conn.execute("VACUUM")
    
    @staticmethod
    def analyze_database(conn: sqlite3.Connection) -> None:
        """Update database statistics for query optimization."""
        conn.execute("ANALYZE")