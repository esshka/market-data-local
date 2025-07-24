#!/usr/bin/env python3
"""
Example usage of OKX Local Store.

This script demonstrates the basic functionality of the OKX Local Store
including setup, configuration, data syncing, and querying.
"""

from okx_local_store import OKXLocalStore, create_default_store
from datetime import datetime, timedelta
import time
import pandas as pd

def basic_example():
    """Basic example of using OKX Local Store."""
    print("=== OKX Local Store - Basic Example ===\n")
    
    # Create a store with some popular trading pairs
    symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT']
    store = create_default_store(symbols)
    
    try:
        # Start the store (this will begin syncing if auto-sync is enabled)
        store.start()
        
        # Get overall status
        print("Store Status:")
        status = store.get_status()
        print(f"  - Tracking {status['config']['instruments_count']} instruments")
        print(f"  - Auto-sync: {status['config']['auto_sync_enabled']}")
        print(f"  - Data directory: {status['config']['data_directory']}")
        print()
        
        # Force an immediate sync for BTC-USDT
        print("Syncing BTC-USDT data...")
        store.sync_now('BTC-USDT')
        
        # Wait a moment for sync to complete
        time.sleep(5)
        
        # Query some data
        print("Querying recent data:")
        
        # Get latest candle
        latest = store.query.get_latest_candle('BTC-USDT', '1h')
        if latest is not None:
            print(f"  - Latest BTC-USDT 1h candle: ${latest['close']:.2f} at {latest.name}")
        else:
            print("  - No data available yet")
        
        # Get recent daily candles
        recent_daily = store.query.get_recent_candles('BTC-USDT', '1d', 7)
        if not recent_daily.empty:
            print(f"  - Retrieved {len(recent_daily)} daily candles")
            print(f"  - Price range: ${recent_daily['low'].min():.2f} - ${recent_daily['high'].max():.2f}")
        
        # Get data coverage information
        coverage = store.query.get_data_coverage('BTC-USDT', '1h')
        if coverage:
            print(f"  - Data coverage: {coverage['record_count']} records")
            if coverage['data_span_days']:
                print(f"  - Span: {coverage['data_span_days']:.1f} days")
        
        print()
        
        # Market overview
        print("Market Overview:")
        overview = store.get_market_overview()
        for symbol, data in overview['symbols'].items():
            if data['latest_price']:
                print(f"  - {symbol}: ${data['latest_price']:.2f}")
        
        print(f"\nTotal symbols tracked: {overview['total_symbols']}")
        
    finally:
        # Always stop the store to cleanup resources
        store.stop()


def advanced_example():
    """Advanced example with custom configuration and backfilling."""
    print("\n=== OKX Local Store - Advanced Example ===\n")
    
    # Create store with custom symbols and configuration
    store = create_default_store(['BTC-USDT', 'ETH-USDT'])
    
    # Add additional symbols with custom settings
    store.add_symbol('DOGE-USDT', timeframes=['5m', '1h', '1d'], sync_interval=120)
    
    try:
        store.start()
        
        # Backfill some historical data
        print("Backfilling historical data...")
        start_date = datetime.now() - timedelta(days=7)
        store.backfill('BTC-USDT', '1h', start_date)
        
        # Wait for backfill to complete
        time.sleep(10)
        
        # Query historical data
        print("Querying historical data:")
        
        # Get data from specific date range
        end_date = datetime.now()
        historical = store.query.get_candles_by_date_range(
            'BTC-USDT', '1h', start_date, end_date
        )
        
        if not historical.empty:
            print(f"  - Retrieved {len(historical)} hourly candles from last 7 days")
            
            # Calculate some statistics
            price_change = historical['close'].iloc[-1] - historical['close'].iloc[0]
            price_change_pct = (price_change / historical['close'].iloc[0]) * 100
            
            print(f"  - 7-day price change: ${price_change:.2f} ({price_change_pct:+.1f}%)")
            print(f"  - Average volume: {historical['volume'].mean():.2f}")
        
        # Calculate volatility
        volatility = store.query.calculate_volatility('BTC-USDT', '1h', window=24)
        if volatility:
            print(f"  - 24h volatility: {volatility:.4f}")
        
        # Detect gaps in data
        print("\nDetecting data gaps...")
        store.detect_gaps('BTC-USDT', '1h')
        
        # Export data to CSV
        print("\nExporting data...")
        if store.export_data('BTC-USDT', '1h', 'btc_usdt_1h.csv', start_date, end_date):
            print("  - Data exported to btc_usdt_1h.csv")
        
    finally:
        store.stop()


def monitoring_example():
    """Example of monitoring and status checking."""
    print("\n=== OKX Local Store - Monitoring Example ===\n")
    
    store = create_default_store(['BTC-USDT'])
    
    try:
        store.start()
        
        # Monitor for a short time
        print("Monitoring store status for 30 seconds...")
        
        for i in range(6):  # 6 iterations, 5 seconds each
            status = store.get_status()
            sync_status = status['sync_engine']
            storage_stats = status['storage']
            
            print(f"\nCheck {i+1}/6:")
            print(f"  - Sync engine running: {sync_status['is_running']}")
            print(f"  - Scheduled jobs: {sync_status['scheduled_jobs']}")
            print(f"  - Total records: {storage_stats['total_records']}")
            print(f"  - Total symbols in storage: {storage_stats['total_symbols']}")
            
            # Check if we have recent errors
            if sync_status['recent_errors']:
                print("  - Recent sync errors detected!")
                for symbol, errors in sync_status['recent_errors'].items():
                    if errors:
                        print(f"    {symbol}: {errors[-1]}")  # Show last error
            else:
                print("  - No recent sync errors")
            
            if i < 5:  # Don't sleep on last iteration
                time.sleep(5)
        
        print("\nMonitoring complete!")
        
    finally:
        store.stop()


if __name__ == "__main__":
    print("OKX Local Store - Example Usage\n")
    
    try:
        # Run examples
        basic_example()
        advanced_example()
        monitoring_example()
        
        print("\n=== All examples completed successfully! ===")
        
    except KeyboardInterrupt:
        print("\nExamples interrupted by user")
    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()