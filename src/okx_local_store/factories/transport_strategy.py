"""Transport strategy factory for clean client creation without coupling."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from loguru import logger
from enum import Enum

from ..interfaces.api_client import RequestResponseClientInterface, RealtimeClientInterface
from ..interfaces.storage import StorageInterface
from ..config import OKXConfig
from ..api_client import OKXAPIClient
from ..websocket_api_client import WebSocketAPIClient
from ..storage import OHLCVStorage
from ..realtime_storage import RealtimeOHLCVStorage
from ..services.realtime_coordinator import RealtimeDataCoordinator
from ..events.realtime_events import RealtimeEventBus
from ..hybrid_sync_engine import HybridSyncEngine
from ..exceptions import ConfigurationError


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
        
        # Create sync engine (no real-time components)
        sync_engine = HybridSyncEngine(
            config=config,
            rest_client=rest_client,
            storage=storage
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
        websocket_client = WebSocketAPIClient(
            api_key=credentials['api_key'],
            api_secret=credentials['api_secret'],
            passphrase=credentials['passphrase'],
            sandbox=config.sandbox,
            websocket_config=config.websocket_config
        )
        
        # Create real-time optimized storage
        storage = RealtimeOHLCVStorage(config.data_dir)
        
        # Create event bus and coordinator
        event_bus = RealtimeEventBus()
        realtime_coordinator = RealtimeDataCoordinator(
            config=config,
            storage=storage,
            event_bus=event_bus
        )
        
        # Create minimal sync engine (polling disabled)
        sync_engine = HybridSyncEngine(
            config=config,
            rest_client=None,  # No REST client needed
            storage=storage,
            event_bus=event_bus,
            realtime_coordinator=realtime_coordinator
        )
        
        return {
            'api_client': websocket_client,
            'websocket_client': websocket_client, 
            'storage': storage,
            'sync_engine': sync_engine,
            'event_bus': event_bus,
            'realtime_coordinator': realtime_coordinator,
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
        
        # Create real-time optimized storage
        storage = RealtimeOHLCVStorage(config.data_dir)
        
        # Create event bus and coordinator
        event_bus = RealtimeEventBus()
        realtime_coordinator = RealtimeDataCoordinator(
            config=config,
            storage=storage,
            event_bus=event_bus
        )
        
        # Create hybrid sync engine with both REST and real-time support
        sync_engine = HybridSyncEngine(
            config=config,
            rest_client=rest_client,
            storage=storage,
            event_bus=event_bus,
            realtime_coordinator=realtime_coordinator
        )
        
        return {
            'api_client': rest_client,  # Primary interface is REST for historical data
            'rest_client': rest_client,
            'storage': storage,
            'sync_engine': sync_engine,
            'event_bus': event_bus,
            'realtime_coordinator': realtime_coordinator,
            'mode': TransportMode.HYBRID
        }
    
    def get_description(self) -> str:
        return "Hybrid mode - WebSocket real-time with REST polling fallback"


class TransportStrategyFactory:
    """Factory for creating transport strategies based on configuration."""
    
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
        """
        Create transport components based on configuration.
        
        Args:
            config: OKX configuration
            credentials: API credentials dictionary
            
        Returns:
            Dictionary containing all created components
            
        Raises:
            ConfigurationError: If strategy creation fails
        """
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
        """Determine transport mode from configuration using new transport strategy format."""
        # Use new configuration methods that abstract WebSocket internals
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
            # Default to hybrid if configuration is unclear
            logger.warning(f"Unknown transport_mode '{transport_mode}', defaulting to hybrid")
            return TransportMode.HYBRID
    
    def get_available_strategies(self) -> Dict[str, str]:
        """Get available transport strategies and their descriptions."""
        return {
            mode.value: strategy.get_description()
            for mode, strategy in self._strategies.items()
        }
    
    def validate_configuration(self, config: OKXConfig) -> Tuple[bool, Optional[str]]:
        """
        Validate configuration for transport strategy creation.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            transport_mode = self._determine_transport_mode(config)
            
            # Check real-time transport requirements using abstracted methods
            if transport_mode in [TransportMode.REALTIME_ONLY, TransportMode.HYBRID]:
                if not hasattr(config, 'websocket_config') or not config.websocket_config:
                    return False, "Real-time configuration required for real-time/hybrid modes"
                
                # Use new configuration methods that don't expose WebSocket internals
                realtime_instruments = config.get_realtime_instruments()
                
                if not realtime_instruments:
                    return False, "No instruments configured for real-time data in real-time/hybrid modes"
            
            return True, None
            
        except Exception as e:
            return False, f"Configuration validation error: {e}"


# Convenience function for easy usage
def create_transport_components(config: OKXConfig, credentials: Dict[str, str]) -> Dict[str, Any]:
    """
    Convenience function to create transport components.
    
    Args:
        config: OKX configuration
        credentials: API credentials
        
    Returns:
        Dictionary containing all transport components
    """
    factory = TransportStrategyFactory()
    return factory.create_transport_components(config, credentials)