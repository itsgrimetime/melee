"""Dolphin debugging interface for Melee."""

from .debugger import Breakpoint, ConnectionMode, DolphinDebugger, Symbol
from .launcher import DolphinLauncher
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


def __getattr__(name):
    if name in {"DolphinMemory", "MeleeAddresses", "get_player_state"}:
        try:
            from . import memory_client
        except ImportError as exc:
            raise ImportError("Legacy memory access requires dolphin-memory-engine; owned GDB sessions do not") from exc
        return getattr(memory_client, name)
    raise AttributeError(name)
