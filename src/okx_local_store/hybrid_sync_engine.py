"""Hybrid sync engine focused on REST polling with real-time coordination support."""

# For backward compatibility, import the simplified version
from .simple_hybrid_sync_engine import SimplifiedHybridSyncEngine, SyncMode, InstrumentSyncState

# Alias for existing code compatibility
HybridSyncEngine = SimplifiedHybridSyncEngine

# Re-export for existing imports
__all__ = ['HybridSyncEngine', 'SimplifiedHybridSyncEngine', 'SyncMode', 'InstrumentSyncState']