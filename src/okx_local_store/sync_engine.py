"""Data synchronization engine for keeping local OHLCV data fresh."""

import schedule
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

from .config import OKXConfig, InstrumentConfig
from .api_client import OKXAPIClient
from .storage import OHLCVStorage


class SyncEngine:
    """Manages synchronization of OHLCV data from OKX to local storage."""
    
    def __init__(self, config: OKXConfig, api_client: OKXAPIClient, storage: OHLCVStorage):
        self.config = config
        self.api_client = api_client
        self.storage = storage
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        
        # Track sync status
        self._sync_status: Dict[str, Dict[str, datetime]] = {}
        self._sync_errors: Dict[str, List[str]] = {}

    def start(self):
        """Start the sync engine with scheduled jobs."""
        if self._is_running:
            logger.warning("Sync engine is already running")
            return
        
        self._is_running = True
        self._stop_event.clear()
        
        # Set up scheduled jobs
        self._setup_schedules()
        
        # Run initial sync if configured
        if self.config.sync_on_startup:
            logger.info("Running initial sync on startup")
            self.sync_all_instruments()
        
        # Start scheduler thread
        self._sync_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._sync_thread.start()
        
        logger.info("Sync engine started")

    def stop(self):
        """Stop the sync engine."""
        if not self._is_running:
            return
        
        logger.info("Stopping sync engine...")
        self._stop_event.set()
        self._is_running = False
        
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5)
        
        # Clear scheduled jobs
        schedule.clear()
        
        logger.info("Sync engine stopped")

    def _setup_schedules(self):
        """Set up scheduled sync jobs for each instrument."""
        schedule.clear()
        
        for instrument in self.config.instruments:
            if not instrument.enabled:
                continue
            
            # Schedule sync for this instrument
            schedule.every(instrument.sync_interval_seconds).seconds.do(
                self._sync_instrument_job, instrument
            )
            
            logger.info(f"Scheduled sync for {instrument.symbol} every {instrument.sync_interval_seconds} seconds")

    def _run_scheduler(self):
        """Run the scheduler in a separate thread."""
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    def _sync_instrument_job(self, instrument: InstrumentConfig):
        """Job wrapper for syncing a single instrument."""
        try:
            self.sync_instrument(instrument.symbol)
        except Exception as e:
            logger.error(f"Error in scheduled sync for {instrument.symbol}: {e}")

    def sync_all_instruments(self):
        """Sync all enabled instruments."""
        enabled_instruments = [inst for inst in self.config.instruments if inst.enabled]
        
        if not enabled_instruments:
            logger.warning("No enabled instruments to sync")
            return
        
        logger.info(f"Starting sync for {len(enabled_instruments)} instruments")
        
        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_syncs) as executor:
            futures = {
                executor.submit(self.sync_instrument, inst.symbol): inst.symbol 
                for inst in enabled_instruments
            }
            
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    future.result()
                    logger.info(f"Completed sync for {symbol}")
                except Exception as e:
                    logger.error(f"Failed to sync {symbol}: {e}")

    def sync_instrument(self, symbol: str):
        """Sync all timeframes for a specific instrument."""
        instrument = self.config.get_instrument(symbol)
        if not instrument or not instrument.enabled:
            logger.warning(f"Instrument {symbol} not found or disabled")
            return
        
        logger.info(f"Syncing instrument {symbol}")
        
        for timeframe in instrument.timeframes:
            try:
                self.sync_timeframe(symbol, timeframe)
                self._update_sync_status(symbol, timeframe, success=True)
            except Exception as e:
                error_msg = f"Failed to sync {symbol} {timeframe}: {e}"
                logger.error(error_msg)
                self._update_sync_status(symbol, timeframe, success=False, error=error_msg)

    def sync_timeframe(self, symbol: str, timeframe: str):
        """Sync a specific symbol and timeframe."""
        logger.debug(f"Syncing {symbol} {timeframe}")
        
        # Get the latest timestamp we have locally
        latest_local = self.storage.get_latest_timestamp(symbol, timeframe)
        
        if latest_local:
            # Incremental sync - fetch data since last update
            since = latest_local + timedelta(milliseconds=self.api_client.get_timeframe_duration_ms(timeframe))
            logger.debug(f"Incremental sync from {since} for {symbol} {timeframe}")
        else:
            # Initial sync - fetch recent historical data
            instrument = self.config.get_instrument(symbol)
            days_back = instrument.max_history_days if instrument else 30
            since = datetime.now(timezone.utc) - timedelta(days=days_back)
            logger.debug(f"Initial sync from {since} for {symbol} {timeframe}")
        
        # Fetch data from API
        candles = self.api_client.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            limit=1000
        )
        
        if candles:
            # Store the fetched data
            stored_count = self.storage.store_ohlcv_data(symbol, timeframe, candles)
            logger.info(f"Synced {stored_count} candles for {symbol} {timeframe}")
        else:
            logger.debug(f"No new data for {symbol} {timeframe}")

    def backfill_historical_data(
        self, 
        symbol: str, 
        timeframe: str, 
        start_date: datetime, 
        end_date: Optional[datetime] = None
    ):
        """
        Backfill historical data for a specific time range.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            start_date: Start date for backfill
            end_date: End date for backfill (defaults to now)
        """
        if not end_date:
            end_date = datetime.now(timezone.utc)
        
        logger.info(f"Backfilling {symbol} {timeframe} from {start_date} to {end_date}")
        
        try:
            # Fetch historical data in chunks
            candles = self.api_client.fetch_historical_range(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_date,
                end_time=end_date
            )
            
            if candles:
                stored_count = self.storage.store_ohlcv_data(symbol, timeframe, candles)
                logger.info(f"Backfilled {stored_count} candles for {symbol} {timeframe}")
            else:
                logger.warning(f"No historical data retrieved for {symbol} {timeframe}")
                
        except Exception as e:
            logger.error(f"Error backfilling {symbol} {timeframe}: {e}")
            raise

    def detect_and_fill_gaps(self, symbol: str, timeframe: str, max_gap_days: int = 7):
        """
        Detect gaps in local data and fill them.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candlestick timeframe
            max_gap_days: Maximum gap size to fill (prevents huge backfills)
        """
        logger.info(f"Detecting gaps for {symbol} {timeframe}")
        
        try:
            tf_ms = self.api_client.get_timeframe_duration_ms(timeframe)
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
                
                logger.info(f"Filling gap from {gap_start} to {gap_end} for {symbol} {timeframe}")
                
                # Fetch data to fill the gap
                candles = self.api_client.fetch_historical_range(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=gap_start,
                    end_time=gap_end
                )
                
                if candles:
                    stored_count = self.storage.store_ohlcv_data(symbol, timeframe, candles)
                    logger.info(f"Filled gap with {stored_count} candles")
                
                # Add delay between gap fills to respect rate limits
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error detecting/filling gaps for {symbol} {timeframe}: {e}")

    def _update_sync_status(self, symbol: str, timeframe: str, success: bool, error: str = None):
        """Update sync status tracking."""
        if symbol not in self._sync_status:
            self._sync_status[symbol] = {}
        
        if symbol not in self._sync_errors:
            self._sync_errors[symbol] = []
        
        self._sync_status[symbol][timeframe] = datetime.now(timezone.utc)
        
        if not success and error:
            self._sync_errors[symbol].append(f"{timeframe}: {error}")
            # Keep only last 10 errors per symbol
            if len(self._sync_errors[symbol]) > 10:
                self._sync_errors[symbol] = self._sync_errors[symbol][-10:]

    def get_sync_status(self) -> Dict[str, any]:
        """Get current sync status."""
        return {
            'is_running': self._is_running,
            'last_sync_times': self._sync_status.copy(),
            'recent_errors': self._sync_errors.copy(),
            'scheduled_jobs': len(schedule.jobs)
        }

    def force_sync_now(self, symbol: Optional[str] = None):
        """Force immediate sync for a symbol or all symbols."""
        if symbol:
            instrument = self.config.get_instrument(symbol)
            if instrument:
                logger.info(f"Force syncing {symbol}")
                self.sync_instrument(symbol)
            else:
                logger.error(f"Instrument {symbol} not found")
        else:
            logger.info("Force syncing all instruments")
            self.sync_all_instruments()

    def add_instrument_sync(self, symbol: str, timeframes: List[str], sync_interval: int = 60):
        """Add a new instrument to sync schedule."""
        # Add to config
        instrument = self.config.add_instrument(
            symbol=symbol,
            timeframes=timeframes,
            sync_interval_seconds=sync_interval
        )
        
        # Add to schedule if engine is running
        if self._is_running:
            schedule.every(sync_interval).seconds.do(
                self._sync_instrument_job, instrument
            )
            
            logger.info(f"Added {symbol} to sync schedule with {sync_interval}s interval")

    def remove_instrument_sync(self, symbol: str):
        """Remove an instrument from sync schedule."""
        # Remove from config
        self.config.instruments = [
            inst for inst in self.config.instruments 
            if inst.symbol != symbol
        ]
        
        # Remove from schedule (requires restart of scheduler)
        if self._is_running:
            self._setup_schedules()
            
        logger.info(f"Removed {symbol} from sync schedule")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()