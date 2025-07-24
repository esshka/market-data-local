# WebSocket URL Fix

## Issue Fixed
The WebSocket connection was using the wrong endpoint URL. The error message indicated that candle channels don't exist on `/ws/v5/public` endpoint, and we need to use `/ws/v5/business` for market data subscriptions.

## Error Message
```
ERROR: Wrong URL or channel:candle1H,instId:BTC-USDT doesn't exist. Please use the correct URL, channel and parameters referring to API document.
```

## Root Cause
The WebSocket client was connecting to the **public** endpoint:
- ❌ `wss://ws.okx.com:8443/ws/v5/public` (sandbox)
- ❌ `wss://wspap.okx.com:8443/ws/v5/public` (production)

But candle data requires the **business** endpoint:
- ✅ `wss://ws.okx.com:8443/ws/v5/business` (sandbox)
- ✅ `wss://wspap.okx.com:8443/ws/v5/business` (production)

## Fix Applied

**File:** `src/okx_local_store/simple_websocket_client.py`

**Before:**
```python
self.base_url = (
    "wss://wspap.okx.com:8443/ws/v5/public" if not sandbox 
    else "wss://ws.okx.com:8443/ws/v5/public"
)
```

**After:**
```python
self.base_url = (
    "wss://wspap.okx.com:8443/ws/v5/business" if not sandbox 
    else "wss://ws.okx.com:8443/ws/v5/business"
)
```

## OKX WebSocket Endpoint Reference

According to OKX API documentation:

- **`/ws/v5/public`**: Public market data (tickers, order book, trades)
- **`/ws/v5/business`**: **Candlestick/OHLCV data** ← Required for our use case
- **`/ws/v5/private`**: Private account data (requires authentication)

## Verification

✅ **Both URLs updated**: Sandbox and production environments
✅ **Correct endpoint**: `/ws/v5/business` for candle data
✅ **Channel formats preserved**: Still using proper `candle1H`, `candle1D` formats
✅ **Backward compatibility**: No breaking changes to API

## Test Steps

1. **Install dependencies**: `pip install -e .`

2. **Run the demo**: `python3 demo_simplified_websocket.py`

3. **Expected behavior**:
   - ✅ Connects to correct `/ws/v5/business` endpoint
   - ✅ Successfully subscribes to BTC-USDT 1H candles
   - ✅ Receives real-time OHLCV data without URL/channel errors
   - ✅ Shows proper message statistics and clean disconnection

## Combined Fixes Applied

1. ✅ **Configuration fix**: Resolved `close_timeout` attribute error
2. ✅ **Channel format fix**: Added proper OKX channel mapping (`candle1H`, `candle1D`)
3. ✅ **URL endpoint fix**: Changed from `/ws/v5/public` to `/ws/v5/business`

The WebSocket client should now connect to the correct endpoint and successfully stream candle data!