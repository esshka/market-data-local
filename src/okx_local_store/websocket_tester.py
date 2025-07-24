"""Dedicated WebSocket testing infrastructure independent of store lifecycle."""

import asyncio
import json
import time
import websockets
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
from loguru import logger

from .config import OKXConfig, WebSocketConfig
from .exceptions import (
    WebSocketError, WebSocketConnectionError, WebSocketAuthenticationError,
    WebSocketTimeoutError
)


class TestStatus(Enum):
    """Test result status."""
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class TestResult:
    """Individual test result."""
    name: str
    status: TestStatus
    duration: float
    message: str
    error: Optional[Exception] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class TestReport:
    """Complete test report."""
    timestamp: datetime
    config_mode: str
    total_duration: float
    results: List[TestResult]
    
    @property
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return all(r.status == TestStatus.PASSED for r in self.results)
    
    @property
    def passed_count(self) -> int:
        """Count of passed tests."""
        return sum(1 for r in self.results if r.status == TestStatus.PASSED)
    
    @property
    def failed_count(self) -> int:
        """Count of failed tests."""
        return sum(1 for r in self.results if r.status == TestStatus.FAILED)


class WebSocketTester:
    """
    Dedicated WebSocket testing infrastructure that operates independently
    of the full store lifecycle to avoid timing and coupling issues.
    """
    
    def __init__(self, config: OKXConfig):
        """
        Initialize WebSocket tester.
        
        Args:
            config: OKX configuration with WebSocket settings
        """
        self.config = config
        self.websocket_config = getattr(config, 'websocket_config', WebSocketConfig())
        
        # Determine WebSocket URLs
        sandbox = getattr(config, 'sandbox', True)
        if sandbox:
            self.ws_url = "wss://wspap.okx.com:8443/ws/v5/public"
            self.ws_private_url = "wss://wspap.okx.com:8443/ws/v5/private"
        else:
            self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
            self.ws_private_url = "wss://ws.okx.com:8443/ws/v5/private"
        
        # Get credentials
        creds = config.get_env_credentials()
        self.api_key = creds.get('api_key')
        self.api_secret = creds.get('api_secret')
        self.passphrase = creds.get('passphrase')
    
    async def test_basic_connectivity(self, timeout: int = 10) -> TestResult:
        """
        Test basic WebSocket connectivity to OKX endpoint.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            TestResult with connectivity test outcome
        """
        start_time = time.time()
        
        try:
            logger.info(f"Testing connectivity to {self.ws_url}")
            
            # Attempt connection with timeout
            websocket = await asyncio.wait_for(
                websockets.connect(
                    self.ws_url,
                    compression="deflate" if self.websocket_config.enable_compression else None,
                    ping_interval=self.websocket_config.ping_interval,
                    ping_timeout=self.websocket_config.connection_timeout,
                    close_timeout=5.0,
                    max_size=2**20,
                    max_queue=32
                ),
                timeout=timeout
            )
            
            # Connection successful - close cleanly
            await websocket.close()
            
            duration = time.time() - start_time
            
            return TestResult(
                name="Basic Connectivity",
                status=TestStatus.PASSED,
                duration=duration,
                message=f"Successfully connected to {self.ws_url}",
                details={
                    "endpoint": self.ws_url,
                    "connection_time": f"{duration:.2f}s",
                    "compression": self.websocket_config.enable_compression
                }
            )
            
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            return TestResult(
                name="Basic Connectivity",
                status=TestStatus.TIMEOUT,
                duration=duration,
                message=f"Connection timeout after {timeout}s",
                details={
                    "endpoint": self.ws_url,
                    "timeout": timeout,
                    "suggestion": "Check network connectivity and firewall settings"
                }
            )
            
        except (ConnectionRefusedError, OSError) as e:
            duration = time.time() - start_time
            return TestResult(
                name="Basic Connectivity",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Connection failed: {e}",
                error=e,
                details={
                    "endpoint": self.ws_url,
                    "error_type": type(e).__name__,
                    "suggestion": "Check network connectivity, DNS resolution, and firewall settings"
                }
            )
            
        except asyncio.CancelledError:
            duration = time.time() - start_time
            return TestResult(
                name="Basic Connectivity",
                status=TestStatus.CANCELLED,
                duration=duration,
                message="Test was cancelled",
                details={"endpoint": self.ws_url}
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                name="Basic Connectivity",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Unexpected error: {e}",
                error=e,
                details={
                    "endpoint": self.ws_url,
                    "error_type": type(e).__name__
                }
            )
    
    async def test_ping_pong(self, timeout: int = 15) -> TestResult:
        """
        Test WebSocket ping/pong functionality.
        
        Args:
            timeout: Test timeout in seconds
            
        Returns:
            TestResult with ping/pong test outcome
        """
        start_time = time.time()
        
        try:
            logger.info("Testing WebSocket ping/pong functionality")
            
            # Connect to WebSocket
            websocket = await asyncio.wait_for(
                websockets.connect(self.ws_url),
                timeout=timeout // 2
            )
            
            try:
                # Send ping and wait for pong
                ping_start = time.time()
                await websocket.ping()
                ping_duration = time.time() - ping_start
                
                duration = time.time() - start_time
                
                return TestResult(
                    name="Ping/Pong Test",
                    status=TestStatus.PASSED,
                    duration=duration,
                    message=f"Ping successful ({ping_duration*1000:.0f}ms)",
                    details={
                        "ping_time_ms": f"{ping_duration*1000:.0f}",
                        "connection_healthy": True
                    }
                )
                
            finally:
                await websocket.close()
                
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            return TestResult(
                name="Ping/Pong Test",
                status=TestStatus.TIMEOUT,
                duration=duration,
                message=f"Ping/pong timeout after {timeout}s",
                details={"suggestion": "Connection may be unstable or server unresponsive"}
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                name="Ping/Pong Test",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Ping/pong failed: {e}",
                error=e,
                details={"error_type": type(e).__name__}
            )
    
    async def test_subscription(self, symbol: str = "BTC-USDT", timeout: int = 20) -> TestResult:
        """
        Test WebSocket subscription to market data.
        
        Args:
            symbol: Trading symbol to subscribe to
            timeout: Test timeout in seconds
            
        Returns:
            TestResult with subscription test outcome
        """
        start_time = time.time()
        
        try:
            logger.info(f"Testing subscription to {symbol} market data")
            
            # Connect to WebSocket
            websocket = await asyncio.wait_for(
                websockets.connect(self.ws_url),
                timeout=timeout // 3
            )
            
            try:
                # Subscribe to candle data
                subscribe_msg = {
                    "op": "subscribe",
                    "args": [{
                        "channel": "candle1m",
                        "instId": symbol
                    }]
                }
                
                await websocket.send(json.dumps(subscribe_msg))
                
                # Wait for subscription confirmation
                response = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=timeout // 2
                )
                
                response_data = json.loads(response)
                
                # Check if subscription was successful
                if response_data.get("event") == "subscribe" and response_data.get("code") == "0":
                    duration = time.time() - start_time
                    
                    return TestResult(
                        name="Market Data Subscription",
                        status=TestStatus.PASSED,
                        duration=duration,
                        message=f"Successfully subscribed to {symbol} market data",
                        details={
                            "symbol": symbol,
                            "channel": "candle1m",
                            "response": response_data
                        }
                    )
                else:
                    duration = time.time() - start_time
                    return TestResult(
                        name="Market Data Subscription",
                        status=TestStatus.FAILED,
                        duration=duration,
                        message=f"Subscription failed: {response_data}",
                        details={
                            "symbol": symbol,
                            "response": response_data,
                            "suggestion": "Check if symbol is valid and market is active"
                        }
                    )
                    
            finally:
                await websocket.close()
                
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            return TestResult(
                name="Market Data Subscription",
                status=TestStatus.TIMEOUT,
                duration=duration,
                message=f"Subscription timeout after {timeout}s",
                details={
                    "symbol": symbol,
                    "suggestion": "Server may be overloaded or symbol invalid"
                }
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                name="Market Data Subscription",
                status=TestStatus.FAILED,
                duration=duration,
                message=f"Subscription failed: {e}",
                error=e,
                details={
                    "symbol": symbol,
                    "error_type": type(e).__name__
                }
            )
    
    async def run_progressive_tests(self, timeout: int = 30) -> TestReport:
        """
        Run all WebSocket tests in progressive order.
        
        Args:
            timeout: Total timeout for all tests
            
        Returns:
            TestReport with complete test results
        """
        start_time = time.time()
        results = []
        
        # Test 1: Basic connectivity
        logger.info("🔌 Starting WebSocket connectivity test...")
        connectivity_result = await self.test_basic_connectivity(timeout=timeout//3)
        results.append(connectivity_result)
        
        # Only continue if connectivity passed
        if connectivity_result.status == TestStatus.PASSED:
            # Test 2: Ping/Pong
            logger.info("🏓 Starting ping/pong test...")
            ping_result = await self.test_ping_pong(timeout=timeout//3)
            results.append(ping_result)
            
            # Only continue if ping/pong passed
            if ping_result.status == TestStatus.PASSED:
                # Test 3: Market data subscription
                logger.info("📊 Starting market data subscription test...")
                subscription_result = await self.test_subscription(timeout=timeout//3)
                results.append(subscription_result)
        
        total_duration = time.time() - start_time
        
        return TestReport(
            timestamp=datetime.now(),
            config_mode=getattr(self.config, 'realtime_mode', 'unknown'),
            total_duration=total_duration,
            results=results
        )


def display_test_report(report: TestReport) -> None:
    """
    Display test report in user-friendly format.
    
    Args:
        report: TestReport to display
    """
    print(f"\n🧪 WebSocket Test Report ({report.timestamp.strftime('%H:%M:%S')})")
    print("=" * 50)
    print(f"Configuration: {report.config_mode} mode")
    print(f"Total Duration: {report.total_duration:.2f}s")
    print(f"Tests: {report.passed_count} passed, {report.failed_count} failed")
    print()
    
    for result in report.results:
        # Status emoji
        if result.status == TestStatus.PASSED:
            emoji = "✅"
        elif result.status == TestStatus.FAILED:
            emoji = "❌"
        elif result.status == TestStatus.TIMEOUT:
            emoji = "⏰"
        else:
            emoji = "🔄"
        
        print(f"{emoji} {result.name}")
        print(f"   Status: {result.status.value.upper()}")
        print(f"   Duration: {result.duration:.2f}s")
        print(f"   Message: {result.message}")
        
        if result.details:
            for key, value in result.details.items():
                if key != "suggestion":
                    print(f"   {key.replace('_', ' ').title()}: {value}")
        
        if result.details and "suggestion" in result.details:
            print(f"   💡 Suggestion: {result.details['suggestion']}")
        
        print()
    
    # Overall result
    if report.all_passed:
        print("🎉 All WebSocket tests passed! Your WebSocket configuration is working correctly.")
    else:
        print("⚠️  Some WebSocket tests failed. Check the suggestions above for troubleshooting.")
        
        # Provide general troubleshooting guidance
        print("\n🔧 General Troubleshooting:")
        print("   • Check your network connection and firewall settings")
        print("   • Verify OKX API credentials are correct")
        print("   • Ensure the trading symbol exists and is active")
        print("   • Try again later if OKX servers are experiencing issues")