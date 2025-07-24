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
                asyncio.create_task(self.websocket_client.unsubscribe(
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
        
        # Start sync thread
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
        
        logger.info("Simplified hybrid sync engine started")

    def stop(self):
        """Stop the sync engine."""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()
        
        # Stop WebSocket connections
        asyncio.create_task(self.websocket_client.disconnect())
        
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
            
        state = self._instrument_states[symbol]
        sync_timeframes = timeframes or list(state.timeframes)
        
        try:
            for timeframe in sync_timeframes:
                # Get latest data from storage
                latest_data = self.storage.get_latest_timestamp(symbol, timeframe)
                
                # Fetch new data from API
                data = self.rest_client.get_ohlcv_data(
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
                        asyncio.create_task(self._start_websocket_subscription(symbol, state))
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

    def get_sync_status(self) -> Dict[str, Dict[str, any]]:
        """Get current sync status for all symbols."""
        status = {}
        for symbol, state in self._instrument_states.items():
            status[symbol] = {
                'current_mode': state.current_mode.value,
                'polling_active': state.polling_active,
                'websocket_active': state.websocket_active,
                'last_polling_data': state.last_polling_data,
                'last_websocket_data': state.last_websocket_data,
                'polling_failures': state.polling_failures,
                'timeframes': list(state.timeframes)
            }
        return status

    def is_running(self) -> bool:
        """Check if sync engine is running."""
        return self._is_running