"""Configuration management for OKX Local Store."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import json
import os


@dataclass
class InstrumentConfig:
    """Configuration for a specific instrument."""
    symbol: str
    timeframes: List[str] = field(default_factory=lambda: ['1m', '5m', '1h', '1d'])
    sync_interval_seconds: int = 60
    max_history_days: int = 365
    enabled: bool = True


@dataclass
class OKXConfig:
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
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[Path] = None

    def __post_init__(self):
        if isinstance(self.data_dir, str):
            self.data_dir = Path(self.data_dir)
        if self.log_file and isinstance(self.log_file, str):
            self.log_file = Path(self.log_file)

    @classmethod
    def load_from_file(cls, config_path: Path) -> 'OKXConfig':
        """Load configuration from JSON file."""
        if not config_path.exists():
            config = cls()
            config.save_to_file(config_path)
            return config
            
        with open(config_path, 'r') as f:
            data = json.load(f)
        
        # Convert instruments
        instruments = []
        for inst_data in data.get('instruments', []):
            instruments.append(InstrumentConfig(**inst_data))
        data['instruments'] = instruments
        
        return cls(**data)

    def save_to_file(self, config_path: Path) -> None:
        """Save configuration to JSON file."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to serializable format
        data = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Path):
                data[key] = str(value)
            elif key == 'instruments':
                data[key] = [inst.__dict__ for inst in value]
            else:
                data[key] = value
        
        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)

    def get_instrument(self, symbol: str) -> Optional[InstrumentConfig]:
        """Get configuration for a specific instrument."""
        for instrument in self.instruments:
            if instrument.symbol == symbol:
                return instrument
        return None

    def add_instrument(self, symbol: str, timeframes: List[str] = None, **kwargs) -> InstrumentConfig:
        """Add or update instrument configuration."""
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
        return [
            '1m', '3m', '5m', '15m', '30m',
            '1H', '2H', '4H', '6H', '12H',
            '1D', '1W', '1M', '3M'
        ]

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