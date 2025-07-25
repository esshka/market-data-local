"""Main OKX Local Store class that coordinates all components."""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from loguru import logger
import sys

from .config import OKXConfig, create_default_config
from .query_interface import OHLCVQueryInterface
from .interfaces.config import ConfigurationProviderInterface
from .interfaces.api_client import APIClientInterface
from .interfaces.storage import StorageInterface
from .interfaces.sync_engine import SyncEngineInterface
from .interfaces.query import QueryInterface
from .simple_transport_strategy import SimpleTransportStrategyFactory, create_transport_components
from .exceptions import OKXStoreError, ConfigurationError


class OKXLocalStore:
    """
    Main interface for OKX Local Store - a local storage system for OHLCV data.
    
    This class coordinates the API client, storage, sync engine, and query interface
    to provide a complete solution for caching OKX market data locally.
    """
    
    def __init__(
        self, 
        config_path: Optional[Path] = None, 
        config: Optional[ConfigurationProviderInterface] = None,
        api_client: Optional[APIClientInterface] = None,
        storage: Optional[StorageInterface] = None,
        sync_engine: Optional[SyncEngineInterface] = None,
        query_interface: Optional[QueryInterface] = None
    ):
        """
        Initialize OKX Local Store.
        
        Args:
            config_path: Path to configuration file
            config: Configuration object (alternative to config_path)
            api_client: Custom API client (for dependency injection)
            storage: Custom storage implementation (for dependency injection)
            sync_engine: Custom sync engine (for dependency injection)
            query_interface: Custom query interface (for dependency injection)
        """
        try:
            # Load or create configuration
            if config:
                self.config = config
            elif config_path:
                self.config = OKXConfig.load_from_file(config_path)
            else:
                # Use default config path
                default_config_path = Path.home() / '.okx_local_store' / 'config.json'
                self.config = OKXConfig.load_from_file(default_config_path)
            
            # Set up logging
            self._setup_logging()
            
            # Initialize components using transport strategy (with dependency injection support)
            if storage or api_client or sync_engine:
                # Manual dependency injection mode
                self.storage = storage or self._create_storage_fallback()
                self.api_client = api_client or self._create_api_client_fallback()
                self.query = query_interface or OHLCVQueryInterface(self.storage, self.config)
                self.sync_engine = sync_engine or self._create_sync_engine_fallback()
                self.transport_components = None
            else:
                # Use transport strategy for integrated setup
                self.transport_components = self._create_transport_components()
                self.storage = self.transport_components['storage']
                self.api_client = self.transport_components['api_client']
                self.query = query_interface or OHLCVQueryInterface(self.storage, self.config)
                self.sync_engine = self.transport_components['sync_engine']
            
            logger.info("OKX Local Store initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize OKX Local Store: {e}")
            raise OKXStoreError(f"Initialization failed: {e}")

    def _setup_logging(self):
        """Set up logging configuration."""
        # Remove default logger
        logger.remove()
        
        # Add console handler
        logger.add(
            sys.stdout,
            level=self.config.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        
        # Add file handler if specified
        if self.config.log_file:
            logger.add(
                self.config.log_file,
                level=self.config.log_level,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                rotation="10 MB",
                retention="7 days"
            )

    def _create_transport_components(self) -> Dict[str, Any]:
        """Create transport components using strategy pattern."""
        try:
            # Use transport strategy factory for clean component creation
            components = create_transport_components(self.config)
            
            logger.info(f"Transport components created: {components['strategy_description']}")
            return components
            
        except Exception as e:
            logger.error(f"Failed to create transport components: {e}")
            raise ConfigurationError(f"Transport component creation failed: {e}")

    def _create_storage_fallback(self) -> StorageInterface:
        """Fallback storage creation for dependency injection mode."""
        try:
            # Import here to avoid circular dependencies
            from .storage import OHLCVStorage
            from .realtime_storage import RealtimeOHLCVStorage
            
            enable_websocket = getattr(self.config, 'enable_websocket', False)
            
            if enable_websocket:
                logger.info("Creating real-time optimized storage for WebSocket mode")
                return RealtimeOHLCVStorage(self.config.data_dir)
            else:
                # Use standard storage for polling mode
                logger.info("Creating standard storage for polling mode")
                return OHLCVStorage(self.config.data_dir)
        except Exception as e:
            logger.error(f"Failed to create storage: {e}")
            raise ConfigurationError(f"Storage creation failed: {e}")
    
    def _create_api_client_fallback(self) -> APIClientInterface:
        """Fallback API client creation for dependency injection mode."""
        try:
            # Import here to avoid circular dependencies
            from .api_client import OKXAPIClient
            from .websocket_api_client import WebSocketAPIClient
            
            realtime_mode = getattr(self.config, 'realtime_mode', 'polling')
            enable_websocket = getattr(self.config, 'enable_websocket', False)
            
            if realtime_mode == 'websocket' and enable_websocket:
                logger.info("Creating WebSocket API client for real-time streaming")
                return WebSocketAPIClient(
                    sandbox=self.config.sandbox,
                    websocket_config=getattr(self.config, 'websocket_config', None)
                )
            else:
                logger.info("Creating REST API client")
                return OKXAPIClient(
                    sandbox=self.config.sandbox,
                    rate_limit_per_minute=self.config.rate_limit_per_minute
                )
        except Exception as e:
            logger.error(f"Failed to create API client: {e}")
            raise ConfigurationError(f"API client creation failed: {e}")

    def _create_sync_engine_fallback(self) -> SyncEngineInterface:
        """Fallback sync engine creation for dependency injection mode."""
        try:
            # Import here to avoid circular dependencies  
            from .sync_engine import SyncEngine
            from .hybrid_sync_engine import HybridSyncEngine
            
            realtime_mode = getattr(self.config, 'realtime_mode', 'polling')
            enable_websocket = getattr(self.config, 'enable_websocket', False)
            
            if enable_websocket and realtime_mode in ['websocket', 'hybrid', 'auto']:
                logger.info(f"Creating HybridSyncEngine for {realtime_mode} mode")
                # Create with old-style dependencies for backward compatibility
                return HybridSyncEngine(
                    config=self.config,
                    rest_client=self.api_client,
                    storage=self.storage
                )
            else:
                logger.info("Creating standard SyncEngine for polling mode")
                return SyncEngine(self.config, self.api_client, self.storage)
        except Exception as e:
            logger.error(f"Failed to create sync engine: {e}")
            raise ConfigurationError(f"Sync engine creation failed: {e}")

    def start(self):
        """Start the local store with automatic syncing."""
        logger.info("Starting OKX Local Store...")
        
        # Test API connection (if available)
        if self.api_client and not self.api_client.test_connection():
            logger.warning("API connection test failed - continuing with limited functionality")
        elif not self.api_client:
            logger.info("WebSocket-only mode - no REST API client available")
        
        # Start sync engine
        if self.config.enable_auto_sync:
            self.sync_engine.start()
            logger.info("Auto-sync enabled")
        else:
            logger.info("Auto-sync disabled")
        
        logger.info("OKX Local Store started successfully")

    def stop(self):
        """Stop the local store and cleanup resources."""
        logger.info("Stopping OKX Local Store...")
        
        # Stop sync engine
        self.sync_engine.stop()
        
        # Close storage connections
        self.storage.close_all_connections()
        
        logger.info("OKX Local Store stopped")

    def add_symbol(self, symbol: str, timeframes: List[str] = None, sync_interval: int = 60):
        """
        Add a new symbol to track.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-USDT')
            timeframes: List of timeframes to track
            sync_interval: Sync interval in seconds
        """
        if not timeframes:
            timeframes = ['1m', '5m', '1h', '1d']
        
        # Add to configuration
        self.config.add_instrument(
            symbol=symbol,
            timeframes=timeframes,
            sync_interval_seconds=sync_interval
        )
        
        # Add to sync engine if running
        if self.sync_engine._is_running:
            self.sync_engine.add_instrument_sync(symbol, timeframes, sync_interval)
        
        logger.info(f"Added symbol {symbol} with timeframes {timeframes}")

    def remove_symbol(self, symbol: str):
        """
        Remove a symbol from tracking.
        
        Args:
            symbol: Trading pair symbol to remove
        """
        # Remove from sync engine
        if self.sync_engine._is_running:
            self.sync_engine.remove_instrument_sync(symbol)
        
        # Remove from configuration
        self.config.instruments = [
            inst for inst in self.config.instruments 
            if inst.symbol != symbol
        ]
        
        logger.info(f"Removed symbol {symbol}")

    def sync_now(self, symbol: Optional[str] = None):
        """
        Force immediate sync for a symbol or all symbols.
        
        Args:
            symbol: Specific symbol to sync, or None for all symbols
        """
        self.sync_engine.force_sync_now(symbol)

    def backfill(self, symbol: str, timeframe: str, start_date: datetime, end_date: Optional[datetime] = None):
        """
        Backfill historical data for a symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            start_date: Start date for backfill
            end_date: End date for backfill (defaults to now)
        """
        self.sync_engine.backfill_historical_data(symbol, timeframe, start_date, end_date)

    def detect_gaps(self, symbol: str, timeframe: str):
        """
        Detect and fill gaps in data for a symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
        """
        self.sync_engine.detect_and_fill_gaps(symbol, timeframe)

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status of the local store."""
        return {
            'config': {
                'instruments_count': len(self.config.instruments),
                'enabled_instruments': len([i for i in self.config.instruments if i.enabled]),
                'auto_sync_enabled': self.config.enable_auto_sync,
                'data_directory': str(self.config.data_dir)
            },
            'sync_engine': self.sync_engine.get_sync_status(),
            'storage': self.storage.get_storage_stats(),
            'api_client': {
                'connection_ok': self.api_client.test_connection() if self.api_client else False,
                'sandbox_mode': self.config.sandbox,
                'websocket_only_mode': self.api_client is None
            }
        }

    def get_market_overview(self) -> Dict[str, Any]:
        """Get market overview with latest data for all tracked symbols."""
        return self.query.get_market_overview()

    def export_data(self, symbol: str, timeframe: str, output_path: str, 
                   start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> bool:
        """
        Export OHLCV data to CSV file.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            output_path: Output file path
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            True if export successful
        """
        return self.query.export_to_csv(symbol, timeframe, output_path, start_date, end_date)

    def save_config(self, config_path: Optional[Path] = None):
        """
        Save current configuration to file.
        
        Args:
            config_path: Path to save configuration (uses default if None)
        """
        if not config_path:
            config_path = Path.home() / '.okx_local_store' / 'config.json'
        
        self.config.save_to_file(config_path)
        logger.info(f"Configuration saved to {config_path}")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


def create_default_store(symbols: List[str] = None) -> OKXLocalStore:
    """
    Create a default OKX Local Store instance with common configuration.
    
    Args:
        symbols: List of symbols to track (uses defaults if None)
        
    Returns:
        Configured OKXLocalStore instance
    """
    config = create_default_config()
    
    # Add custom symbols if provided
    if symbols:
        config.instruments.clear()  # Remove defaults
        for symbol in symbols:
            config.add_instrument(symbol)
    
    return OKXLocalStore(config=config)