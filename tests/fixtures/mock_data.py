"""Mock data generators for testing."""

import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class MockAPIResponse:
    """Mock API response structure."""
    status_code: int = 200
    data: Dict[str, Any] = None
    error: str = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class MockOHLCVData:
    """Generator for mock OHLCV data."""
    
    @staticmethod
    def generate_candles(
        symbol: str = "BTC-USDT",
        timeframe: str = "1h",
        count: int = 100,
        start_price: float = 50000.0,
        start_time: datetime = None
    ) -> List[Dict[str, Any]]:
        """Generate mock OHLCV candle data."""
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(hours=count)
        
        # Calculate time interval based on timeframe
        interval_map = {
            '1m': timedelta(minutes=1),
            '5m': timedelta(minutes=5),
            '15m': timedelta(minutes=15), 
            '30m': timedelta(minutes=30),
            '1h': timedelta(hours=1),
            '4h': timedelta(hours=4),
            '1d': timedelta(days=1),
        }
        
        interval = interval_map.get(timeframe, timedelta(hours=1))
        
        candles = []
        current_time = start_time
        current_price = start_price
        
        for i in range(count):
            # Generate realistic price movement
            price_change = random.uniform(-0.05, 0.05)  # ±5% max change
            new_price = current_price * (1 + price_change)
            
            # Generate OHLC values
            high = max(current_price, new_price) * random.uniform(1.0, 1.02)
            low = min(current_price, new_price) * random.uniform(0.98, 1.0)
            open_price = current_price
            close_price = new_price
            
            # Generate volume
            volume = random.uniform(10, 1000)
            vol_currency = volume * close_price
            
            candle = {
                'timestamp': int(current_time.timestamp() * 1000),
                'open': round(open_price, 2),
                'high': round(high, 2), 
                'low': round(low, 2),
                'close': round(close_price, 2),
                'volume': round(volume, 4),
                'vol_currency': round(vol_currency, 2)
            }
            
            candles.append(candle)
            current_time += interval
            current_price = new_price
        
        return candles
    
    @staticmethod
    def generate_ccxt_ohlcv(
        symbol: str = "BTC/USDT",
        timeframe: str = "1h", 
        count: int = 100,
        start_price: float = 50000.0,
        start_time: datetime = None
    ) -> List[List[float]]:
        """Generate OHLCV data in CCXT format [timestamp, open, high, low, close, volume]."""
        candles = MockOHLCVData.generate_candles(
            symbol.replace('/', '-'), timeframe, count, start_price, start_time
        )
        
        # Convert to CCXT format
        ccxt_candles = []
        for candle in candles:
            ccxt_candles.append([
                candle['timestamp'],
                candle['open'],
                candle['high'],
                candle['low'],
                candle['close'],
                candle['volume']
            ])
        
        return ccxt_candles
    
    @staticmethod
    def generate_market_data() -> Dict[str, Any]:
        """Generate mock market data."""
        symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT']
        markets = {}
        
        for symbol in symbols:
            markets[symbol.replace('-', '/')] = {
                'id': symbol.lower().replace('-', '_'),
                'symbol': symbol.replace('-', '/'),
                'base': symbol.split('-')[0],
                'quote': symbol.split('-')[1],
                'active': True,
                'type': 'spot',
                'precision': {
                    'amount': 8,
                    'price': 2
                },
                'limits': {
                    'amount': {'min': 0.001, 'max': 10000},
                    'price': {'min': 0.01, 'max': 1000000}
                }
            }
        
        return markets
    
    @staticmethod
    def generate_exchange_status() -> Dict[str, Any]:
        """Generate mock exchange status."""
        return {
            'status': 'ok',
            'updated': datetime.now(timezone.utc).isoformat()
        }
    
    @staticmethod
    def generate_candles_with_gaps(
        symbol: str = "BTC-USDT",
        timeframe: str = "1h",
        total_hours: int = 100,
        gap_hours: int = 5,
        gap_start: int = 50
    ) -> List[Dict[str, Any]]:
        """Generate candles with intentional gaps for testing gap detection."""
        # Generate first part
        part1_count = gap_start
        part1 = MockOHLCVData.generate_candles(
            symbol, timeframe, part1_count, 50000.0
        )
        
        # Generate second part after gap
        start_time_part2 = datetime.fromtimestamp(
            part1[-1]['timestamp'] / 1000, tz=timezone.utc
        ) + timedelta(hours=gap_hours + 1)  # Create gap
        
        part2_count = total_hours - gap_start
        part2 = MockOHLCVData.generate_candles(
            symbol, timeframe, part2_count, 51000.0, start_time_part2
        )
        
        return part1 + part2