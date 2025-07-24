#!/usr/bin/env python3
"""
Command-line interface for OKX Local Store.

This CLI provides basic commands for managing the OKX Local Store,
including starting/stopping sync, querying data, and managing symbols.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
import json

from .okx_store import OKXLocalStore, create_default_store
from .config import OKXConfig


def create_parser():
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="OKX Local Store - Command Line Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                           # Show store status
  %(prog)s sync BTC-USDT                    # Sync specific symbol
  %(prog)s sync --all                       # Sync all symbols
  %(prog)s query BTC-USDT 1h --count 24     # Get 24 recent hourly candles
  %(prog)s add-symbol ETH-USDT              # Add new symbol to track
  %(prog)s export BTC-USDT 1d output.csv    # Export daily data to CSV
  %(prog)s backfill BTC-USDT 1h --days 7    # Backfill 7 days of hourly data
  %(prog)s daemon                           # Start daemon mode
  %(prog)s websocket status                 # Show detailed WebSocket status
  %(prog)s websocket test                   # Test WebSocket connection
  %(prog)s websocket config                 # Show WebSocket configuration
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        type=Path,
        help='Configuration file path'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show store status')
    status_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Sync command
    sync_parser = subparsers.add_parser('sync', help='Sync data from OKX')
    sync_parser.add_argument('symbol', nargs='?', help='Symbol to sync (e.g., BTC-USDT)')
    sync_parser.add_argument('--all', action='store_true', help='Sync all symbols')
    
    # Query command
    query_parser = subparsers.add_parser('query', help='Query local data')
    query_parser.add_argument('symbol', help='Symbol to query (e.g., BTC-USDT)')
    query_parser.add_argument('timeframe', help='Timeframe (e.g., 1m, 1h, 1d)')
    query_parser.add_argument('--count', type=int, default=10, help='Number of recent candles')
    query_parser.add_argument('--days', type=int, help='Number of days back to query')
    query_parser.add_argument('--format', choices=['table', 'json', 'csv'], default='table', help='Output format')
    
    # Add symbol command
    add_parser = subparsers.add_parser('add-symbol', help='Add symbol to track')
    add_parser.add_argument('symbol', help='Symbol to add (e.g., BTC-USDT)')
    add_parser.add_argument('--timeframes', nargs='+', default=['1m', '1h', '1d'], help='Timeframes to track')
    add_parser.add_argument('--interval', type=int, default=60, help='Sync interval in seconds')
    
    # Remove symbol command
    remove_parser = subparsers.add_parser('remove-symbol', help='Remove symbol from tracking')
    remove_parser.add_argument('symbol', help='Symbol to remove')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export data to CSV')
    export_parser.add_argument('symbol', help='Symbol to export')
    export_parser.add_argument('timeframe', help='Timeframe to export')
    export_parser.add_argument('output', help='Output CSV file path')
    export_parser.add_argument('--days', type=int, help='Number of days to export')
    
    # Backfill command
    backfill_parser = subparsers.add_parser('backfill', help='Backfill historical data')
    backfill_parser.add_argument('symbol', help='Symbol to backfill')
    backfill_parser.add_argument('timeframe', help='Timeframe to backfill')
    backfill_parser.add_argument('--days', type=int, default=7, help='Number of days to backfill')
    
    # List symbols command
    list_parser = subparsers.add_parser('list', help='List tracked symbols')
    list_parser.add_argument('--available', action='store_true', help='List available symbols from OKX')
    
    # Start daemon command
    daemon_parser = subparsers.add_parser('daemon', help='Start sync daemon')
    daemon_parser.add_argument('--no-sync-on-start', action='store_true', help='Skip initial sync')
    
    # WebSocket commands
    ws_parser = subparsers.add_parser('websocket', help='WebSocket management')
    ws_subparsers = ws_parser.add_subparsers(dest='ws_command', help='WebSocket commands')
    
    # WebSocket status
    ws_status_parser = ws_subparsers.add_parser('status', help='Show detailed WebSocket status')
    ws_status_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # WebSocket test
    ws_test_parser = ws_subparsers.add_parser('test', help='Test WebSocket connection')
    ws_test_parser.add_argument('--timeout', type=int, default=30, help='Total test timeout in seconds')
    
    # WebSocket config
    ws_config_parser = ws_subparsers.add_parser('config', help='Show WebSocket configuration')
    ws_config_parser.add_argument('--set-mode', choices=['websocket', 'polling', 'hybrid'], 
                                  help='Set realtime mode')
    ws_config_parser.add_argument('--enable', action='store_true', help='Enable WebSocket')
    ws_config_parser.add_argument('--disable', action='store_true', help='Disable WebSocket')
    
    return parser


def format_output(data, format_type='table'):
    """Format data for output."""
    if format_type == 'json':
        return json.dumps(data, indent=2, default=str)
    elif format_type == 'csv':
        if hasattr(data, 'to_csv'):
            return data.to_csv(index=False)
        else:
            return str(data)
    else:  # table
        if hasattr(data, 'to_string'):
            return data.to_string()
        else:
            return str(data)


def cmd_status(args, store):
    """Handle status command."""
    status = store.get_status()
    
    if args.json:
        print(format_output(status, 'json'))
    else:
        print("OKX Local Store Status")
        print("=" * 25)
        
        # Configuration
        config = status['config']
        print(f"Tracked instruments: {config['instruments_count']}")
        print(f"Enabled instruments: {config['enabled_instruments']}")
        print(f"Auto-sync: {config['auto_sync_enabled']}")
        print(f"Data directory: {config['data_directory']}")
        
        # Sync engine with enhanced WebSocket info
        sync = status['sync_engine']
        print(f"\nSync engine running: {sync['is_running']}")
        print(f"Scheduled jobs: {sync['scheduled_jobs']}")
        
        # WebSocket status (if available)
        if 'effective_mode' in sync:
            print(f"Sync mode: {sync['effective_mode']}")
            
        if 'websocket_status' in sync and sync['websocket_status']:
            ws_status = sync['websocket_status']
            print(f"\nWebSocket Status:")
            print(f"  Connected: {'✓' if ws_status.get('connected') else '✗'}")
            print(f"  Authenticated: {'✓' if ws_status.get('authenticated') else '✗'}")
            
            if ws_status.get('connection_age_seconds'):
                age_minutes = ws_status['connection_age_seconds'] / 60
                print(f"  Connection age: {age_minutes:.1f} minutes")
            
            print(f"  Active subscriptions: {ws_status.get('active_subscriptions', 0)}")
            print(f"  Reconnect attempts: {ws_status.get('reconnect_attempts', 0)}")
            
            if ws_status.get('last_pong_seconds_ago') is not None:
                print(f"  Last pong: {ws_status['last_pong_seconds_ago']:.1f}s ago")
        
        # Enhanced instrument status with WebSocket info
        if 'instrument_states' in sync:
            instrument_states = sync['instrument_states']
            print(f"\nInstruments ({len(instrument_states)}):")
            
            for symbol, state in instrument_states.items():
                mode = state.get('current_mode', 'unknown')
                ws_active = '🟢' if state.get('websocket_active') else '⚫'
                polling_active = '🔵' if state.get('polling_active') else '⚫'
                fallback = ' (fallback)' if state.get('fallback_active') else ''
                
                print(f"  {symbol}: {mode}{fallback}")
                print(f"    WebSocket: {ws_active}  Polling: {polling_active}")
                
                # Show failure counts if any
                ws_failures = state.get('websocket_failures', 0)
                polling_failures = state.get('polling_failures', 0)
                if ws_failures > 0 or polling_failures > 0:
                    print(f"    Failures - WS: {ws_failures}, Polling: {polling_failures}")
        
        # Active counts summary
        if 'active_counts' in sync:
            counts = sync['active_counts']
            print(f"\nSync Summary:")
            print(f"  WebSocket instruments: {counts.get('websocket_instruments', 0)}")
            print(f"  Polling instruments: {counts.get('polling_instruments', 0)}")
            print(f"  Fallback instruments: {counts.get('fallback_instruments', 0)}")
        
        # Storage with real-time stats
        storage = status['storage']
        print(f"\nStorage:")
        print(f"  Total records: {storage['total_records']}")
        print(f"  Symbols in storage: {storage['total_symbols']}")
        
        # Real-time storage statistics (if available)
        if 'realtime_stats' in storage:
            rt_stats = storage['realtime_stats']
            print(f"  Real-time stats:")
            print(f"    Total writes: {rt_stats.get('total_writes', 0)}")
            print(f"    WebSocket writes: {rt_stats.get('websocket_writes', 0)}")
            print(f"    Polling writes: {rt_stats.get('polling_writes', 0)}")
            print(f"    Batched writes: {rt_stats.get('batched_writes', 0)}")
            print(f"    Buffer size: {rt_stats.get('current_buffer_size', 0)}")
            
            if rt_stats.get('last_write_time'):
                import time
                last_write = rt_stats['last_write_time']
                if hasattr(last_write, 'timestamp'):
                    seconds_ago = time.time() - last_write.timestamp()
                    print(f"    Last write: {seconds_ago:.1f}s ago")
        
        # API
        api = status['api_client']
        print(f"\nAPI:")
        print(f"  Connection: {'OK' if api['connection_ok'] else 'Failed'}")
        print(f"  Sandbox mode: {api['sandbox_mode']}")
        
        # Recent errors (if any)
        if 'recent_errors' in sync and sync['recent_errors']:
            print(f"\nRecent Errors:")
            for symbol, errors in sync['recent_errors'].items():
                if errors:
                    print(f"  {symbol}:")
                    for error in errors[-3:]:  # Show last 3 errors
                        print(f"    • {error}")


def cmd_sync(args, store):
    """Handle sync command."""
    if args.all:
        print("Syncing all symbols...")
        store.sync_now()
        print("Sync initiated for all symbols")
    elif args.symbol:
        print(f"Syncing {args.symbol}...")
        store.sync_now(args.symbol)
        print(f"Sync initiated for {args.symbol}")
    else:
        print("Error: Must specify --all or a symbol")
        return 1


def cmd_query(args, store):
    """Handle query command."""
    try:
        if args.days:
            # Query by days back
            start_date = datetime.now() - timedelta(days=args.days)
            data = store.query.get_candles_since(args.symbol, args.timeframe, start_date)
        else:
            # Query recent candles
            data = store.query.get_recent_candles(args.symbol, args.timeframe, args.count)
        
        if data.empty:
            print(f"No data found for {args.symbol} {args.timeframe}")
            return 1
        
        print(format_output(data, args.format))
        
    except Exception as e:
        print(f"Error querying data: {e}")
        return 1


def cmd_add_symbol(args, store):
    """Handle add-symbol command."""
    try:
        store.add_symbol(args.symbol, args.timeframes, args.interval)
        store.save_config()
        print(f"Added {args.symbol} with timeframes {args.timeframes}")
        print(f"Sync interval: {args.interval} seconds")
    except Exception as e:
        print(f"Error adding symbol: {e}")
        return 1


def cmd_remove_symbol(args, store):
    """Handle remove-symbol command."""
    try:
        store.remove_symbol(args.symbol)
        store.save_config()
        print(f"Removed {args.symbol} from tracking")
    except Exception as e:
        print(f"Error removing symbol: {e}")
        return 1


def cmd_export(args, store):
    """Handle export command."""
    try:
        start_date = None
        end_date = None
        
        if args.days:
            start_date = datetime.now() - timedelta(days=args.days)
            end_date = datetime.now()
        
        success = store.export_data(args.symbol, args.timeframe, args.output, start_date, end_date)
        
        if success:
            print(f"Data exported to {args.output}")
        else:
            print("Export failed")
            return 1
            
    except Exception as e:
        print(f"Error exporting data: {e}")
        return 1


def cmd_backfill(args, store):
    """Handle backfill command."""
    try:
        start_date = datetime.now() - timedelta(days=args.days)
        print(f"Backfilling {args.symbol} {args.timeframe} for {args.days} days...")
        
        store.backfill(args.symbol, args.timeframe, start_date)
        print("Backfill completed")
        
    except Exception as e:
        print(f"Error during backfill: {e}")
        return 1


def cmd_list(args, store):
    """Handle list command."""
    try:
        if args.available:
            print("Fetching available symbols from OKX...")
            symbols = store.api_client.get_available_symbols()
            
            if symbols:
                print(f"\nFound {len(symbols)} available symbols:")
                for i, symbol in enumerate(sorted(symbols), 1):
                    print(f"{i:4}. {symbol}")
            else:
                print("No symbols retrieved")
        else:
            # List tracked symbols
            print("Tracked symbols:")
            for instrument in store.config.instruments:
                status = "enabled" if instrument.enabled else "disabled"
                print(f"  {instrument.symbol} ({status})")
                print(f"    Timeframes: {', '.join(instrument.timeframes)}")
                print(f"    Sync interval: {instrument.sync_interval_seconds}s")
                print()
                
    except Exception as e:
        print(f"Error listing symbols: {e}")
        return 1


def cmd_daemon(args, store):
    """Handle daemon command."""
    print("Starting OKX Local Store daemon...")
    print("Press Ctrl+C to stop")
    
    try:
        # Override sync_on_startup if requested
        if args.no_sync_on_start:
            store.config.sync_on_startup = False
        
        store.start()
        
        # Keep running until interrupted
        while True:
            import time
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping daemon...")
    except Exception as e:
        print(f"Daemon error: {e}")
        return 1
    finally:
        store.stop()
    
    print("Daemon stopped")


def cmd_websocket(args, store):
    """Handle websocket command and subcommands."""
    if not args.ws_command:
        print("Error: WebSocket subcommand required")
        return 1
    
    if args.ws_command == 'status':
        return cmd_websocket_status(args, store)
    elif args.ws_command == 'test':
        return cmd_websocket_test(args, store)
    elif args.ws_command == 'config':
        return cmd_websocket_config(args, store)
    else:
        print(f"Unknown WebSocket command: {args.ws_command}")
        return 1


def cmd_websocket_status(args, store):
    """Handle websocket status command."""
    try:
        status = store.get_status()
        sync_status = status.get('sync_engine', {})
        
        if args.json:
            ws_data = {
                'websocket_status': sync_status.get('websocket_status'),
                'instrument_states': sync_status.get('instrument_states'),
                'active_counts': sync_status.get('active_counts'),
                'effective_mode': sync_status.get('effective_mode'),
                'realtime_stats': status.get('storage', {}).get('realtime_stats')
            }
            print(format_output(ws_data, 'json'))
        else:
            print("WebSocket Detailed Status")
            print("=" * 30)
            
            # Overall mode and status
            effective_mode = sync_status.get('effective_mode', 'unknown')
            print(f"Effective sync mode: {effective_mode}")
            
            # WebSocket connection details
            ws_status = sync_status.get('websocket_status')
            if ws_status:
                print(f"\nConnection Details:")
                print(f"  Status: {'🟢 Connected' if ws_status.get('connected') else '🔴 Disconnected'}")
                print(f"  Authenticated: {'✓' if ws_status.get('authenticated') else '✗'}")
                print(f"  WebSocket URL: {ws_status.get('websocket_url', 'N/A')}")
                
                if ws_status.get('connection_age_seconds'):
                    age = ws_status['connection_age_seconds']
                    age_str = f"{age//3600:.0f}h {(age%3600)//60:.0f}m {age%60:.0f}s" if age >= 3600 else f"{age//60:.0f}m {age%60:.0f}s"
                    print(f"  Connection age: {age_str}")
                
                print(f"  Reconnection attempts: {ws_status.get('reconnect_attempts', 0)}/{ws_status.get('max_reconnect_attempts', 0)}")
                print(f"  Buffer size: {ws_status.get('buffer_size', 0)} messages")
                
                last_pong = ws_status.get('last_pong_seconds_ago')
                if last_pong is not None:
                    pong_status = '🟢 Healthy' if last_pong < 30 else '🟡 Slow' if last_pong < 60 else '🔴 Stale'
                    print(f"  Last pong: {last_pong:.1f}s ago ({pong_status})")
            else:
                print(f"\nWebSocket: Not available or not enabled")
            
            # Per-instrument status
            instrument_states = sync_status.get('instrument_states', {})
            if instrument_states:
                print(f"\nInstrument Status ({len(instrument_states)} instruments):")
                for symbol, state in instrument_states.items():
                    mode = state.get('current_mode', 'unknown')
                    ws_active = state.get('websocket_active', False)
                    polling_active = state.get('polling_active', False)
                    fallback_active = state.get('fallback_active', False)
                    
                    # Status indicators
                    ws_indicator = '🟢' if ws_active else '⚫'
                    polling_indicator = '🔵' if polling_active else '⚫'
                    fallback_indicator = ' ⚠️ FALLBACK' if fallback_active else ''
                    
                    print(f"  {symbol} ({mode}){fallback_indicator}")
                    print(f"    WebSocket: {ws_indicator}  REST Polling: {polling_indicator}")
                    
                    # Data freshness
                    last_ws_data = state.get('last_websocket_data')
                    last_polling_data = state.get('last_polling_data')
                    
                    if last_ws_data:
                        import time
                        from datetime import datetime, timezone
                        if hasattr(last_ws_data, 'timestamp'):
                            ws_age = time.time() - last_ws_data.timestamp()
                            print(f"    Last WebSocket data: {ws_age:.1f}s ago")
                    
                    if last_polling_data:
                        if hasattr(last_polling_data, 'timestamp'):
                            polling_age = time.time() - last_polling_data.timestamp()
                            print(f"    Last polling data: {polling_age:.1f}s ago")
                    
                    # Failure counts
                    ws_failures = state.get('websocket_failures', 0)
                    polling_failures = state.get('polling_failures', 0)
                    if ws_failures > 0 or polling_failures > 0:
                        print(f"    Failures: WebSocket={ws_failures}, Polling={polling_failures}")
                    
                    print()  # Empty line between instruments
            
            # Summary statistics
            active_counts = sync_status.get('active_counts', {})
            if active_counts:
                print(f"Summary Statistics:")
                print(f"  Total instruments: {active_counts.get('total_instruments', 0)}")
                print(f"  WebSocket active: {active_counts.get('websocket_instruments', 0)}")
                print(f"  Polling active: {active_counts.get('polling_instruments', 0)}")
                print(f"  In fallback mode: {active_counts.get('fallback_instruments', 0)}")
            
            # Real-time performance stats
            rt_stats = status.get('storage', {}).get('realtime_stats')
            if rt_stats:
                print(f"\nPerformance Statistics:")
                print(f"  Total writes: {rt_stats.get('total_writes', 0)}")
                print(f"  WebSocket writes: {rt_stats.get('websocket_writes', 0)}")
                print(f"  Polling writes: {rt_stats.get('polling_writes', 0)}")
                print(f"  Batched operations: {rt_stats.get('batched_writes', 0)}")
                print(f"  Deduplicated records: {rt_stats.get('deduplicated_records', 0)}")
                print(f"  Failed writes: {rt_stats.get('failed_writes', 0)}")
                print(f"  Current buffer: {rt_stats.get('current_buffer_size', 0)} items")
                
        return 0
        
    except Exception as e:
        print(f"Error getting WebSocket status: {e}")
        return 1


def cmd_websocket_test(args, store):
    """Handle websocket test command using dedicated WebSocket tester."""
    import asyncio
    from .websocket_tester import WebSocketTester, display_test_report
    
    try:
        # Use timeout from args (already has default from parser)
        timeout = args.timeout
        
        print("🔌 Starting WebSocket Tests...")
        print(f"Timeout: {timeout}s")
        print("=" * 50)
        
        # Create dedicated tester (independent of store lifecycle)
        config = store.config
        tester = WebSocketTester(config)
        
        # Run async tests in sync CLI context
        try:
            report = asyncio.run(tester.run_progressive_tests(timeout=timeout))
            display_test_report(report)
            return 0 if report.all_passed else 1
            
        except KeyboardInterrupt:
            print("\n🛑 Test cancelled by user")
            return 1
            
        except Exception as e:
            print(f"\n❌ Test execution failed: {e}")
            print("This might indicate a configuration or network issue.")
            return 1
            
    except Exception as e:
        print(f"❌ Failed to initialize WebSocket test: {e}")
        print("Check your configuration and try again.")
        return 1


def cmd_websocket_status_standalone(args, store):
    """Handle websocket status command without starting the full store."""
    try:
        print("WebSocket Configuration Status")
        print("=" * 35)
        
        config = store.config
        
        print(f"Realtime mode: {config.realtime_mode}")
        print(f"WebSocket enabled: {config.enable_websocket}")
        print(f"Fallback enabled: {config.websocket_fallback_enabled}")
        
        # WebSocket connection settings
        ws_config = config.websocket_config
        print(f"\nConnection Settings:")
        print(f"  Max reconnect attempts: {ws_config.max_reconnect_attempts}")
        print(f"  Connection timeout: {ws_config.connection_timeout}s")
        print(f"  Heartbeat interval: {ws_config.heartbeat_interval}s")
        print(f"  Ping interval: {ws_config.ping_interval}s")
        print(f"  Max connection age: {ws_config.max_connection_age}s")
        print(f"  Reconnect delay: {ws_config.reconnect_delay_base}s - {ws_config.reconnect_delay_max}s")
        print(f"  Compression enabled: {ws_config.enable_compression}")
        print(f"  Buffer size: {ws_config.buffer_size}")
        
        # Configured instruments
        print(f"\nConfigured Instruments ({len(config.instruments)}):")
        for instrument in config.instruments:
            if instrument.enabled:
                realtime_source = getattr(instrument, 'realtime_source', 'auto')
                fallback_enabled = getattr(instrument, 'fallback_to_polling', True)
                ws_priority = getattr(instrument, 'websocket_priority', True)
                
                print(f"  {instrument.symbol}:")
                print(f"    Timeframes: {', '.join(instrument.timeframes)}")  
                print(f"    Realtime source: {realtime_source}")
                print(f"    Fallback to polling: {fallback_enabled}")
                print(f"    WebSocket priority: {ws_priority}")
        
        print(f"\n💡 Note: To see live connection status, use daemon mode:")
        print(f"   okx-store --config {args.config or 'default'} daemon")
        
        return 0
        
    except Exception as e:
        print(f"Error showing WebSocket config: {e}")
        return 1


def cmd_websocket_config(args, store):
    """Handle websocket config command."""
    try:
        if args.set_mode or args.enable or args.disable:
            print("Configuration modification not yet implemented")
            print("Please modify the configuration file directly")
            return 1
        
        # Show current WebSocket configuration
        print("WebSocket Configuration")
        print("=" * 25)
        
        config = store.config
        
        print(f"Realtime mode: {config.realtime_mode}")
        print(f"WebSocket enabled: {config.enable_websocket}")
        print(f"Fallback enabled: {config.websocket_fallback_enabled}")
        
        # WebSocket connection settings
        ws_config = config.websocket_config
        print(f"\nConnection Settings:")
        print(f"  Max reconnect attempts: {ws_config.max_reconnect_attempts}")
        print(f"  Connection timeout: {ws_config.connection_timeout}s")
        print(f"  Heartbeat interval: {ws_config.heartbeat_interval}s")
        print(f"  Ping interval: {ws_config.ping_interval}s")
        print(f"  Max connection age: {ws_config.max_connection_age}s")
        print(f"  Reconnect delay: {ws_config.reconnect_delay_base}s - {ws_config.reconnect_delay_max}s")
        print(f"  Compression enabled: {ws_config.enable_compression}")
        print(f"  Buffer size: {ws_config.buffer_size}")
        
        # Per-instrument settings
        print(f"\nPer-Instrument Settings:")
        for instrument in config.instruments:
            if instrument.enabled:
                realtime_source = getattr(instrument, 'realtime_source', 'auto')
                fallback_enabled = getattr(instrument, 'fallback_to_polling', True)
                ws_priority = getattr(instrument, 'websocket_priority', True)
                
                print(f"  {instrument.symbol}:")
                print(f"    Realtime source: {realtime_source}")
                print(f"    Fallback to polling: {fallback_enabled}")
                print(f"    WebSocket priority: {ws_priority}")
        
        return 0
        
    except Exception as e:
        print(f"Error showing WebSocket config: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Set up logging level
    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    try:
        # Create store
        if args.config:
            config = OKXConfig.load_from_file(args.config)
            store = OKXLocalStore(config=config)
        else:
            store = create_default_store()
        
        # Commands that don't need the store to be started
        if args.command in ['add-symbol', 'remove-symbol', 'list']:
            if args.command == 'add-symbol':
                return cmd_add_symbol(args, store) or 0
            elif args.command == 'remove-symbol':
                return cmd_remove_symbol(args, store) or 0
            elif args.command == 'list':
                return cmd_list(args, store) or 0
        
        # Handle websocket commands independently (don't need store started)
        if args.command == 'websocket' and args.ws_command in ['test', 'status']:
            if args.ws_command == 'test':
                return cmd_websocket_test(args, store) or 0
            elif args.ws_command == 'status':
                return cmd_websocket_status_standalone(args, store) or 0
        
        # Commands that need the store started
        if args.command == 'daemon':
            return cmd_daemon(args, store) or 0
        else:
            # Start store for other commands
            store.start()
            
            try:
                if args.command == 'status':
                    return cmd_status(args, store) or 0
                elif args.command == 'sync':
                    return cmd_sync(args, store) or 0
                elif args.command == 'query':
                    return cmd_query(args, store) or 0
                elif args.command == 'export':
                    return cmd_export(args, store) or 0
                elif args.command == 'backfill':
                    return cmd_backfill(args, store) or 0
                elif args.command == 'websocket':
                    return cmd_websocket(args, store) or 0
                else:
                    print(f"Unknown command: {args.command}")
                    return 1
                    
            finally:
                store.stop()
        
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())