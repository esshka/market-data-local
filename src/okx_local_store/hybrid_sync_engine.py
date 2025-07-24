"""Hybrid sync engine focused on REST polling with real-time coordination support."""

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from .interfaces.sync_engine import SyncEngineInterface
from .interfaces.api_client import RequestResponseClientInterface
from .interfaces.storage import StorageInterface
from .config import OKXConfig, InstrumentConfig
from .api_client import OKXAPIClient
from .exceptions import SyncError
from .services.realtime_coordinator import RealtimeDataCoordinator
from .events.realtime_events import RealtimeEventBus


class SyncMode(Enum):
    """Sync mode for instruments."""
    WEBSOCKET = "websocket"
    POLLING = "polling"
    HYBRID = "hybrid"
    AUTO = "auto"


@dataclass
class InstrumentSyncState:
    """Track sync state for individual instruments (polling-focused)."""
    symbol: str
    timeframes: Set[str] = field(default_factory=set)
    current_mode: SyncMode = SyncMode.AUTO
    polling_active: bool = False
    last_polling_data: Optional[datetime] = None
    polling_failures: int = 0
    realtime_active: bool = False  # Managed by RealtimeDataCoordinator
    
    def should_use_polling(self) -> bool:
        """Determine if should use polling mode."""
        # Use polling if realtime is not active or configured for polling
        return (self.current_mode == SyncMode.POLLING or 
                not self.realtime_active or
                self.polling_failures < 3)


