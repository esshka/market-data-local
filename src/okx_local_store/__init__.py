"""
OKX Local Store - A local storage system for OHLCV candlestick data from OKX.

This package provides a complete solution for syncing and querying OHLCV data
from the OKX exchange, storing it locally in SQLite databases for fast access.

Main Components:
- OKXLocalStore: Main interface class
- OKXConfig: Configuration management
- OHLCVStorage: SQLite-based storage
- OKXAPIClient: CCXT-based API client
- SyncEngine: Data synchronization
- OHLCVQueryInterface: Query interface

Example usage:
    >>> from okx_local_store import OKXLocalStore, create_default_store
    >>> 
    >>> # Create with default configuration
    >>> store = create_default_store(['BTC-USDT', 'ETH-USDT'])
    >>> 
    >>> # Start syncing
    >>> with store:
    >>>     # Get latest candle
    >>>     latest = store.query.get_latest_candle('BTC-USDT', '1h')
    >>>     
    >>>     # Get recent candles
    >>>     recent = store.query.get_recent_candles('BTC-USDT', '1d', 30)
    >>>     
    >>>     # Force sync
    >>>     store.sync_now('BTC-USDT')
"""

__version__ = "0.1.0"
__author__ = "eugeny"
__email__ = "esshka@gmail.com"

# Main classes
from .okx_store import OKXLocalStore, create_default_store
from .config import OKXConfig, InstrumentConfig, create_default_config
from .api_client import OKXAPIClient
from .storage import OHLCVStorage
from .simple_hybrid_sync_engine import SimplifiedHybridSyncEngine as SyncEngine
from .query_interface import OHLCVQueryInterface

# Convenience imports
__all__ = [
    # Main interface
    'OKXLocalStore',
    'create_default_store',
    
    # Configuration
    'OKXConfig',
    'InstrumentConfig', 
    'create_default_config',
    
    # Core components
    'OKXAPIClient',
    'OHLCVStorage',
    'SyncEngine', 
    'OHLCVQueryInterface',
    
    # Package info
    '__version__',
    '__author__',
    '__email__',
]