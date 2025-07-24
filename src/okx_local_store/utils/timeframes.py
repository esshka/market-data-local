"""Centralized timeframe utilities and mappings."""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class TimeframeInfo:
    """Information about a timeframe."""
    symbol: str
    minutes: int
    milliseconds: int
    display_name: str


class TimeframeRegistry:
    """Registry for all supported timeframes with their properties."""
    
    _TIMEFRAMES = {
        '1m': TimeframeInfo('1m', 1, 60 * 1000, '1 Minute'),
        '3m': TimeframeInfo('3m', 3, 3 * 60 * 1000, '3 Minutes'),
        '5m': TimeframeInfo('5m', 5, 5 * 60 * 1000, '5 Minutes'),
        '15m': TimeframeInfo('15m', 15, 15 * 60 * 1000, '15 Minutes'),
        '30m': TimeframeInfo('30m', 30, 30 * 60 * 1000, '30 Minutes'),
        '1h': TimeframeInfo('1h', 60, 60 * 60 * 1000, '1 Hour'),
        '1H': TimeframeInfo('1H', 60, 60 * 60 * 1000, '1 Hour'),
        '2H': TimeframeInfo('2H', 120, 2 * 60 * 60 * 1000, '2 Hours'),
        '4H': TimeframeInfo('4H', 240, 4 * 60 * 60 * 1000, '4 Hours'),
        '6H': TimeframeInfo('6H', 360, 6 * 60 * 60 * 1000, '6 Hours'),
        '12H': TimeframeInfo('12H', 720, 12 * 60 * 60 * 1000, '12 Hours'),
        '1d': TimeframeInfo('1d', 1440, 24 * 60 * 60 * 1000, '1 Day'),
        '1D': TimeframeInfo('1D', 1440, 24 * 60 * 60 * 1000, '1 Day'),
        '1w': TimeframeInfo('1w', 10080, 7 * 24 * 60 * 60 * 1000, '1 Week'),
        '1W': TimeframeInfo('1W', 10080, 7 * 24 * 60 * 60 * 1000, '1 Week'),
        '1M': TimeframeInfo('1M', 43200, 30 * 24 * 60 * 60 * 1000, '1 Month'),
        '3M': TimeframeInfo('3M', 129600, 90 * 24 * 60 * 60 * 1000, '3 Months'),
    }
    
    @classmethod
    def get_info(cls, timeframe: str) -> Optional[TimeframeInfo]:
        """Get timeframe information."""
        return cls._TIMEFRAMES.get(timeframe)
    
    @classmethod
    def is_valid(cls, timeframe: str) -> bool:
        """Check if timeframe is valid."""
        return timeframe in cls._TIMEFRAMES
    
    @classmethod
    def get_duration_ms(cls, timeframe: str) -> Optional[int]:
        """Get timeframe duration in milliseconds."""
        info = cls.get_info(timeframe)
        return info.milliseconds if info else None
    
    @classmethod
    def get_duration_minutes(cls, timeframe: str) -> Optional[int]:
        """Get timeframe duration in minutes."""
        info = cls.get_info(timeframe)
        return info.minutes if info else None
    
    @classmethod
    def get_all_symbols(cls) -> List[str]:
        """Get all available timeframe symbols."""
        return list(cls._TIMEFRAMES.keys())
    
    @classmethod
    def get_display_name(cls, timeframe: str) -> str:
        """Get human-readable display name for timeframe."""
        info = cls.get_info(timeframe)
        return info.display_name if info else timeframe
    
    @classmethod
    def normalize_symbol(cls, timeframe: str) -> str:
        """Normalize timeframe symbol (e.g., '1H' -> '1h')."""
        # Handle common variations
        canonical_mapping = {
            '1H': '1h',
            '1D': '1d', 
            '1W': '1w',
        }
        
        return canonical_mapping.get(timeframe, timeframe)


# Convenience functions for backward compatibility
def get_timeframe_duration_ms(timeframe: str) -> int:
    """Get timeframe duration in milliseconds (backward compatible)."""
    duration = TimeframeRegistry.get_duration_ms(timeframe)
    return duration if duration is not None else 60 * 1000  # Default to 1 minute


def get_timeframe_duration_minutes(timeframe: str) -> int:
    """Get timeframe duration in minutes (backward compatible)."""
    duration = TimeframeRegistry.get_duration_minutes(timeframe)
    return duration if duration is not None else 1  # Default to 1 minute


def validate_timeframe(timeframe: str) -> bool:
    """Validate if timeframe is supported."""
    return TimeframeRegistry.is_valid(timeframe)


def get_supported_timeframes() -> List[str]:
    """Get list of all supported timeframes."""
    return TimeframeRegistry.get_all_symbols()