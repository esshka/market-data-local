"""Abstract interfaces for OKX Local Store components."""

from .api_client import APIClientInterface
from .storage import StorageInterface
from .sync_engine import SyncEngineInterface
from .config import ConfigurationProviderInterface
from .query import QueryInterface

__all__ = [
    'APIClientInterface',
    'StorageInterface', 
    'SyncEngineInterface',
    'ConfigurationProviderInterface',
    'QueryInterface',
]