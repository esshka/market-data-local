"""Simplified transport strategy factory for clean client creation."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from loguru import logger
from enum import Enum

from .interfaces.api_client import RequestResponseClientInterface
from .interfaces.storage import StorageInterface
from .config import OKXConfig
from .api_client import OKXAPIClient
from .simple_websocket_client import SimpleWebSocketClient
from .storage import OHLCVStorage
# Removed complex RealtimeOHLCVStorage - using simple OHLCVStorage for all modes
from .simple_hybrid_sync_engine import SimplifiedHybridSyncEngine
from .exceptions import ConfigurationError


class TransportMode(Enum):
    """Transport modes for data access."""
    POLLING_ONLY = "polling"
    REALTIME_ONLY = "realtime" 
    HYBRID = "hybrid"
    AUTO = "auto"


class TransportStrategy(ABC):
    """Abstract base class for transport strategies."""
    
    @abstractmethod
    def create_components(self, config: OKXConfig, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Create all necessary components for this transport strategy."""
        pass
    
    @abstractmethod
    def get_description(self) -> str:
        """Get description of this transport strategy."""
        pass


class PollingTransportStrategy(TransportStrategy):
    """Strategy for REST API polling only."""
    
    def create_components(self, config: OKXConfig, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Create components for polling-only transport."""
        logger.info("Creating components for polling-only transport")
        
        # Create REST client
        rest_client = OKXAPIClient(
            api_key=credentials['api_key'],
            api_secret=credentials['api_secret'],
            passphrase=credentials['passphrase'],
            sandbox=config.sandbox,
            rate_limit_per_minute=config.rate_limit_per_minute
        )
        
        # Create standard storage
        storage = OHLCVStorage(config.data_dir)
        
        # Create sync engine (no WebSocket)
        sync_engine = SimplifiedHybridSyncEngine(
            config=config,
            rest_client=rest_client,
            storage=storage,
            websocket_client=None  # No WebSocket for polling-only
        )
        
        return {
            'api_client': rest_client,
            'storage': storage,
            'sync_engine': sync_engine,
            'mode': TransportMode.POLLING_ONLY
        }
    
    def get_description(self) -> str:
        return "REST API polling only - no real-time features"


class RealtimeTransportStrategy(TransportStrategy):
    """Strategy for WebSocket real-time only."""
    
    def create_components(self, config: OKXConfig, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Create components for real-time-only transport."""
        logger.info("Creating components for real-time-only transport")
        
        # Create WebSocket client
        websocket_client = SimpleWebSocketClient(
            sandbox=config.sandbox,
            websocket_config=config.websocket_config
        )
        
        # Create standard storage (simplified from complex real-time storage)
        storage = OHLCVStorage(config.data_dir)
        
        # Create sync engine with WebSocket only
        sync_engine = SimplifiedHybridSyncEngine(
            config=config,
            rest_client=None,  # No REST client for real-time only
            storage=storage,
            websocket_client=websocket_client
        )
        
        return {
            'api_client': websocket_client,
            'websocket_client': websocket_client, 
            'storage': storage,
            'sync_engine': sync_engine,
            'mode': TransportMode.REALTIME_ONLY
        }
    
    def get_description(self) -> str:
        return "WebSocket real-time streaming only - no polling fallback"


class HybridTransportStrategy(TransportStrategy):
    """Strategy for hybrid WebSocket + REST polling."""
    
    def create_components(self, config: OKXConfig, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Create components for hybrid transport."""
        logger.info("Creating components for hybrid transport (WebSocket + REST polling)")
        
        # Create REST client for polling and historical data
        rest_client = OKXAPIClient(
            api_key=credentials['api_key'],
            api_secret=credentials['api_secret'],
            passphrase=credentials['passphrase'],
            sandbox=config.sandbox,
            rate_limit_per_minute=config.rate_limit_per_minute
        )
        
        # Create WebSocket client for real-time data
        websocket_client = SimpleWebSocketClient(
            sandbox=config.sandbox,
            websocket_config=config.websocket_config
        )
        
        # Create standard storage (simplified from complex real-time storage)
        storage = OHLCVStorage(config.data_dir)
        
        # Create hybrid sync engine with both REST and WebSocket
        sync_engine = SimplifiedHybridSyncEngine(
            config=config,
            rest_client=rest_client,
            storage=storage,
            websocket_client=websocket_client
        )
        
        return {
            'api_client': rest_client,  # Primary interface is REST for historical data
            'rest_client': rest_client,
            'websocket_client': websocket_client,
            'storage': storage,
            'sync_engine': sync_engine,
            'mode': TransportMode.HYBRID
        }
    
    def get_description(self) -> str:
        return "Hybrid mode - WebSocket real-time with REST polling fallback"


class SimpleTransportStrategyFactory:
    """Simplified factory for creating transport strategies."""
    
    def __init__(self):
        """Initialize strategy factory."""
        self._strategies = {
            TransportMode.POLLING_ONLY: PollingTransportStrategy(),
            TransportMode.REALTIME_ONLY: RealtimeTransportStrategy(),
            TransportMode.HYBRID: HybridTransportStrategy(),
            TransportMode.AUTO: HybridTransportStrategy()  # Auto defaults to hybrid
        }
    
    def create_transport_components(
        self, 
        config: OKXConfig, 
        credentials: Dict[str, str]
    ) -> Dict[str, Any]:
        """Create transport components based on configuration."""
        try:
            # Determine transport mode from configuration
            transport_mode = self._determine_transport_mode(config)
            
            # Get appropriate strategy
            strategy = self._strategies[transport_mode]
            
            # Create components using strategy
            components = strategy.create_components(config, credentials)
            
            # Add metadata
            components['strategy_description'] = strategy.get_description()
            components['transport_mode'] = transport_mode
            
            logger.info(f"Transport strategy created: {strategy.get_description()}")
            return components
            
        except Exception as e:
            logger.error(f"Failed to create transport components: {e}")
            raise ConfigurationError(f"Transport strategy creation failed: {e}")
    
    def _determine_transport_mode(self, config: OKXConfig) -> TransportMode:
        """Determine transport mode from configuration."""
        transport_mode = getattr(config, 'transport_mode', 'hybrid')
        enable_realtime = getattr(config, 'enable_realtime', True)
        
        # Map configuration to transport mode
        if not enable_realtime:
            return TransportMode.POLLING_ONLY
        elif transport_mode == 'realtime':
            return TransportMode.REALTIME_ONLY
        elif transport_mode in ['hybrid', 'auto']:
            return TransportMode.HYBRID
        elif transport_mode == 'polling':
            return TransportMode.POLLING_ONLY
        else:
            logger.warning(f"Unknown transport mode '{transport_mode}', defaulting to hybrid")
            return TransportMode.HYBRID


def create_transport_components(config: OKXConfig, credentials: Dict[str, str]) -> Dict[str, Any]:
    """
    Create transport components using the factory.
    
    Args:
        config: OKX configuration
        credentials: API credentials
        
    Returns:
        Dictionary with transport components
    """
    factory = SimpleTransportStrategyFactory()
    return factory.create_transport_components(config, credentials)