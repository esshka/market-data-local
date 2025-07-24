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
        
        # Sync engine
        sync = status['sync_engine']
        print(f"\nSync engine running: {sync['is_running']}")
        print(f"Scheduled jobs: {sync['scheduled_jobs']}")
        
        # Storage
        storage = status['storage']
        print(f"\nTotal records: {storage['total_records']}")
        print(f"Symbols in storage: {storage['total_symbols']}")
        
        # API
        api = status['api_client']
        print(f"\nAPI connection: {'OK' if api['connection_ok'] else 'Failed'}")
        print(f"Sandbox mode: {api['sandbox_mode']}")


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