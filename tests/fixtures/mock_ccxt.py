"""Mock CCXT exchange for testing."""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from unittest.mock import Mock

from .mock_data import MockOHLCVData


class MockCCXTExchange:
    """Mock CCXT exchange that simulates OKX API responses."""
    
    def __init__(self, fail_requests: bool = False, rate_limit_error: bool = False):
        """
        Initialize mock exchange.
        
        Args:
            fail_requests: If True, simulate API failures
            rate_limit_error: If True, simulate rate limit errors
        """
        self.fail_requests = fail_requests
        self.rate_limit_error = rate_limit_error
        self.request_count = 0
        self.markets_data = MockOHLCVData.generate_market_data()
        
        # Mock properties
        self.id = 'okx'
        self.name = 'OKX'
        self.countries = ['CN']
        
    def load_markets(self) -> Dict[str, Any]:
        """Mock load_markets method."""
        self._check_failures()
        return self.markets_data
    
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1h',
        since: Optional[int] = None,
        limit: int = 100,
        params: Dict = None
    ) -> List[List[float]]:
        """Mock fetch_ohlcv method."""
        self._check_failures()
        
        start_time = None
        if since:
            start_time = datetime.fromtimestamp(since / 1000, tz=timezone.utc)
        
        return MockOHLCVData.generate_ccxt_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            count=min(limit, 1000),
            start_time=start_time
        )
    
    def fetch_status(self) -> Dict[str, Any]:
        """Mock fetch_status method."""
        self._check_failures()
        return MockOHLCVData.generate_exchange_status()
    
    def _check_failures(self):
        """Check if we should simulate failures."""
        self.request_count += 1
        
        if self.rate_limit_error and self.request_count > 5:
            import ccxt
            raise ccxt.RateLimitExceeded("Rate limit exceeded")
        
        if self.fail_requests:
            import ccxt
            # Always fail when fail_requests is True
            raise ccxt.NetworkError("Network error")


def create_mock_ccxt_exchange(**kwargs) -> Mock:
    """Create a mock CCXT exchange with configurable behavior."""
    mock_exchange = MockCCXTExchange(**kwargs)
    
    # Create mock object with the same interface as real CCXT exchange
    mock = Mock()
    mock.load_markets = Mock(side_effect=mock_exchange.load_markets)
    mock.fetch_ohlcv = Mock(side_effect=mock_exchange.fetch_ohlcv)
    mock.fetch_status = Mock(side_effect=mock_exchange.fetch_status)
    mock.id = mock_exchange.id
    mock.name = mock_exchange.name
    mock.countries = mock_exchange.countries
    
    return mock


def mock_ccxt_factory(exchange_name: str = 'okx', **exchange_config):
    """Factory function that creates mock exchanges."""
    def create_exchange(config):
        return create_mock_ccxt_exchange(**exchange_config)
    
    # Mock the ccxt module's exchange creation
    mock_ccxt = Mock()
    setattr(mock_ccxt, exchange_name, create_exchange)
    return mock_ccxt