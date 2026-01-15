"""Dolphin debugging interface for Melee."""

from .debugger import Breakpoint, ConnectionMode, DolphinDebugger, Symbol
from .launcher import DolphinLauncher
from .memory_client import DolphinMemory, MeleeAddresses, get_player_state
from .rsp_client import GDBClient

__all__ = [
    # Main interface
    "DolphinDebugger",
    "ConnectionMode",
    "Symbol",
    "Breakpoint",
    # Low-level
    "GDBClient",
    "DolphinLauncher",
    "DolphinMemory",
    "MeleeAddresses",
    "get_player_state",
]