class HybridSyncEngine(SyncEngineInterface):
    """
    Hybrid sync engine focused on REST polling with real-time coordination support.
    WebSocket logic is handled by RealtimeDataCoordinator for proper separation.
    """
    
    def __init__(
        self, 
        config: OKXConfig, 
        rest_client: RequestResponseClientInterface, 
        storage: StorageInterface,
        event_bus: Optional[RealtimeEventBus] = None,
        realtime_coordinator: Optional[RealtimeDataCoordinator] = None
    ):
        """
        Initialize hybrid sync engine focused on REST polling.
        
        Args:
            config: Configuration with sync settings
            rest_client: REST API client for data fetching
            storage: Storage interface for data persistence
            event_bus: Optional event bus for real-time integration
            realtime_coordinator: Optional coordinator for real-time data
        """
        self.config = config
        self.rest_client = rest_client
        self.storage = storage
        self.event_bus = event_bus
        self.realtime_coordinator = realtime_coordinator
        
        # Sync engine state
        self._is_running = False
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Instrument sync state tracking
        self._instrument_states: Dict[str, InstrumentSyncState] = {}
        self._sync_status: Dict[str, Dict[str, datetime]] = {}
        self._sync_errors: Dict[str, List[str]] = {}
        
        # Mode management
        self._effective_mode = self._determine_effective_mode()
        
        # Scheduled polling executor
        self._polling_executor = ThreadPoolExecutor(max_workers=config.max_concurrent_syncs)
        
        logger.info(f"Hybrid sync engine initialized with mode: {self._effective_mode}")
    
    def _determine_effective_mode(self) -> SyncMode:
        """Determine effective sync mode based on configuration."""
        # This sync engine focuses on polling - real-time is handled separately
        mode_map = {
            "websocket": SyncMode.POLLING,  # Real-time handled by coordinator
            "polling": SyncMode.POLLING,
            "hybrid": SyncMode.HYBRID,  # Polling + real-time coordination
            "auto": SyncMode.HYBRID
        }
        
        return mode_map.get(self.config.realtime_mode, SyncMode.POLLING)
    
    def _initialize_realtime_coordinator(self):
        """Initialize real-time coordinator if needed and not provided."""
        if (not self.realtime_coordinator and 
            self._effective_mode == SyncMode.HYBRID and
            self.config.enable_websocket):
            
            # Create event bus if not provided
            if not self.event_bus:
                self.event_bus = RealtimeEventBus()
            
            # Create coordinator
            self.realtime_coordinator = RealtimeDataCoordinator(
                config=self.config,
                storage=self.storage,
                event_bus=self.event_bus
            )
    
    def _run_realtime_coordinator(self):
        """Run real-time coordinator in separate event loop."""
        import asyncio
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Start event bus
            loop.run_until_complete(self.event_bus.start())
            
            # Start coordinator
            loop.run_until_complete(self.realtime_coordinator.start())
            
            # Keep running until stop event
            while not self._stop_event.is_set():
                loop.run_until_complete(asyncio.sleep(1))
                
        except Exception as e:
            logger.error(f"Error in realtime coordinator thread: {e}")
        finally:
            # Cleanup
            try:
                if self.realtime_coordinator:
                    loop.run_until_complete(self.realtime_coordinator.stop())
                if self.event_bus:
                    loop.run_until_complete(self.event_bus.stop())
            except Exception as e:
                logger.error(f"Error cleaning up realtime coordinator: {e}")
            finally:
                loop.close()
    
    def start(self) -> None:
        """Start the hybrid sync engine."""
        if self._is_running:
            logger.warning("Hybrid sync engine is already running")
            return
        
        self._is_running = True
        self._stop_event.clear()
        
        # Initialize real-time coordinator if needed
        self._initialize_realtime_coordinator()
        
        # Initialize instrument states
        self._initialize_instrument_states()
        
        # Start real-time coordinator if available
        if self.realtime_coordinator and self._effective_mode == SyncMode.HYBRID:
            # Start coordinator in background thread
            import asyncio
            self._sync_thread = threading.Thread(
                target=self._run_realtime_coordinator, 
                daemon=True
            )
            self._sync_thread.start()
        
        # Run initial sync if configured
        if self.config.sync_on_startup:
            logger.info("Running initial sync on startup")
            self.sync_all_instruments()
        
        # Start scheduled polling for hybrid/polling modes
        if self._effective_mode in [SyncMode.POLLING, SyncMode.HYBRID]:
            self._start_scheduled_polling()
        
        logger.info(f"Hybrid sync engine started in {self._effective_mode.value} mode")
    
    def stop(self) -> None:
        """Stop the hybrid sync engine."""
        if not self._is_running:
            return
        
        logger.info("Stopping hybrid sync engine...")
        self._stop_event.set()
        self._is_running = False
        
        # Stop async operations
        if self._loop and not self._loop.is_closed():
            try:
                # Schedule the stop operation and wait for it
                future = asyncio.run_coroutine_threadsafe(self._stop_async_operations(), self._loop)
                future.result(timeout=3.0)  # Wait up to 3 seconds for graceful shutdown
            except Exception as e:
                logger.warning(f"Error during async shutdown: {e}")
        
        # Wait for sync thread to finish
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5)
            if self._sync_thread.is_alive():
                logger.warning("Sync thread did not stop gracefully")
        
        # Shutdown polling executor
        self._polling_executor.shutdown(wait=True)
        
        logger.info("Hybrid sync engine stopped")
    
    def _initialize_instrument_states(self):
        """Initialize sync state for all configured instruments."""
        for instrument in self.config.instruments:
            if not instrument.enabled:
                continue
                
            state = InstrumentSyncState(
                symbol=instrument.symbol,
                timeframes=set(instrument.timeframes),
                current_mode=self._get_instrument_mode(instrument)
            )
            
            self._instrument_states[instrument.symbol] = state
            
            logger.info(f"Initialized {instrument.symbol} with mode: {state.current_mode.value}")
    
    def _get_instrument_mode(self, instrument: InstrumentConfig) -> SyncMode:
        """Determine sync mode for specific instrument."""
        # Per-instrument override
        if hasattr(instrument, 'realtime_source'):
            if instrument.realtime_source == "websocket":
                return SyncMode.WEBSOCKET
            elif instrument.realtime_source == "polling":
                return SyncMode.POLLING
            elif instrument.realtime_source == "auto":
                return self._effective_mode
        
        # Fall back to global mode
        return self._effective_mode
    
    def _run_async_operations(self):
        """Run async WebSocket operations in dedicated thread."""
        try:
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Start WebSocket operations
            self._websocket_task = self._loop.create_task(self._websocket_manager())
            
            # Run event loop
            self._loop.run_until_complete(self._websocket_task)
            
        except asyncio.CancelledError:
            logger.info("Async operations cancelled during shutdown")
        except Exception as e:
            logger.error(f"Error in async operations: {e}")
        finally:
            if self._loop and not self._loop.is_closed():
                # Cancel any pending tasks before closing the loop
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                
                # Wait for tasks to complete cancellation
                if pending:
                    try:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception:
                        pass  # Ignore exceptions during cleanup
                
                self._loop.close()
    
    async def _websocket_manager(self):
        """Manage WebSocket connections and subscriptions."""
        try:
            if not self.websocket_client:
                logger.error("WebSocket client not initialized")
                return
            
            # Start WebSocket connection
            success = await self.websocket_client.start_websocket()
            if not success:
                logger.error("Failed to start WebSocket connection")
                await self._handle_websocket_failure()
                return
            
            # Subscribe to all WebSocket-enabled instruments
            await self._subscribe_websocket_instruments()
            
            # Monitor connections and handle reconnections
            while self._is_running and not self._stop_event.is_set():
                try:
                    await self._monitor_websocket_health()
                    await asyncio.sleep(10)  # Check every 10 seconds
                except asyncio.CancelledError:
                    logger.info("WebSocket manager cancelled during shutdown")
                    break
                    
        except asyncio.CancelledError:
            logger.info("WebSocket manager task cancelled")
        except Exception as e:
            logger.error(f"Error in WebSocket manager: {e}")
            await self._handle_websocket_failure()
    
    async def _subscribe_websocket_instruments(self):
        """Subscribe to WebSocket data for all eligible instruments."""
        for symbol, state in self._instrument_states.items():
            if state.current_mode in [SyncMode.WEBSOCKET, SyncMode.HYBRID]:
                try:
                    # Subscribe to all timeframes for this symbol
                    success = await self.websocket_client.subscribe_symbol(
                        symbol, 
                        list(state.timeframes)
                    )
                    
                    if success:
                        state.websocket_active = True
                        state.websocket_failures = 0
                        logger.info(f"Subscribed to WebSocket data for {symbol}")
                        
                        # Set up data callback
                        await self._setup_websocket_callback(symbol, state.timeframes)
                    else:
                        logger.warning(f"Failed to subscribe to WebSocket for {symbol}")
                        state.websocket_failures += 1
                        
                except Exception as e:
                    logger.error(f"Error subscribing to {symbol}: {e}")
                    state.websocket_failures += 1
    
    async def _setup_websocket_callback(self, symbol: str, timeframes: Set[str]):
        """Set up WebSocket data callback for instrument."""
        async def data_callback(data: Dict):
            try:
                # Process real-time WebSocket data
                await self._process_websocket_data(symbol, data)
            except Exception as e:
                logger.error(f"Error processing WebSocket data for {symbol}: {e}")
        
        # Set up callback for each timeframe
        for timeframe in timeframes:
            try:
                await self.websocket_client.watch_ohlcv(symbol, timeframe, data_callback)
            except Exception as e:
                logger.error(f"Error setting up WebSocket watch for {symbol} {timeframe}: {e}")
    
    async def _process_websocket_data(self, symbol: str, data: Dict):
        """Process incoming WebSocket data."""
        try:
            timeframe = data.get('timeframe')
            if not timeframe:
                return
            
            # Convert to storage format
            storage_data = [{
                'timestamp': data['timestamp'],
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'close': data['close'],
                'volume': data['volume'],
                'vol_currency': data.get('vol_currency'),
                'updated_at': int(time.time() * 1000)
            }]
            
            # Store data
            stored_count = self.storage.store_ohlcv_data(symbol, timeframe, storage_data)
            
            if stored_count > 0:
                # Update sync state
                if symbol in self._instrument_states:
                    self._instrument_states[symbol].last_websocket_data = datetime.now(timezone.utc)
                
                # Update sync status
                self._update_sync_status(symbol, timeframe, success=True, source="websocket")
                
                logger.debug(f"Stored WebSocket data: {symbol} {timeframe} ({stored_count} records)")
            
        except Exception as e:
            logger.error(f"Error processing WebSocket data: {e}")
            self._update_sync_status(symbol, timeframe, success=False, error=str(e), source="websocket")
    
    async def _monitor_websocket_health(self):
        """Monitor WebSocket connection health and handle fallbacks."""
        if not self.websocket_client:
            return
        
        for symbol, state in self._instrument_states.items():
            if not state.websocket_active:
                continue
            
            # Check if should fallback to polling
            if state.should_fallback_to_polling():
                logger.warning(f"WebSocket failing for {symbol}, falling back to polling")
                await self._activate_polling_fallback(symbol, state)
            
            # Check if should retry WebSocket after cooldown
            elif state.fallback_active and state.should_retry_websocket():
                logger.info(f"Retrying WebSocket for {symbol}")
                await self._retry_websocket_connection(symbol, state)
    
    async def _activate_polling_fallback(self, symbol: str, state: InstrumentSyncState):
        """Activate polling fallback for failed WebSocket connection."""
        try:
            # Unsubscribe from WebSocket
            await self.websocket_client.unsubscribe_symbol(symbol)
            
            # Update state
            state.websocket_active = False
            state.fallback_active = True
            state.polling_active = True
            
            logger.info(f"Activated polling fallback for {symbol}")
            
        except Exception as e:
            logger.error(f"Error activating polling fallback for {symbol}: {e}")
    
    async def _retry_websocket_connection(self, symbol: str, state: InstrumentSyncState):
        """Retry WebSocket connection after fallback cooldown."""
        try:
            # Attempt to resubscribe
            success = await self.websocket_client.subscribe_symbol(symbol, list(state.timeframes))
            
            if success:
                # Reactivate WebSocket
                state.websocket_active = True
                state.fallback_active = False
                state.polling_active = False
                state.websocket_failures = 0
                
                # Re-setup callback
                await self._setup_websocket_callback(symbol, state.timeframes)
                
                logger.info(f"Successfully reactivated WebSocket for {symbol}")
            else:
                logger.warning(f"Failed to reactivate WebSocket for {symbol}")
                state.websocket_failures += 1
                
        except Exception as e:
            logger.error(f"Error retrying WebSocket for {symbol}: {e}")
            state.websocket_failures += 1
    
    async def _handle_websocket_failure(self):
        """Handle overall WebSocket system failure."""
        logger.error("WebSocket system failure - falling back to polling for all instruments")
        
        # Fall back all WebSocket instruments to polling
        for symbol, state in self._instrument_states.items():
            if state.current_mode in [SyncMode.WEBSOCKET, SyncMode.HYBRID]:
                state.websocket_active = False
                state.fallback_active = True
                state.polling_active = True
    
    async def _stop_async_operations(self):
        """Stop async WebSocket operations."""
        try:
            if self.websocket_client:
                await self.websocket_client.stop_websocket()
                
            # Cancel WebSocket task and wait for it to complete
            if self._websocket_task and not self._websocket_task.done():
                self._websocket_task.cancel()
                try:
                    await asyncio.wait_for(self._websocket_task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    # Expected when cancelling or timing out
                    pass
                
        except asyncio.CancelledError:
            logger.info("Stop operations cancelled")
        except Exception as e:
            logger.error(f"Error stopping async operations: {e}")
    
    def _start_scheduled_polling(self):
        """Start scheduled polling for instruments using polling mode."""
        # Import schedule here to avoid circular imports
        import schedule
        
        # Clear any existing jobs
        schedule.clear()
        
        # Schedule polling for each instrument
        for instrument in self.config.instruments:
            if not instrument.enabled:
                continue
            
            state = self._instrument_states.get(instrument.symbol)
            if not state:
                continue
            
            # Schedule polling if needed
            if (state.current_mode in [SyncMode.POLLING, SyncMode.HYBRID] or 
                state.fallback_active):
                
                schedule.every(instrument.sync_interval_seconds).seconds.do(
                    self._sync_instrument_polling, instrument.symbol
                )
                
                logger.info(f"Scheduled polling for {instrument.symbol} every {instrument.sync_interval_seconds}s")
        
        # Start scheduler thread
        def run_scheduler():
            while self._is_running and not self._stop_event.is_set():
                schedule.run_pending()
                time.sleep(1)
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
    
    def _sync_instrument_polling(self, symbol: str):
        """Sync instrument using REST polling."""
        try:
            state = self._instrument_states.get(symbol)
            if not state or not state.polling_active:
                return
            
            instrument = self.config.get_instrument(symbol)
            if not instrument:
                return
            
            logger.debug(f"Polling sync for {symbol}")
            
            # Sync each timeframe
            for timeframe in state.timeframes:
                try:
                    self._sync_timeframe_polling(symbol, timeframe)
                    state.last_polling_data = datetime.now(timezone.utc)
                    state.polling_failures = 0
                    
                except Exception as e:
                    logger.error(f"Error syncing {symbol} {timeframe} via polling: {e}")
                    state.polling_failures += 1
                    self._update_sync_status(symbol, timeframe, success=False, error=str(e), source="polling")
                    
        except Exception as e:
            logger.error(f"Error in polling sync for {symbol}: {e}")
    
    def _sync_timeframe_polling(self, symbol: str, timeframe: str):
        """Sync specific timeframe using REST API."""
        # Get latest local timestamp
        latest_local = self.storage.get_latest_timestamp(symbol, timeframe)
        
        if latest_local:
            # Incremental sync
            since = latest_local + timedelta(milliseconds=self._get_timeframe_duration_ms(timeframe))
        else:
            # Initial sync
            instrument = self.config.get_instrument(symbol)
            days_back = instrument.max_history_days if instrument else 30
            since = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        # Fetch data from REST API
        candles = self.rest_client.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            limit=1000
        )
        
        if candles:
            stored_count = self.storage.store_ohlcv_data(symbol, timeframe, candles)
            self._update_sync_status(symbol, timeframe, success=True, source="polling")
            logger.debug(f"Polling stored {stored_count} candles for {symbol} {timeframe}")
    
    def _get_timeframe_duration_ms(self, timeframe: str) -> int:
        """Get timeframe duration in milliseconds."""
        # Import here to avoid circular dependency
        from .utils.timeframes import get_timeframe_duration_ms
        return get_timeframe_duration_ms(timeframe)
    
    def _update_sync_status(self, symbol: str, timeframe: str, success: bool, error: str = None, source: str = "unknown"):
        """Update sync status tracking."""
        if symbol not in self._sync_status:
            self._sync_status[symbol] = {}
        
        if symbol not in self._sync_errors:
            self._sync_errors[symbol] = []
        
        # Update status with source information
        status_key = f"{timeframe}_{source}"
        self._sync_status[symbol][status_key] = datetime.now(timezone.utc)
        
        if not success and error:
            error_msg = f"{timeframe} ({source}): {error}"
            self._sync_errors[symbol].append(error_msg)
            # Keep only last 10 errors per symbol
            if len(self._sync_errors[symbol]) > 10:
                self._sync_errors[symbol] = self._sync_errors[symbol][-10:]

    # Implement SyncEngineInterface methods
    
    def sync_all_instruments(self) -> None:
        """Sync all enabled instruments."""
        enabled_instruments = [inst for inst in self.config.instruments if inst.enabled]
        
        if not enabled_instruments:
            logger.warning("No enabled instruments to sync")
            return
        
        logger.info(f"Starting sync for {len(enabled_instruments)} instruments")
        
        # For WebSocket instruments, they're already syncing via subscriptions
        # For polling instruments, trigger immediate sync
        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_syncs) as executor:
            futures = []
            
            for inst in enabled_instruments:
                state = self._instrument_states.get(inst.symbol)
                if state and (state.polling_active or state.current_mode == SyncMode.POLLING):
                    future = executor.submit(self._sync_instrument_polling, inst.symbol)
                    futures.append((future, inst.symbol))
            
            # Wait for completion
            for future, symbol in futures:
                try:
                    future.result()
                    logger.info(f"Completed polling sync for {symbol}")
                except Exception as e:
                    logger.error(f"Failed to sync {symbol}: {e}")
    
    def sync_instrument(self, symbol: str) -> None:
        """Sync all timeframes for a specific instrument."""
        state = self._instrument_states.get(symbol)
        if not state:
            logger.warning(f"Instrument {symbol} not found in sync state")
            return
        
        # For WebSocket mode, data is already syncing
        if state.websocket_active:
            logger.info(f"WebSocket sync active for {symbol}")
            return
        
        # For polling mode, trigger sync
        if state.polling_active or state.current_mode == SyncMode.POLLING:
            self._sync_instrument_polling(symbol)
    
    def sync_timeframe(self, symbol: str, timeframe: str) -> None:
        """Sync a specific symbol and timeframe."""
        state = self._instrument_states.get(symbol)
        if not state:
            logger.warning(f"Instrument {symbol} not found")
            return
        
        if timeframe not in state.timeframes:
            logger.warning(f"Timeframe {timeframe} not configured for {symbol}")
            return
        
        # Use polling for direct sync requests
        self._sync_timeframe_polling(symbol, timeframe)
    
    def backfill_historical_data(
        self, 
        symbol: str, 
        timeframe: str, 
        start_date: datetime, 
        end_date: Optional[datetime] = None
    ) -> None:
        """Backfill historical data using REST API."""
        logger.info(f"Backfilling {symbol} {timeframe} from {start_date}")
        
        # Always use REST client for historical backfill
        try:
            candles = self.rest_client.fetch_historical_range(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_date,
                end_time=end_date or datetime.now(timezone.utc)
            )
            
            if candles:
                stored_count = self.storage.store_ohlcv_data(symbol, timeframe, candles)
                logger.info(f"Backfilled {stored_count} candles for {symbol} {timeframe}")
                
        except Exception as e:
            logger.error(f"Error backfilling {symbol} {timeframe}: {e}")
            raise
    
    def detect_and_fill_gaps(self, symbol: str, timeframe: str, max_gap_days: int = 7) -> None:
        """Detect gaps in local data and fill them using REST API."""
        logger.info(f"Detecting gaps for {symbol} {timeframe}")
        
        try:
            tf_ms = self._get_timeframe_duration_ms(timeframe)
            gaps = self.storage.find_gaps(symbol, timeframe, tf_ms)
            
            if not gaps:
                logger.debug(f"No gaps found for {symbol} {timeframe}")
                return
            
            logger.info(f"Found {len(gaps)} gaps for {symbol} {timeframe}")
            
            for gap_start, gap_end in gaps:
                gap_duration = (gap_end - gap_start).total_seconds() / 86400  # Days
                
                if gap_duration > max_gap_days:
                    logger.warning(f"Skipping large gap ({gap_duration:.1f} days) for {symbol} {timeframe}")
                    continue
                
                # Fill gap using REST API
                candles = self.rest_client.fetch_historical_range(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=gap_start,
                    end_time=gap_end
                )
                
                if candles:
                    stored_count = self.storage.store_ohlcv_data(symbol, timeframe, candles)
                    logger.info(f"Filled gap with {stored_count} candles")
                
                time.sleep(1)  # Rate limiting
                
        except Exception as e:
            logger.error(f"Error detecting/filling gaps for {symbol} {timeframe}: {e}")
    
    def force_sync_now(self, symbol: Optional[str] = None) -> None:
        """Force immediate sync for a symbol or all symbols."""
        if symbol:
            self.sync_instrument(symbol)
        else:
            self.sync_all_instruments()
    
    def add_instrument_sync(self, symbol: str, timeframes: List[str], sync_interval: int = 60) -> None:
        """Add a new instrument to sync schedule."""
        # Add to config
        instrument = self.config.add_instrument(
            symbol=symbol,
            timeframes=timeframes,
            sync_interval_seconds=sync_interval
        )
        
        # Initialize sync state
        state = InstrumentSyncState(
            symbol=symbol,
            timeframes=set(timeframes),
            current_mode=self._get_instrument_mode(instrument)
        )
        self._instrument_states[symbol] = state
        
        # If running, add to appropriate sync method
        if self._is_running:
            if state.current_mode in [SyncMode.WEBSOCKET, SyncMode.HYBRID]:
                # Schedule WebSocket subscription
                if self._loop and self.websocket_client:
                    asyncio.run_coroutine_threadsafe(
                        self.websocket_client.subscribe_symbol(symbol, timeframes),
                        self._loop
                    )
            
            if state.current_mode in [SyncMode.POLLING, SyncMode.HYBRID]:
                # Add polling schedule
                import schedule
                schedule.every(sync_interval).seconds.do(
                    self._sync_instrument_polling, symbol
                )
        
        logger.info(f"Added {symbol} to hybrid sync with mode: {state.current_mode.value}")
    
    def remove_instrument_sync(self, symbol: str) -> None:
        """Remove an instrument from sync schedule."""
        # Remove from WebSocket subscriptions
        if self._loop and self.websocket_client:
            asyncio.run_coroutine_threadsafe(
                self.websocket_client.unsubscribe_symbol(symbol),
                self._loop
            )
        
        # Remove from state tracking
        if symbol in self._instrument_states:
            del self._instrument_states[symbol]
        
        # Remove from config
        self.config.instruments = [
            inst for inst in self.config.instruments 
            if inst.symbol != symbol
        ]
        
        logger.info(f"Removed {symbol} from hybrid sync")
    
    def get_sync_status(self) -> Dict[str, any]:
        """Get current sync status."""
        websocket_status = {}
        if self.websocket_client:
            websocket_status = self.websocket_client.get_websocket_status()
        
        # Count active modes
        websocket_count = sum(1 for s in self._instrument_states.values() if s.websocket_active)
        polling_count = sum(1 for s in self._instrument_states.values() if s.polling_active)
        fallback_count = sum(1 for s in self._instrument_states.values() if s.fallback_active)
        
        return {
            'is_running': self._is_running,
            'effective_mode': self._effective_mode.value,
            'websocket_status': websocket_status,
            'instrument_states': {
                symbol: {
                    'current_mode': state.current_mode.value,
                    'websocket_active': state.websocket_active,
                    'polling_active': state.polling_active,
                    'fallback_active': state.fallback_active,
                    'websocket_failures': state.websocket_failures,
                    'polling_failures': state.polling_failures,
                    'last_websocket_data': state.last_websocket_data,
                    'last_polling_data': state.last_polling_data
                }
                for symbol, state in self._instrument_states.items()
            },
            'active_counts': {
                'websocket_instruments': websocket_count,
                'polling_instruments': polling_count,
                'fallback_instruments': fallback_count,
                'total_instruments': len(self._instrument_states)
            },
            'scheduled_jobs': len([s for s in self._instrument_states.values() if s.polling_active]),
            'last_sync_times': self._sync_status.copy(),
            'recent_errors': self._sync_errors.copy()
        }
    
    @property
    def is_running(self) -> bool:
        """Check if sync engine is running."""
        return self._is_running