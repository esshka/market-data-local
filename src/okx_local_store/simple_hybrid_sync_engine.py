"""Simplified hybrid sync engine with direct WebSocket integration."""

import threading
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Union, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from .interfaces.sync_engine import SyncEngineInterface
from .interfaces.api_client import RequestResponseClientInterface
from .interfaces.storage import StorageInterface
from .config import OKXConfig, InstrumentConfig
from .simple_websocket_client import SimpleWebSocketClient
from .exceptions import SyncError


class SyncMode(Enum):
    """Sync mode for instruments."""
    WEBSOCKET = "websocket"
    POLLING = "polling"
    HYBRID = "hybrid"
    AUTO = "auto"


@dataclass
class InstrumentSyncState:
    """Track sync state for individual instruments."""
    symbol: str
    timeframes: Set[str] = field(default_factory=set)
    current_mode: SyncMode = SyncMode.AUTO
    polling_active: bool = False
    websocket_active: bool = False
    last_polling_data: Optional[datetime] = None
    last_websocket_data: Optional[datetime] = None
    polling_failures: int = 0


class SimplifiedHybridSyncEngine(SyncEngineInterface):
    """Simplified hybrid sync engine with direct WebSocket integration."""
    
    def __init__(
        self, 
        config: OKXConfig, 
        rest_client: RequestResponseClientInterface, 
        storage: StorageInterface,
        websocket_client: Optional[SimpleWebSocketClient] = None
    ):
        """Initialize simplified hybrid sync engine."""
        self.config = config
        self.rest_client = rest_client
        self.storage = storage
        self.websocket_client = websocket_client or SimpleWebSocketClient(
            sandbox=config.sandbox,
            websocket_config=config.websocket_config
        )
        
        # State management
        self._is_running = False
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._instrument_states: Dict[str, InstrumentSyncState] = {}
        
        # Thread pool for polling
        self._polling_executor = ThreadPoolExecutor(max_workers=config.max_concurrent_syncs)
        
        logger.info("Simplified hybrid sync engine initialized")

    def _safe_async_call(self, coro):
        """Safely call async function from sync context."""
        def run_async():
            try:
                asyncio.run(coro)
            except Exception as e:
                logger.error(f"Async call failed: {e}")
        
        try:
            # Always run in thread pool to avoid event loop conflicts
            future = self._polling_executor.submit(run_async)
            # Don't wait for completion to avoid blocking
            return future
        except Exception as e:
            logger.error(f"Failed to submit async task: {e}")

    def add_symbol(self, symbol: str, timeframes: List[str], config: Optional[InstrumentConfig] = None):
        """Add symbol for synchronization."""
        if symbol not in self._instrument_states:
            self._instrument_states[symbol] = InstrumentSyncState(
                symbol=symbol,
                timeframes=set(timeframes),
                current_mode=SyncMode.AUTO
            )
            logger.info(f"Added symbol {symbol} with timeframes {timeframes}")

    def remove_symbol(self, symbol: str):
        """Remove symbol from synchronization."""
        if symbol in self._instrument_states:
            # Stop WebSocket subscription if active
            if self._instrument_states[symbol].websocket_active:
                self._safe_async_call(self.websocket_client.unsubscribe(
                    symbol, list(self._instrument_states[symbol].timeframes)
                ))
            
            del self._instrument_states[symbol]
            logger.info(f"Removed symbol {symbol}")

    def start(self):
        """Start the sync engine."""
        if self._is_running:
            return

        self._is_running = True
        self._stop_event.clear()
        
        # Load instruments from configuration
        self._setup_instruments()
        
        # Start sync thread
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
        
        logger.info("Simplified hybrid sync engine started")

    def _setup_instruments(self):
        """Setup instruments from configuration."""
        logger.info("Setting up instruments from configuration")
        
        for instrument_config in self.config.instruments:
            if instrument_config.enabled:
                # Add symbol to sync engine
                self.add_symbol(
                    symbol=instrument_config.symbol,
                    timeframes=instrument_config.timeframes,
                    config=instrument_config
                )
                logger.info(
                    f"Loaded instrument {instrument_config.symbol} "
                    f"with timeframes {instrument_config.timeframes}"
                )
            else:
                logger.debug(f"Skipping disabled instrument {instrument_config.symbol}")
        
        logger.info(f"Loaded {len(self._instrument_states)} instruments for sync")

    def stop(self):
        """Stop the sync engine."""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()
        
        # Stop WebSocket connections safely
        self._safe_async_call(self.websocket_client.disconnect())
        
        # Wait for sync thread
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
            
        # Shutdown thread pool
        self._polling_executor.shutdown(wait=True)
        
        logger.info("Simplified hybrid sync engine stopped")

    def sync_now(self, symbol: str, timeframes: Optional[List[str]] = None) -> bool:
        """Sync symbol immediately using REST API."""
        if symbol not in self._instrument_states:
            logger.error(f"Symbol {symbol} not configured for sync")
            return False
            
        if not self.rest_client:
            logger.warning(f"No REST client available for sync of {symbol} - WebSocket-only mode")
            return False
            
        state = self._instrument_states[symbol]
        sync_timeframes = timeframes or list(state.timeframes)
        
        try:
            for timeframe in sync_timeframes:
                # Get latest data from storage
                latest_data = self.storage.get_latest_timestamp(symbol, timeframe)
                
                # Fetch new data from API
                data = self.rest_client.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    since=latest_data
                )
                
                if data:
                    # Store new data
                    self.storage.store_ohlcv_data(symbol, timeframe, data)
                    state.last_polling_data = datetime.now(timezone.utc)
                    state.polling_failures = 0
                    logger.debug(f"Synced {len(data)} candles for {symbol} {timeframe}")
                
            return True
            
        except Exception as e:
            state.polling_failures += 1
            logger.error(f"Sync failed for {symbol}: {e}")
            return False

    def _sync_loop(self):
        """Main sync loop for periodic polling."""
        logger.info("Sync loop started")
        
        while self._is_running and not self._stop_event.is_set():
            try:
                # Determine which symbols need WebSocket vs polling
                self._update_sync_modes()
                
                # Start/stop WebSocket subscriptions as needed
                self._manage_websocket_subscriptions()
                
                # Perform polling for symbols that need it
                self._perform_polling_sync()
                
                # Wait before next cycle
                self._stop_event.wait(30)  # 30 second cycle
                
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                self._stop_event.wait(5)  # Short wait on error

    def _update_sync_modes(self):
        """Update sync modes for each instrument based on activity."""
        for symbol, state in self._instrument_states.items():
            # Simple heuristic: use WebSocket if available, fallback to polling
            if self.websocket_client.is_connected():
                # Check if we should use WebSocket
                now = datetime.now(timezone.utc)
                
                # Use WebSocket if no recent failures
                if (state.last_websocket_data is None or 
                    (now - state.last_websocket_data).total_seconds() < 300):  # 5 minutes
                    
                    if not state.websocket_active:
                        # Start WebSocket subscription
                        self._safe_async_call(self._start_websocket_subscription(symbol, state))
                    state.polling_active = False
                else:
                    # WebSocket not working, use polling
                    state.websocket_active = False
                    state.polling_active = True
            else:
                # No WebSocket connection, use polling
                state.websocket_active = False
                state.polling_active = True

    async def _start_websocket_subscription(self, symbol: str, state: InstrumentSyncState):
        """Start WebSocket subscription for a symbol."""
        try:
            # Create callback for this symbol
            def data_callback(ohlcv_data: Dict):
                # Store data directly
                self.storage.store_ohlcv_data(
                    symbol=ohlcv_data['symbol'],
                    timeframe=ohlcv_data['timeframe'],
                    data=[ohlcv_data]
                )
                state.last_websocket_data = datetime.now(timezone.utc)
                
            # Subscribe to WebSocket
            success = await self.websocket_client.subscribe(
                symbol=symbol,
                timeframes=list(state.timeframes),
                callback=data_callback
            )
            
            if success:
                state.websocket_active = True
                logger.info(f"WebSocket subscription started for {symbol}")
            else:
                logger.error(f"Failed to start WebSocket subscription for {symbol}")
                state.websocket_active = False
                
        except Exception as e:
            logger.error(f"Error starting WebSocket subscription for {symbol}: {e}")
            state.websocket_active = False

    def _manage_websocket_subscriptions(self):
        """Manage WebSocket subscriptions based on current state."""
        # This runs in the sync thread, so we need to handle async calls carefully
        # For now, we'll let _update_sync_modes handle this via asyncio.create_task
        pass

    def _perform_polling_sync(self):
        """Perform polling sync for symbols that need it."""
        polling_symbols = [
            symbol for symbol, state in self._instrument_states.items()
            if state.polling_active
        ]
        
        if not polling_symbols:
            return
            
        # Submit polling tasks
        futures = []
        for symbol in polling_symbols:
            future = self._polling_executor.submit(
                self.sync_now, symbol
            )
            futures.append((symbol, future))
        
        # Wait for completion
        for symbol, future in futures:
            try:
                future.result(timeout=30)  # 30 second timeout per symbol
            except Exception as e:
                logger.error(f"Polling sync failed for {symbol}: {e}")

    def get_sync_status(self) -> Dict[str, any]:
        """Get current sync status."""
        # Build instrument states dict
        instrument_states = {}
        for symbol, state in self._instrument_states.items():
            instrument_states[symbol] = {
                'current_mode': state.current_mode.value,
                'polling_active': state.polling_active,
                'websocket_active': state.websocket_active,
                'last_polling_data': state.last_polling_data,
                'last_websocket_data': state.last_websocket_data,
                'polling_failures': state.polling_failures,
                'timeframes': list(state.timeframes)
            }
        
        # WebSocket status
        websocket_status = {
            'connected': self.websocket_client.is_connected() if self.websocket_client else False,
            'state': self.websocket_client.state.value if self.websocket_client else 'disconnected',
            'subscriptions': len(self.websocket_client.subscriptions) if self.websocket_client else 0,
            'messages_received': getattr(self.websocket_client, 'messages_received', 0),
            'reconnect_attempts': getattr(self.websocket_client, 'reconnect_attempts', 0)
        }
        
        # Count active states
        active_polling = sum(1 for state in self._instrument_states.values() if state.polling_active)
        active_websocket = sum(1 for state in self._instrument_states.values() if state.websocket_active)
        
        return {
            'is_running': self._is_running,
            'scheduled_jobs': len(self._instrument_states),  # Use instrument count as proxy
            'effective_mode': 'hybrid',  # Always hybrid for this engine
            'websocket_status': websocket_status,
            'instrument_states': instrument_states,
            'active_counts': {
                'polling': active_polling,
                'websocket': active_websocket,
                'total_instruments': len(self._instrument_states)
            },
            'recent_errors': [],  # Could be enhanced to track recent errors
            'last_sync_times': {symbol: state.last_polling_data or state.last_websocket_data 
                              for symbol, state in self._instrument_states.items()}
        }

    @property
    def is_running(self) -> bool:
        """Check if sync engine is running."""
        return self._is_running

    # Abstract method implementations required by SyncEngineInterface

    def sync_all_instruments(self) -> None:
        """Sync all enabled instruments."""
        logger.info("Starting sync for all instruments")
        for symbol in self._instrument_states.keys():
            self.sync_now(symbol)
        logger.info("Completed sync for all instruments")

    def sync_instrument(self, symbol: str) -> None:
        """Sync all timeframes for a specific instrument."""
        if symbol not in self._instrument_states:
            logger.error(f"Symbol {symbol} not configured for sync")
            return
        
        logger.info(f"Syncing instrument {symbol}")
        self.sync_now(symbol)

    def sync_timeframe(self, symbol: str, timeframe: str) -> None:
        """Sync a specific symbol and timeframe."""
        if symbol not in self._instrument_states:
            logger.error(f"Symbol {symbol} not configured for sync")
            return
            
        if timeframe not in self._instrument_states[symbol].timeframes:
            logger.warning(f"Timeframe {timeframe} not configured for {symbol}")
            
        logger.info(f"Syncing {symbol} {timeframe}")
        self.sync_now(symbol, [timeframe])

    def backfill_historical_data(
        self, 
        symbol: str, 
        timeframe: str, 
        start_date: datetime, 
        end_date: Optional[datetime] = None
    ) -> None:
        """Backfill historical data for a specific time range."""
        if symbol not in self._instrument_states:
            logger.error(f"Symbol {symbol} not configured for sync")
            return
            
        end_date = end_date or datetime.now(timezone.utc)
        logger.info(f"Backfilling {symbol} {timeframe} from {start_date} to {end_date}")
        
        if not self.rest_client:
            logger.error(f"No REST client available for backfill of {symbol} {timeframe} - WebSocket-only mode")
            raise SyncError("Backfill not available in WebSocket-only mode")
            
        try:
            # Use fetch_historical_range for the entire date range
            # The API client will handle chunking internally
            data = self.rest_client.fetch_historical_range(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_date,
                end_time=end_date,
                max_requests=50  # Allow more requests for backfill
            )
            
            if data:
                self.storage.store_ohlcv_data(symbol, timeframe, data)
                logger.info(f"Backfilled {len(data)} candles for {symbol} {timeframe}")
            else:
                logger.warning(f"No data returned for backfill of {symbol} {timeframe}")
                
        except Exception as e:
            logger.error(f"Backfill failed for {symbol} {timeframe}: {e}")
            raise SyncError(f"Backfill failed: {e}")

    def detect_and_fill_gaps(self, symbol: str, timeframe: str, max_gap_days: int = 7) -> None:
        """Detect gaps in local data and fill them."""
        if symbol not in self._instrument_states:
            logger.error(f"Symbol {symbol} not configured for sync")
            return
            
        logger.info(f"Detecting gaps for {symbol} {timeframe}")
        
        try:
            # Check if we have any data first
            record_count = self.storage.get_record_count(symbol, timeframe)
            if record_count == 0:
                logger.info(f"No existing data for {symbol} {timeframe}")
                return
            
            # Convert timeframe to milliseconds for gap detection
            timeframe_ms = self._timeframe_to_ms(timeframe)
            
            # Find gaps using storage interface
            gaps = self.storage.find_gaps(symbol, timeframe, timeframe_ms)
            
            if not gaps:
                logger.info(f"No gaps found for {symbol} {timeframe}")
                return
                
            logger.info(f"Found {len(gaps)} gaps for {symbol} {timeframe}")
            
            # Fill gaps that are within the max_gap_days limit
            max_gap_duration = timedelta(days=max_gap_days)
            
            for gap_start, gap_end in gaps:
                gap_duration = gap_end - gap_start
                
                if gap_duration <= max_gap_duration:
                    logger.info(f"Filling gap for {symbol} {timeframe} from {gap_start} to {gap_end}")
                    self.backfill_historical_data(symbol, timeframe, gap_start, gap_end)
                else:
                    logger.warning(f"Gap too large ({gap_duration}) for {symbol} {timeframe}, skipping")
                
            logger.info(f"Gap detection completed for {symbol} {timeframe}")
            
        except Exception as e:
            logger.error(f"Gap detection failed for {symbol} {timeframe}: {e}")
            raise SyncError(f"Gap detection failed: {e}")

    def _timeframe_to_ms(self, timeframe: str) -> int:
        """Convert timeframe string to milliseconds."""
        timeframe_map = {
            '1m': 60 * 1000,
            '3m': 3 * 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '1H': 60 * 60 * 1000,
            '2H': 2 * 60 * 60 * 1000,
            '4H': 4 * 60 * 60 * 1000,
            '6H': 6 * 60 * 60 * 1000,
            '12H': 12 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
            '1D': 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000,
            '1W': 7 * 24 * 60 * 60 * 1000,
            '1M': 30 * 24 * 60 * 60 * 1000,
            '3M': 90 * 24 * 60 * 60 * 1000,
        }
        return timeframe_map.get(timeframe, 60 * 1000)  # Default to 1 minute

    def force_sync_now(self, symbol: Optional[str] = None) -> None:
        """Force immediate sync for a symbol or all symbols."""
        if symbol:
            logger.info(f"Force syncing {symbol}")
            if symbol not in self._instrument_states:
                logger.error(f"Symbol {symbol} not configured for sync")
                return
            self.sync_now(symbol)
        else:
            logger.info("Force syncing all instruments")
            self.sync_all_instruments()

    def add_instrument_sync(
        self, 
        symbol: str, 
        timeframes: List[str], 
        sync_interval: int = 60
    ) -> None:
        """Add a new instrument to sync schedule."""
        logger.info(f"Adding instrument sync for {symbol} with timeframes {timeframes}")
        self.add_symbol(symbol, timeframes)
        
        # Store sync interval in instrument state if needed
        if symbol in self._instrument_states:
            # We could extend InstrumentSyncState to include sync_interval if needed
            pass

    def remove_instrument_sync(self, symbol: str) -> None:
        """Remove an instrument from sync schedule."""
        logger.info(f"Removing instrument sync for {symbol}")
        self.remove_symbol(symbol)