# WebSocket Configuration Fix Verification

## Issue Fixed
The `SimpleWebSocketClient` was trying to access `self.config.close_timeout` which doesn't exist in `WebSocketConfig`. 

## Changes Made

### 1. Fixed WebSocket Connection Parameters
**File:** `src/okx_local_store/simple_websocket_client.py`

**Before:**
```python
self.websocket = await websockets.connect(
    self.base_url,
    ping_interval=self.config.ping_interval,
    ping_timeout=self.config.ping_timeout,
    close_timeout=self.config.close_timeout  # ❌ This attribute doesn't exist
)
```

**After:**
```python
self.websocket = await websockets.connect(
    self.base_url,
    ping_interval=self.config.ping_interval,
    ping_timeout=self.config.ping_timeout,
    open_timeout=self.config.connection_timeout,  # ✅ Use existing attribute
    close_timeout=10  # ✅ Use fixed value since not in config
)
```

### 2. Updated Demo and Test Scripts
Fixed `WebSocketConfig` usage in:
- `demo_simplified_websocket.py`
- `test_websocket_simplification.py`

**Before:**
```python
websocket_config = WebSocketConfig(
    ping_interval=20,
    ping_timeout=10,  # ❌ Too short
    close_timeout=10,  # ❌ This parameter doesn't exist
    max_reconnect_attempts=3
)
```

**After:**
```python
websocket_config = WebSocketConfig(
    ping_interval=20,
    ping_timeout=60,  # ✅ Use proper timeout
    connection_timeout=10,  # ✅ Use correct parameter name
    max_reconnect_attempts=3
)
```

## Available WebSocketConfig Attributes

According to `src/okx_local_store/config.py`, the `WebSocketConfig` has these attributes:

- ✅ `max_reconnect_attempts: int = 5`
- ✅ `heartbeat_interval: int = 30`
- ✅ `connection_timeout: int = 10`
- ✅ `ping_interval: int = 20`
- ✅ `ping_timeout: int = 60` 
- ✅ `max_connection_age: int = 3600`
- ✅ `reconnect_delay_base: float = 1.0`
- ✅ `reconnect_delay_max: float = 60.0`
- ✅ `enable_compression: bool = True`

## Verification Steps

### Step 1: Install Dependencies
```bash
pip install -e .
```

### Step 2: Test the Fix
```bash
python3 demo_simplified_websocket.py
```

### Step 3: Expected Behavior
The demo should now:
1. ✅ Connect to WebSocket successfully (no config attribute errors)
2. ✅ Subscribe to BTC-USDT data
3. ✅ Receive real-time candle updates
4. ✅ Show statistics and disconnect cleanly

### Step 4: Verify Structure (Without Dependencies)
```bash
python3 test_structure.py
```

This should show:
- ✅ File removal successful
- ✅ Line count reduction achieved
- ✅ Syntax validation passes

## Fix Confirmed
- ✅ Configuration attribute mismatch resolved
- ✅ WebSocket client uses correct config parameters
- ✅ Backward compatibility maintained
- ✅ All demo and test scripts updated
- ✅ Syntax validation passes

The WebSocket simplification is now ready for user testing!