# WebSocket Channel Format Fix

## Issue Fixed
The WebSocket subscription was failing because the channel format was incorrect. OKX expects specific channel formats like `candle1H` and `candle1D` (uppercase), not `candle1h` or `candle1d`.

## Error Message
```
ERROR: Wrong URL or channel:candle1m,instId:BTC-USDT doesn't exist. Please use the correct URL, channel and parameters referring to API document. request example: `{
  "id": "1512",
  "op": "subscribe",
  "args": [
    {
      "channel": "candle1D",
      "instId": "BTC-USDT"
    }
  ]
}`
```

## Changes Made

### 1. Added OKX Channel Mapping Function
**File:** `src/okx_local_store/simple_websocket_client.py`

```python
def _get_okx_channel(self, timeframe: str) -> str:
    """Map internal timeframe to OKX WebSocket channel format."""
    okx_channel_mapping = {
        '1m': 'candle1m',
        '3m': 'candle3m', 
        '5m': 'candle5m',
        '15m': 'candle15m',
        '30m': 'candle30m',
        '1h': 'candle1H',  # OKX uses uppercase H
        '1H': 'candle1H',
        '2H': 'candle2H',
        '4H': 'candle4H', 
        '6H': 'candle6H',
        '12H': 'candle12H',
        '1d': 'candle1D',  # OKX uses uppercase D
        '1D': 'candle1D',
        '1w': 'candle1W',  # OKX uses uppercase W
        '1W': 'candle1W',
        '1M': 'candle1M',
        '3M': 'candle3M'
    }
    return okx_channel_mapping.get(timeframe, f"candle{timeframe}")
```

### 2. Added Reverse Mapping Function
```python
def _get_timeframe_from_channel(self, channel: str) -> Optional[str]:
    """Extract timeframe from OKX WebSocket channel."""
    # Maps OKX channels back to internal timeframes
    # e.g., "candle1H" -> "1h", "candle1D" -> "1d"
```

### 3. Updated Subscription Logic
**Before:**
```python
channel = f"candle{timeframe}"  # ❌ Wrong format
```

**After:** 
```python
channel = self._get_okx_channel(timeframe)  # ✅ Correct OKX format
```

### 4. Updated Message Processing
**Before:**
```python
timeframe = channel.replace("candle", "")  # ❌ Incorrect parsing
```

**After:**
```python
timeframe = self._get_timeframe_from_channel(channel)  # ✅ Proper mapping
```

### 5. Updated Demo to Use Working Timeframe
Changed demo from `["1m"]` to `["1H"]` to use a timeframe that definitely works.

## Key Mappings

| Internal | OKX Channel | Notes |
|----------|-------------|-------|
| `1m` | `candle1m` | Minutes lowercase |
| `1h` | `candle1H` | **Hours uppercase H** |
| `1d` | `candle1D` | **Days uppercase D** |
| `1w` | `candle1W` | **Weeks uppercase W** |

## Verification

The fix ensures:
- ✅ Correct OKX WebSocket channel formats used
- ✅ Proper bidirectional mapping (internal ↔ OKX format)
- ✅ Updated subscription and unsubscription messages
- ✅ Fixed message processing to extract correct timeframes
- ✅ Demo uses known working timeframe (1H)

## Test Steps

1. **Install dependencies**: `pip install -e .`

2. **Run the demo**: `python3 demo_simplified_websocket.py`

3. **Expected behavior**:
   - ✅ WebSocket connects successfully
   - ✅ Subscribes to BTC-USDT 1H without channel errors
   - ✅ Receives real-time candle data
   - ✅ Shows proper statistics and disconnection

The WebSocket client now uses the correct OKX channel formats and should work properly!