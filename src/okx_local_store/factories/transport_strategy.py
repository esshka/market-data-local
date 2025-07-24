"""Transport strategy factory for clean client creation without coupling."""

# For backward compatibility, import the simplified version
from ..simple_transport_strategy import (
    SimpleTransportStrategyFactory, TransportMode, TransportStrategy,
    PollingTransportStrategy, RealtimeTransportStrategy, HybridTransportStrategy
)

# Alias for existing code compatibility
TransportStrategyFactory = SimpleTransportStrategyFactory

# Re-export for existing imports
__all__ = [
    'TransportStrategyFactory', 'SimpleTransportStrategyFactory', 'TransportMode', 
    'TransportStrategy', 'PollingTransportStrategy', 'RealtimeTransportStrategy', 
    'HybridTransportStrategy'
]