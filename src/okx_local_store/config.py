"""Configuration management for OKX Local Store."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Any
from pathlib import Path
import json
import os

from .interfaces.config import ConfigurationProviderInterface, InstrumentConfigInterface
from .utils.validation import ConfigValidator
from .utils.timeframes import get_supported_timeframes
from .exceptions import ConfigurationError


@dataclass
class WebSocketConfig:
    """Configuration for WebSocket connections (isolated from core logic)."""
    max_reconnect_attempts: int = 5
    heartbeat_interval: int = 30  # seconds
    connection_timeout: int = 10  # seconds
    ping_interval: int = 20  # seconds
    ping_timeout: int = 60  # seconds
    max_connection_age: int = 3600  # seconds - reconnect after 1 hour
    reconnect_delay_base: float = 1.0  # base delay for exponential backoff
    reconnect_delay_max: float = 60.0  # max delay between reconnection attempts
    enable_compression: bool = True
    # Removed complex buffering and batching - simplified WebSocket client doesn't need these


@dataclass
class InstrumentConfig(InstrumentConfigInterface):
    """Configuration for a specific instrument."""
    symbol: str
    timeframes: List[str] = field(default_factory=lambda: ['1m', '5m', '1h', '1d'])
    sync_interval_seconds: int = 60
    max_history_days: int = 365
    enabled: bool = True
    
    # Transport settings (abstracted from WebSocket specifics)
    realtime_source: Literal["websocket", "polling", "auto"] = "auto"
    fallback_to_polling: bool = True
    prefer_realtime: bool = True  # prefer real-time over polling when both available
    realtime_timeout_seconds: int = 300  # timeout for real-time data before fallback


@dataclass
class OKXConfig(ConfigurationProviderInterface):
    """Main configuration for OKX Local Store."""
    
    # Data storage
    data_dir: Path = field(default_factory=lambda: Path("data"))
    
    # OKX API settings
    sandbox: bool = True
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None
    
    # Rate limiting
    rate_limit_per_minute: int = 240  # Conservative limit
    
    # Instruments to track
    instruments: List[InstrumentConfig] = field(default_factory=list)
    
    # Sync settings
    enable_auto_sync: bool = True
    sync_on_startup: bool = True
    max_concurrent_syncs: int = 3
    
    # Transport Strategy Configuration (abstracted from implementation details)
    transport_mode: Literal["polling", "realtime", "hybrid", "auto"] = "hybrid"
    enable_realtime: bool = True  # Enable real-time features (WebSocket)
    enable_polling_fallback: bool = True  # Enable polling fallback when real-time fails
    
    # Real-time transport settings (WebSocket configuration isolated)
    websocket_config: WebSocketConfig = field(default_factory=WebSocketConfig)
    
    # Backward compatibility (deprecated - use transport_mode instead)
    realtime_mode: Optional[Literal["websocket", "polling", "hybrid"]] = None
    enable_websocket: Optional[bool] = None
    websocket_fallback_enabled: Optional[bool] = None
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[Path] = None

    def __post_init__(self):
        # Path conversion
        if isinstance(self.data_dir, str):
            self.data_dir = Path(self.data_dir)
        if self.log_file and isinstance(self.log_file, str):
            self.log_file = Path(self.log_file)
        
        # Migrate deprecated configuration to new transport strategy format
        self._migrate_transport_config()
    
    def _migrate_transport_config(self):
        """Migrate deprecated configuration options to new transport strategy format."""
        # Handle realtime_mode -> transport_mode migration
        if self.realtime_mode is not None:
            mode_mapping = {
                "websocket": "realtime",
                "polling": "polling", 
                "hybrid": "hybrid"
            }
            self.transport_mode = mode_mapping.get(self.realtime_mode, "hybrid")
            self.realtime_mode = None  # Clear deprecated field
        
        # Handle enable_websocket -> enable_realtime migration
        if self.enable_websocket is not None:
            self.enable_realtime = self.enable_websocket
            self.enable_websocket = None  # Clear deprecated field
        
        # Handle websocket_fallback_enabled -> enable_polling_fallback migration
        if self.websocket_fallback_enabled is not None:
            self.enable_polling_fallback = self.websocket_fallback_enabled
            self.websocket_fallback_enabled = None  # Clear deprecated field
    
    def get_transport_strategy_config(self) -> Dict[str, Any]:
        """Get configuration for transport strategy selection."""
        return {
            "transport_mode": self.transport_mode,
            "enable_realtime": self.enable_realtime,
            "enable_polling_fallback": self.enable_polling_fallback,
            "websocket_config": self.websocket_config,
            "max_concurrent_syncs": self.max_concurrent_syncs
        }
    
    def get_realtime_instruments(self) -> List[InstrumentConfig]:
        """Get instruments configured for real-time data."""
        return [
            inst for inst in self.instruments 
            if inst.enabled and inst.realtime_source in ["websocket", "auto"]
        ]
    
    def get_polling_instruments(self) -> List[InstrumentConfig]:
        """Get instruments configured for polling data."""
        return [
            inst for inst in self.instruments 
            if inst.enabled and inst.realtime_source in ["polling", "auto"]
        ]
    
    def should_use_realtime_transport(self) -> bool:
        """Determine if real-time transport should be used."""
        return (
            self.enable_realtime and 
            self.transport_mode in ["realtime", "hybrid", "auto"] and
            len(self.get_realtime_instruments()) > 0
        )
    
    def should_use_polling_transport(self) -> bool:
        """Determine if polling transport should be used."""
        return (
            self.transport_mode in ["polling", "hybrid", "auto"] and
            (len(self.get_polling_instruments()) > 0 or self.enable_polling_fallback)
        )

    @classmethod
    def load_from_file(cls, config_path: Path) -> 'OKXConfig':
        """Load configuration from JSON file."""
        if not config_path.exists():
            config = cls()
            config.save_to_file(config_path)
            return config
            
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise ConfigurationError(f"Failed to load configuration from {config_path}: {e}")
        
        # Validate configuration data
        try:
            ConfigValidator.validate_and_raise(data)
        except Exception as e:
            raise ConfigurationError(f"Configuration validation failed: {e}")
        
        # Convert instruments
        instruments = []
        for inst_data in data.get('instruments', []):
            instruments.append(InstrumentConfig(**inst_data))
        data['instruments'] = instruments
        
        # Convert websocket_config
        if 'websocket_config' in data and isinstance(data['websocket_config'], dict):
            data['websocket_config'] = WebSocketConfig(**data['websocket_config'])
        
        return cls(**data)

    def save_to_file(self, config_path: Path) -> None:
        """Save configuration to JSON file."""
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert to serializable format
            data = {}
            for key, value in self.__dict__.items():
                if isinstance(value, Path):
                    data[key] = str(value)
                elif key == 'instruments':
                    data[key] = [inst.__dict__ for inst in value]
                elif key == 'websocket_config':
                    data[key] = value.__dict__ if hasattr(value, '__dict__') else value
                else:
                    data[key] = value
            
            # Validate before saving
            ConfigValidator.validate_and_raise(data)
            
            with open(config_path, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration to {config_path}: {e}")

    def get_instrument(self, symbol: str) -> Optional[InstrumentConfig]:
        """Get configuration for a specific instrument."""
        for instrument in self.instruments:
            if instrument.symbol == symbol:
                return instrument
        return None

    def add_instrument(self, symbol: str, timeframes: List[str] = None, **kwargs) -> InstrumentConfig:
        """Add or update instrument configuration."""
        # Validate symbol
        if not ConfigValidator.validate_symbol(symbol):
            raise ConfigurationError(f"Invalid symbol format: {symbol}")
        
        # Validate timeframes
        if timeframes:
            invalid_tfs = ConfigValidator.validate_timeframes(timeframes)
            if invalid_tfs:
                raise ConfigurationError(f"Invalid timeframes: {', '.join(invalid_tfs)}")
        
        existing = self.get_instrument(symbol)
        if existing:
            if timeframes:
                existing.timeframes = timeframes
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            return existing
        
        if not timeframes:
            timeframes = ['1m', '5m', '1h', '1d']
        
        instrument = InstrumentConfig(symbol=symbol, timeframes=timeframes, **kwargs)
        self.instruments.append(instrument)
        return instrument

    @property 
    def available_timeframes(self) -> List[str]:
        """Get all supported OKX timeframes."""
        return get_supported_timeframes()

    def get_env_credentials(self) -> Dict[str, Optional[str]]:
        """Get API credentials from environment variables."""
        return {
            'api_key': os.getenv('OKX_API_KEY', self.api_key),
            'api_secret': os.getenv('OKX_API_SECRET', self.api_secret),
            'passphrase': os.getenv('OKX_PASSPHRASE', self.passphrase),
        }


def create_default_config() -> OKXConfig:
    """Create a default configuration with common trading pairs."""
    config = OKXConfig()
    
    # Add some popular trading pairs
    popular_pairs = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT']
    for symbol in popular_pairs:
        config.add_instrument(symbol)
    
    return config