"""Configuration provider interface for dependency inversion."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from pathlib import Path


class InstrumentConfigInterface(ABC):
    """Interface for instrument configuration."""
    
    # For dataclass compatibility, we define these as attributes that should exist
    # rather than abstract properties
    symbol: str
    timeframes: List[str]
    sync_interval_seconds: int
    max_history_days: int
    enabled: bool


class ConfigurationProviderInterface(ABC):
    """Abstract interface for configuration providers."""
    
    # For dataclass compatibility, we define these as attributes that should exist
    # rather than abstract properties
    data_dir: Path
    sandbox: bool
    rate_limit_per_minute: int
    instruments: List[InstrumentConfigInterface]
    enable_auto_sync: bool
    sync_on_startup: bool
    max_concurrent_syncs: int
    log_level: str
    log_file: Optional[Path]
    
    @abstractmethod
    def get_instrument(self, symbol: str) -> Optional[InstrumentConfigInterface]:
        """Get configuration for a specific instrument."""
        pass
    
    @abstractmethod
    def add_instrument(self, symbol: str, timeframes: List[str] = None, **kwargs) -> InstrumentConfigInterface:
        """Add or update instrument configuration."""
        pass
    
    
    @abstractmethod
    def save_to_file(self, config_path: Path) -> None:
        """Save configuration to file."""
        pass
    
    @classmethod
    @abstractmethod
    def load_from_file(cls, config_path: Path) -> 'ConfigurationProviderInterface':
        """Load configuration from file."""
        pass