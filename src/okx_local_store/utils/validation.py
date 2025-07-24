"""Configuration validation utilities."""

import re
from typing import List, Optional, Dict, Any
from pathlib import Path

from .timeframes import TimeframeRegistry


class ValidationError(Exception):
    """Configuration validation error."""
    pass


class ConfigValidator:
    """Validator for OKX Local Store configuration."""
    
    # Valid symbol pattern (e.g., BTC-USDT, ETH-BTC)
    SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{2,10}-[A-Z0-9]{2,10}$')
    
    @classmethod
    def validate_symbol(cls, symbol: str) -> bool:
        """Validate trading pair symbol format."""
        if not isinstance(symbol, str):
            return False
        # Must be uppercase and match pattern
        return bool(cls.SYMBOL_PATTERN.match(symbol) and symbol == symbol.upper())
    
    @classmethod
    def validate_timeframe(cls, timeframe: str) -> bool:
        """Validate timeframe."""
        if not isinstance(timeframe, str):
            return False
        return TimeframeRegistry.is_valid(timeframe)
    
    @classmethod 
    def validate_timeframes(cls, timeframes: List[str]) -> List[str]:
        """Validate list of timeframes and return invalid ones."""
        if not isinstance(timeframes, list):
            return ["timeframes must be a list"]
        
        invalid = []
        for tf in timeframes:
            if not cls.validate_timeframe(tf):
                invalid.append(f"invalid timeframe: {tf}")
        
        return invalid
    
    @classmethod
    def validate_sync_interval(cls, interval: int) -> bool:
        """Validate sync interval (must be positive integer)."""
        if not isinstance(interval, int):
            return False
        return interval > 0
    
    @classmethod
    def validate_max_history_days(cls, days: int) -> bool:
        """Validate max history days (must be positive integer)."""
        if not isinstance(days, int):
            return False
        return days > 0
    
    @classmethod
    def validate_data_dir(cls, data_dir: Path) -> List[str]:
        """Validate data directory."""
        errors = []
        
        if not isinstance(data_dir, Path):
            try:
                data_dir = Path(data_dir)
            except (TypeError, ValueError):
                return ["data_dir must be a valid path"]
        
        # Check if parent directory exists and is writable
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            if not data_dir.is_dir():
                errors.append("data_dir is not a directory")
            elif not data_dir.exists():
                errors.append("data_dir does not exist and cannot be created")
        except PermissionError:
            errors.append("insufficient permissions to create/access data_dir")
        except Exception as e:
            errors.append(f"data_dir validation error: {e}")
        
        return errors
    
    @classmethod
    def validate_log_level(cls, log_level: str) -> bool:
        """Validate log level."""
        if not isinstance(log_level, str):
            return False
        
        valid_levels = ['TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL']
        return log_level.upper() in valid_levels
    
    @classmethod
    def validate_rate_limit(cls, rate_limit: int) -> bool:
        """Validate rate limit per minute."""
        if not isinstance(rate_limit, int):
            return False
        return 1 <= rate_limit <= 1000  # Reasonable bounds
    
    @classmethod
    def validate_max_concurrent_syncs(cls, max_syncs: int) -> bool:
        """Validate max concurrent syncs."""
        if not isinstance(max_syncs, int):
            return False
        return 1 <= max_syncs <= 20  # Reasonable bounds
    
    @classmethod
    def validate_instrument_config(cls, config: Dict[str, Any]) -> List[str]:
        """Validate instrument configuration dictionary."""
        errors = []
        
        # Required fields
        if 'symbol' not in config:
            errors.append("missing required field: symbol")
        elif not cls.validate_symbol(config['symbol']):
            errors.append(f"invalid symbol format: {config['symbol']}")
        
        # Optional fields with validation
        if 'timeframes' in config:
            tf_errors = cls.validate_timeframes(config['timeframes'])
            errors.extend(tf_errors)
        
        if 'sync_interval_seconds' in config:
            if not cls.validate_sync_interval(config['sync_interval_seconds']):
                errors.append("sync_interval_seconds must be a positive integer")
        
        if 'max_history_days' in config:
            if not cls.validate_max_history_days(config['max_history_days']):
                errors.append("max_history_days must be a positive integer")
        
        if 'enabled' in config:
            if not isinstance(config['enabled'], bool):
                errors.append("enabled must be a boolean")
        
        return errors
    
    @classmethod
    def validate_okx_config(cls, config: Dict[str, Any]) -> List[str]:
        """Validate main OKX configuration dictionary."""
        errors = []
        
        # Data directory
        if 'data_dir' in config:
            dir_errors = cls.validate_data_dir(Path(config['data_dir']))
            errors.extend(dir_errors)
        
        # Log level
        if 'log_level' in config:
            if not cls.validate_log_level(config['log_level']):
                errors.append("invalid log_level (must be one of: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL)")
        
        # Rate limiting
        if 'rate_limit_per_minute' in config:
            if not cls.validate_rate_limit(config['rate_limit_per_minute']):
                errors.append("rate_limit_per_minute must be between 1 and 1000")
        
        # Max concurrent syncs
        if 'max_concurrent_syncs' in config:
            if not cls.validate_max_concurrent_syncs(config['max_concurrent_syncs']):
                errors.append("max_concurrent_syncs must be between 1 and 20")
        
        # Boolean fields
        boolean_fields = ['sandbox', 'enable_auto_sync', 'sync_on_startup']
        for field in boolean_fields:
            if field in config and not isinstance(config[field], bool):
                errors.append(f"{field} must be a boolean")
        
        # Instruments validation
        if 'instruments' in config:
            if not isinstance(config['instruments'], list):
                errors.append("instruments must be a list")
            else:
                for i, instrument in enumerate(config['instruments']):
                    inst_errors = cls.validate_instrument_config(instrument)
                    for error in inst_errors:
                        errors.append(f"instrument[{i}]: {error}")
        
        return errors
    
    @classmethod
    def validate_and_raise(cls, config: Dict[str, Any]) -> None:
        """Validate configuration and raise ValidationError if invalid."""
        errors = cls.validate_okx_config(config)
        if errors:
            raise ValidationError(f"Configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors))