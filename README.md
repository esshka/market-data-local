# OKX Local Store

A Python application for local storage of OHLCV candlestick data from OKX exchange that stays in sync with remote data, enabling fast local queries instead of repeated API calls.

## Features

- **Multi-instrument support**: Track multiple trading pairs simultaneously
- **Multiple timeframes**: Support for all OKX timeframes (1m, 5m, 1h, 1d, etc.)
- **Automatic synchronization**: Keep data fresh with configurable sync intervals
- **SQLite storage**: Efficient local storage with proper indexing
- **Gap detection**: Automatically detect and fill missing data
- **Fast queries**: Query local data instead of hitting OKX API repeatedly
- **Rate limit compliance**: Respects OKX API rate limits
- **Flexible configuration**: JSON-based configuration with environment variable support
- **CLI interface**: Command-line tools for management and monitoring
- **Export functionality**: Export data to CSV for analysis

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd okx-local-store

# Install dependencies
pip install -e .
```

## Quick Start

### Python API

```python
from okx_local_store import create_default_store

# Create store with popular trading pairs
store = create_default_store(['BTC-USDT', 'ETH-USDT', 'SOL-USDT'])

# Use as context manager for automatic cleanup
with store:
    # Get latest candle
    latest = store.query.get_latest_candle('BTC-USDT', '1h')
    print(f"Latest BTC price: ${latest['close']}")
    
    # Get recent candles
    recent = store.query.get_recent_candles('BTC-USDT', '1d', 30)
    print(f"Retrieved {len(recent)} daily candles")
    
    # Force sync
    store.sync_now('BTC-USDT')
```

### Command Line Interface

```bash
# Show status
okx-store status

# Sync all symbols
okx-store sync --all

# Sync specific symbol
okx-store sync BTC-USDT

# Query recent data
okx-store query BTC-USDT 1h --count 24

# Add new symbol
okx-store add-symbol ETH-USDT --timeframes 1m 1h 1d

# Export data to CSV
okx-store export BTC-USDT 1d output.csv --days 30

# Start daemon mode
okx-store daemon
```

## Configuration

### Environment Variables

Set your OKX API credentials (optional for public endpoints):

```bash
export OKX_API_KEY="your-api-key"
export OKX_API_SECRET="your-api-secret" 
export OKX_PASSPHRASE="your-passphrase"
```

### Configuration File

The app uses a JSON configuration file (default: `~/.okx_local_store/config.json`):

```json
{
  "data_dir": "data",
  "sandbox": false,
  "rate_limit_per_minute": 240,
  "enable_auto_sync": true,
  "sync_on_startup": true,
  "max_concurrent_syncs": 3,
  "log_level": "INFO",
  "instruments": [
    {
      "symbol": "BTC-USDT",
      "timeframes": ["1m", "5m", "1h", "1d"],
      "sync_interval_seconds": 60,
      "max_history_days": 365,
      "enabled": true
    }
  ]
}
```

## Architecture

The application consists of several key components:

- **OKXAPIClient**: CCXT-based client for OKX API integration
- **OHLCVStorage**: SQLite-based storage with optimized indexing
- **SyncEngine**: Manages data synchronization and scheduling
- **OHLCVQueryInterface**: Provides fast query methods
- **OKXConfig**: Configuration management system

### Data Storage

- One SQLite database per trading pair for scalability
- Separate tables for each timeframe
- Proper indexing on timestamps for fast queries
- Automatic gap detection and backfill capabilities

### Synchronization Strategy

- Incremental updates (only fetch new/missing data)
- Configurable sync intervals per instrument/timeframe
- Background scheduler with thread pool for concurrent syncing
- Rate limit compliance with OKX API restrictions
- Error recovery and retry logic

## API Reference

### OKXLocalStore

Main interface class:

```python
# Create instance
store = OKXLocalStore(config_path="config.json")

# Lifecycle management
store.start()  # Start sync engine
store.stop()   # Stop and cleanup

# Symbol management
store.add_symbol("ETH-USDT", timeframes=["1h", "1d"])
store.remove_symbol("ETH-USDT")

# Data operations
store.sync_now("BTC-USDT")  # Force sync
store.backfill("BTC-USDT", "1h", start_date)  # Backfill historical
store.detect_gaps("BTC-USDT", "1h")  # Find and fill gaps

# Status and monitoring
status = store.get_status()
overview = store.get_market_overview()
```

### Query Interface

Fast data access methods:

```python
# Recent data
latest = store.query.get_latest_candle("BTC-USDT", "1h")
recent = store.query.get_recent_candles("BTC-USDT", "1d", 30)

# Date range queries
data = store.query.get_candles_by_date_range(
    "BTC-USDT", "1h", start_date, end_date
)

# Analysis methods
returns = store.query.calculate_returns("BTC-USDT", "1h")
volatility = store.query.calculate_volatility("BTC-USDT", "1h", window=24)

# Data coverage
coverage = store.query.get_data_coverage("BTC-USDT", "1h")

# Export
store.query.export_to_csv("BTC-USDT", "1d", "output.csv")
```

## Examples

See `example_usage.py` for comprehensive usage examples including:

- Basic setup and querying
- Advanced configuration and backfilling  
- Monitoring and status checking

## Supported Timeframes

All OKX timeframes are supported:

- Minutes: `1m`, `3m`, `5m`, `15m`, `30m`
- Hours: `1H`, `2H`, `4H`, `6H`, `12H`  
- Days/Weeks: `1D`, `1W`, `1M`, `3M`

## Rate Limits

The application respects OKX API rate limits:

- Conservative default: 240 requests per minute
- Automatic rate limiting with request queuing
- Configurable limits per use case

## Data Integrity

- Automatic gap detection and backfill
- Duplicate prevention with upsert operations
- Data validation and error handling
- Comprehensive logging for debugging

## Monitoring

Built-in monitoring capabilities:

- Sync status tracking per symbol/timeframe
- Error logging and reporting
- Storage statistics and coverage metrics
- Health checks for API connectivity

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

[Add your license information here]

## Support

For issues and questions:
- Check the examples in `example_usage.py`
- Review configuration options
- Check logs for error details
- Open an issue on GitHub