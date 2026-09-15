#!/usr/bin/env python3
"""Dolphin debugging CLI for Melee.

    melee-agent dolphin launch --iso game.iso --session /tmp/melee-session
    melee-agent dolphin --session /tmp/melee-session read lbLang_SetLanguageSetting -n 4
    melee-agent dolphin --session /tmp/melee-session resume
    melee-agent dolphin --session /tmp/melee-session input tap START
    melee-agent dolphin --session /tmp/melee-session capture
    melee-agent dolphin --session /tmp/melee-session stop

Launch stays alive as the foreground owner. The legacy interactive attach API
is explicit; owned sessions never fall back to another GDB stub or DME.
"""

import argparse
import json
import sys
from pathlib import Path

from . import daemon as dbg_daemon
from .debugger import ConnectionMode, DolphinDebugger

# Default paths
DEFAULT_ISO = Path.home() / "Downloads/ssbm_v1.02_original.iso"
DOLPHIN_DEBUG_APP = Path.home() / "Applications/Dolphin-Debug.app"
SYMBOLS_FILE = dbg_daemon.symbols_path()


class DaemonClient:
    """Client for communicating with the debug daemon."""

    def __init__(self):
        self.connected = False

    def is_available(self) -> bool:
        """Check if daemon is running."""
        return dbg_daemon.is_running()

    def send(self, cmd: dict, timeout: float = 60.0) -> dict:
        """Send command to daemon."""
        return dbg_daemon.send_command(cmd, timeout)


class MeleeDebugCLI:
    """CLI interface for Melee debugging."""

    def __init__(self):
        self.dbg = DolphinDebugger()
        self._symbols_loaded = False
        self._daemon = DaemonClient()

    def _use_daemon(self) -> bool:
        """Check if we should use the daemon."""
        return self._daemon.is_available()

    def _ensure_symbols(self):
        """Load symbols if not already loaded."""
        if not self._symbols_loaded and SYMBOLS_FILE.exists():
            count = self.dbg.load_symbols(SYMBOLS_FILE)
            self._symbols_loaded = True
            return count
        return 0

    def _format_address(self, addr: int) -> str:
        """Format an address, with symbol if known."""
        self._ensure_symbols()
        sym = self.dbg.get_symbol_at(addr)
        if sym:
            return f"0x{addr:08X} <{sym}>"
        return f"0x{addr:08X}"

    def cmd_launch(self, iso_path=None, wait=True, **options):
        """Run an owned session in the foreground, retaining the GDB connection."""
        if not wait:
            print("Error: --no-wait is removed; keep the foreground owner alive or use shell backgrounding")
            return 1
        return dbg_daemon.DebugDaemon().start(iso_path=iso_path or str(DEFAULT_ISO), **options)

    def cmd_connect(self, mode: str = "auto"):
        """Connect to running Dolphin."""
        if mode == "gdb":
            conn_mode = ConnectionMode.GDB
        elif mode == "memory":
            conn_mode = ConnectionMode.MEMORY_ENGINE
        else:
            conn_mode = ConnectionMode.AUTO

        self.dbg.mode = conn_mode

        print(f"Connecting ({mode} mode)...")
        if self.dbg.connect(timeout=5.0):
            print("Connected!")
            if self.dbg.has_gdb:
                print("  GDB stub: active")
            if self.dbg.has_memory_engine:
                print("  Memory engine: active")
            game_id = self.dbg.get_game_id()
            if game_id:
                print(f"  Game: {game_id}")
            return 0
        else:
            print("Failed to connect to Dolphin")
            print("Make sure Dolphin-Debug is running with a game loaded")
            return 1

    def cmd_read(self, address: str, count: int = 16, fmt: str = "hex"):
        """Read memory at address."""
        if not self._ensure_connected():
            return 1

        addr = self.dbg.resolve_address(address)
        if addr is None:
            print(f"Error: Cannot resolve address '{address}'")
            return 1

        data = self.dbg.read_bytes(addr, count)
        if data is None:
            print(f"Error: Failed to read memory at {self._format_address(addr)}")
            return 1

        print(f"Memory at {self._format_address(addr)}:")

        if fmt == "hex":
            # Hex dump format
            for i in range(0, len(data), 16):
                chunk = data[i : i + 16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"  {addr + i:08X}  {hex_part:<48}  {ascii_part}")

        elif fmt == "u32":
            for i in range(0, len(data), 4):
                if i + 4 <= len(data):
                    val = int.from_bytes(data[i : i + 4], "big")
                    print(f"  {addr + i:08X}: 0x{val:08X} ({val})")

        elif fmt == "f32":
            import struct

            for i in range(0, len(data), 4):
                if i + 4 <= len(data):
                    val = struct.unpack(">f", data[i : i + 4])[0]
                    print(f"  {addr + i:08X}: {val:.6f}")

        elif fmt == "string":
            s = self.dbg.read_string(addr, count)
            print(f'  "{s}"')

        return 0

    def cmd_write(self, address: str, value: str):
        """Write value to memory."""
        if not self._ensure_connected():
            return 1

        addr = self.dbg.resolve_address(address)
        if addr is None:
            print(f"Error: Cannot resolve address '{address}'")
            return 1

        # Determine value type and write
        try:
            if value.startswith("0x"):
                int_val = int(value, 16)
            elif "." in value:
                float_val = float(value)
                if self.dbg.write_f32(addr, float_val):
                    print(f"Wrote {float_val} to {self._format_address(addr)}")
                    return 0
                else:
                    print("Write failed")
                    return 1
            else:
                int_val = int(value)

            if self.dbg.write_u32(addr, int_val):
                print(f"Wrote 0x{int_val:08X} to {self._format_address(addr)}")
                return 0
            else:
                print("Write failed")
                return 1
        except ValueError:
            print(f"Error: Invalid value '{value}'")
            return 1

    def cmd_break(self, address: str, remove: bool = False):
        """Set or remove a breakpoint."""
        # Use daemon if available (preferred for persistent connections)
        if self._use_daemon():
            result = self._daemon.send({"action": "break", "address": address, "remove": remove})
            if result.get("success"):
                data = result.get("data", {})
                if remove:
                    print(f"Removed breakpoint at {address}")
                else:
                    addr = data.get("address", 0)
                    sym = data.get("symbol", "")
                    if sym:
                        print(f"Set breakpoint at 0x{addr:08X} <{sym}>")
                    else:
                        print(f"Set breakpoint at 0x{addr:08X}")
                return 0
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")
                return 1

        # Direct connection (one-shot)
        if not self._ensure_connected():
            return 1

        if not self.dbg.has_gdb:
            print("Error: Breakpoints require GDB stub connection")
            print("Tip: Use 'melee-debug daemon start' for persistent debugging")
            return 1

        self._ensure_symbols()
        addr = self.dbg.resolve_address(address)
        if addr is None:
            print(f"Error: Cannot resolve address '{address}'")
            return 1

        if remove:
            if self.dbg.remove_breakpoint(addr):
                print(f"Removed breakpoint at {self._format_address(addr)}")
                return 0
            else:
                print("Failed to remove breakpoint")
                return 1
        else:
            if self.dbg.set_breakpoint(addr):
                print(f"Set breakpoint at {self._format_address(addr)}")
                return 0
            else:
                print("Failed to set breakpoint")
                return 1

    def cmd_watch(self, address: str, size: int = 4, read: bool = False, write: bool = True):
        """Set a memory watchpoint."""
        if not self._ensure_connected():
            return 1

        if not self.dbg.has_gdb:
            print("Error: Watchpoints require GDB stub connection")
            return 1

        addr = self.dbg.resolve_address(address)
        if addr is None:
            print(f"Error: Cannot resolve address '{address}'")
            return 1

        mode = []
        if read:
            mode.append("read")
        if write:
            mode.append("write")

        if self.dbg.set_watchpoint(addr, size, write=write, read=read):
            print(f"Set {'/'.join(mode)} watchpoint at {self._format_address(addr)} ({size} bytes)")
            return 0
        else:
            print("Failed to set watchpoint")
            return 1

    def cmd_step(self, count: int = 1):
        """Single-step instructions."""
        if type(count) is not int or not 1 <= count <= 10000:
            print("Error: step count must be an integer from 1 to 10000")
            return 1
        if self._use_daemon():
            result = self._daemon.send({"action": "step", "count": count})
            if result.get("success"):
                print(f"Stepped {count} instruction(s)")
                return 0
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")
                return 1

        if not self._ensure_connected():
            return 1

        if not self.dbg.has_gdb:
            print("Error: Stepping requires GDB stub connection")
            return 1

        for i in range(count):
            result = self.dbg.step()
            if result:
                print(f"Step {i + 1}: {result}")
            else:
                print(f"Step {i + 1} failed: {self.dbg.last_error}")
                return 1

        return 0

    def cmd_continue(self):
        """Continue execution."""
        if self._use_daemon():
            print("Continuing execution (will block until breakpoint hit)...")
            try:
                result = self._daemon.send({"action": "continue"}, timeout=60.0)
            except KeyboardInterrupt:
                return self.cmd_halt()
            if result.get("success"):
                stop_reason = result.get("data")
                print(f"Stopped: {stop_reason}")
                return 0
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")
                return 1

        if not self._ensure_connected():
            return 1

        if not self.dbg.has_gdb:
            print("Error: Continue requires GDB stub connection")
            return 1

        print("Continuing execution (Ctrl+C to interrupt)...")
        try:
            result = self.dbg.continue_execution()
            if result:
                print(f"Stopped: {result}")
            else:
                print(f"Continue failed: {self.dbg.last_error} ({self.dbg.execution_state})")
                return 1
        except KeyboardInterrupt:
            return self.cmd_halt()

        return 0

    def cmd_halt(self):
        """Halt execution."""
        if self._use_daemon():
            result = self._daemon.send({"action": "halt"})
            if result.get("success"):
                print("Confirmed stopped")
                return 0
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")
                return 1

        if not self._ensure_connected():
            return 1

        if self.dbg.halt():
            print("Confirmed stopped")
            return 0
        else:
            print("Failed to halt")
            return 1

    def cmd_regs(self):
        """Display registers."""
        if self._use_daemon():
            result = self._daemon.send({"action": "regs"})
            if result.get("success"):
                regs = result.get("data", {})
                print("General Purpose Registers:")
                gprs = regs.get("gpr", [])
                for i in range(0, min(32, len(gprs)), 4):
                    line = "  "
                    for j in range(4):
                        if i + j < len(gprs):
                            line += f"r{i + j:2d}=0x{gprs[i + j]:08X}  "
                    print(line)
                return 0
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")
                return 1

        if not self._ensure_connected():
            return 1

        if not self.dbg.has_gdb:
            print("Error: Register access requires GDB stub connection")
            return 1

        regs = self.dbg.read_registers()
        if not regs:
            print("Failed to read registers")
            return 1

        print("General Purpose Registers:")
        gprs = regs.get("gpr", [])
        for i in range(0, min(32, len(gprs)), 4):
            line = "  "
            for j in range(4):
                if i + j < len(gprs):
                    line += f"r{i + j:2d}=0x{gprs[i + j]:08X}  "
            print(line)

        return 0

    def cmd_symbol(self, name: str):
        """Look up a symbol."""
        self._ensure_symbols()

        # Try exact match
        sym = self.dbg.get_symbol(name)
        if sym:
            print(f"{sym.name}:")
            print(f"  Address: 0x{sym.address:08X}")
            print(f"  Type: {sym.sym_type}")
            if sym.size:
                print(f"  Size: 0x{sym.size:X} ({sym.size} bytes)")
            return 0

        # Try partial match
        matches = [s for s in self.dbg.symbols.values() if name.lower() in s.name.lower()]
        if matches:
            print(f"Found {len(matches)} matching symbols:")
            for sym in matches[:20]:
                print(f"  0x{sym.address:08X}  {sym.name}")
            if len(matches) > 20:
                print(f"  ... and {len(matches) - 20} more")
            return 0

        print(f"Symbol '{name}' not found")
        return 1

    def cmd_status(self):
        """Show connection status."""
        print("Dolphin Debug Status:")

        # Check daemon first
        if self._use_daemon():
            result = self._daemon.send({"action": "status"})
            if result.get("success"):
                data = result.get("data", {})
                print("  Mode: daemon (persistent)")
                print(f"  Connected: {data.get('connected', False)}")
                print(f"  GDB stub: {'active' if data.get('has_gdb') else 'inactive'}")
                print(f"  Memory engine: {'active' if data.get('has_memory') else 'inactive'}")
                if data.get("game_id"):
                    print(f"  Game ID: {data['game_id']}")
                print(f"  Symbols loaded: {data.get('symbols', 0)}")
                print(f"  Breakpoints: {data.get('breakpoints', 0)}")
                return 0
            else:
                print(f"  Daemon error: {result.get('error')}")
                return 1

        print("  Mode: direct (one-shot)")
        print("  Daemon: not running (use 'daemon start' for persistent debugging)")
        print(f"  Connected: {self.dbg.is_connected}")
        print(f"  GDB stub: {'active' if self.dbg.has_gdb else 'inactive'}")
        print(f"  Memory engine: {'active' if self.dbg.has_memory_engine else 'inactive'}")

        if self.dbg.is_connected:
            game_id = self.dbg.get_game_id()
            if game_id:
                print(f"  Game ID: {game_id}")
            frame = self.dbg.get_frame_count()
            if frame is not None:
                print(f"  Frame: {frame}")

        print(f"  Symbols loaded: {len(self.dbg.symbols)}")
        print(f"  Breakpoints: {len(self.dbg.breakpoints)}")

        return 0

    def cmd_interactive(self):
        """Enter interactive debugging mode."""
        if not self._ensure_connected():
            return 1

        self._ensure_symbols()

        print("Melee Debug Interactive Mode")
        print("Commands: r[ead] w[rite] b[reak] s[tep] c[ont] h[alt] reg sym q[uit]")
        print()

        while True:
            try:
                line = input("melee> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()

            try:
                if cmd in ("q", "quit", "exit"):
                    break
                elif cmd in ("r", "read"):
                    if len(parts) >= 2:
                        count = int(parts[2], 0) if len(parts) > 2 else 16
                        self.cmd_read(parts[1], count)
                    else:
                        print("Usage: read <address> [count]")
                elif cmd in ("w", "write"):
                    if len(parts) >= 3:
                        self.cmd_write(parts[1], parts[2])
                    else:
                        print("Usage: write <address> <value>")
                elif cmd in ("b", "break"):
                    if len(parts) >= 2:
                        self.cmd_break(parts[1], remove="-r" in parts or "--remove" in parts)
                    else:
                        print("Usage: break <address> [-r]")
                elif cmd in ("s", "step"):
                    count = int(parts[1]) if len(parts) > 1 else 1
                    self.cmd_step(count)
                elif cmd in ("c", "cont", "continue"):
                    self.cmd_continue()
                elif cmd in ("h", "halt", "stop"):
                    self.cmd_halt()
                elif cmd in ("reg", "regs", "registers"):
                    self.cmd_regs()
                elif cmd in ("sym", "symbol"):
                    if len(parts) >= 2:
                        self.cmd_symbol(parts[1])
                    else:
                        print("Usage: sym <name>")
                elif cmd == "status":
                    self.cmd_status()
                elif cmd == "help":
                    print("Commands:")
                    print("  read <addr> [count]    Read memory")
                    print("  write <addr> <value>   Write memory")
                    print("  break <addr> [-r]      Set/remove breakpoint")
                    print("  step [count]           Single-step")
                    print("  cont                   Continue execution")
                    print("  halt                   Stop execution")
                    print("  regs                   Show registers")
                    print("  sym <name>             Look up symbol")
                    print("  status                 Show status")
                    print("  quit                   Exit")
                else:
                    print(f"Unknown command: {cmd}")
            except Exception as e:
                print(f"Error: {e}")

        return 0

    def _ensure_connected(self) -> bool:
        """Ensure we're connected to Dolphin."""
        if self.dbg.is_connected:
            self._ensure_symbols()
            return True

        print("Not connected. Attempting to connect...")
        if self.dbg.connect(timeout=2.0):
            self._ensure_symbols()
            return True

        print("Failed to connect. Use 'melee-debug connect' or 'melee-debug launch'")
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Dolphin debugging CLI for Melee",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--session", help="Owned session directory; commands never fall back to direct attachment")
    parser.add_argument("--symbols", help="Explicit symbols file for launch or local symbol lookup")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="Manage persistent debug daemon")
    p_daemon.add_argument("action", choices=["start", "stop", "status"], help="Daemon action")

    # launch
    p_launch = subparsers.add_parser("launch", help="Launch Dolphin with GDB stub")
    p_launch.add_argument("--iso", help="Path to Melee ISO")
    p_launch.add_argument(
        "--session", default=argparse.SUPPRESS, help="New private session directory (default /tmp/dolphin-<id>)"
    )
    p_launch.add_argument("--symbols", default=argparse.SUPPRESS, help="Override active-worktree symbols file")
    p_launch.add_argument("--dolphin", help="Dolphin executable or .app bundle")
    p_launch.add_argument("--profile", help="New isolated profile directory")
    p_launch.add_argument("--port", type=int, default=0, help="Dedicated GDB port; 0 allocates a free port")
    p_launch.add_argument("--interpreter", action="store_true", help="Explicitly select CPUCore=0")
    p_launch.add_argument("--timeout", type=float, default=30, help="Readiness timeout in host seconds")

    # connect
    p_connect = subparsers.add_parser("connect", help="Connect to running Dolphin")
    p_connect.add_argument("--gdb", action="store_true", help="Use GDB stub only")
    p_connect.add_argument("--memory", action="store_true", help="Use memory engine only")

    # read
    p_read = subparsers.add_parser("read", help="Read memory")
    p_read.add_argument("address", help="Address or symbol name")
    p_read.add_argument("-n", "--count", type=int, default=16, help="Bytes to read")
    p_read.add_argument("-f", "--format", choices=["hex", "u32", "f32", "string"], default="hex")

    # write
    p_write = subparsers.add_parser("write", help="Write memory")
    p_write.add_argument("address", help="Address or symbol name")
    p_write.add_argument("value", help="Value to write")

    # break
    p_break = subparsers.add_parser("break", help="Set/remove breakpoint")
    p_break.add_argument("address", help="Address or symbol name")
    p_break.add_argument("-r", "--remove", action="store_true", help="Remove breakpoint")

    # watch
    p_watch = subparsers.add_parser("watch", help="Set memory watchpoint")
    p_watch.add_argument("address", help="Address or symbol name")
    p_watch.add_argument("-s", "--size", type=int, default=4, help="Watch size")
    p_watch.add_argument("--read", action="store_true", help="Watch reads")
    p_watch.add_argument("--write", action="store_true", default=True, help="Watch writes")

    # step
    p_step = subparsers.add_parser("step", help="Single-step")
    p_step.add_argument("-n", "--count", type=int, default=1, help="Steps to take")
    p_step.add_argument("--timeout", type=float, default=5)

    # continue
    for name in ("continue", "cont"):
        subparsers.add_parser(name, help="Continue until a confirmed stop or timeout").add_argument(
            "--timeout", type=float, default=60
        )
    subparsers.add_parser("resume", help="Issue continue; report running/request state after a short wait")
    subparsers.add_parser("stop", help="Stop only this owned session via RPC")

    # halt
    subparsers.add_parser("halt", help="Halt execution")

    # regs
    subparsers.add_parser("regs", help="Show registers")

    # symbol
    p_sym = subparsers.add_parser("symbol", help="Look up symbol")
    p_sym.add_argument("name", help="Symbol name (partial match)")

    # status
    subparsers.add_parser("status", help="Show connection status")

    # interactive
    subparsers.add_parser("interactive", help="Interactive mode")
    subparsers.add_parser("i", help="Interactive mode (alias)")

    p_input = subparsers.add_parser("input", help="Host pipe input requests; requires running session")
    input_sub = p_input.add_subparsers(dest="operation", required=True)
    for name in ("press", "release", "tap"):
        part = input_sub.add_parser(name)
        part.add_argument("token")
        if name == "tap":
            part.add_argument("--duration", type=float, default=0.3)
    input_sub.add_parser("release-all")
    stick = input_sub.add_parser("stick", help="Normalized raw pipe axes [0,1], center .5")
    stick.add_argument("token", choices=["MAIN", "C"])
    stick.add_argument("x", type=float)
    stick.add_argument("y", type=float)
    trigger = input_sub.add_parser("trigger")
    trigger.add_argument("token", choices=["L", "R"])
    trigger.add_argument("x", type=float)
    capture = subparsers.add_parser("capture", help="Fresh decoded native PNG; no game-state predicate")
    capture.add_argument("--timeout", type=float, default=10)
    capture.add_argument("--attempts", type=int, default=3)
    capture.add_argument("--settle", type=float, default=0)
    capture.add_argument("--dwell", type=float, default=0.15)
    capture.add_argument("--release-dwell", type=float, default=0.15)
    capture.add_argument("--brightness-threshold", type=float, default=32)
    capture.add_argument("--visible-fraction", type=float, default=0.001)
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "launch":
        try:
            return dbg_daemon.DebugDaemon().start(
                iso_path=args.iso or str(DEFAULT_ISO),
                dolphin_path=args.dolphin or str(DOLPHIN_DEBUG_APP),
                session=args.session,
                profile=args.profile,
                port=args.port,
                interpreter=args.interpreter,
                symbols=args.symbols,
                timeout=args.timeout,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Error: {exc}")
            return 1

    if args.command == "daemon":
        if args.action == "start":
            print("Use dolphin launch --iso ... --session ... to start the foreground owner")
            return 1
        args.command = args.action

    if args.session:
        command = {"action": {"cont": "continue"}.get(args.command, args.command)}
        if args.command == "read":
            command.update(address=args.address, count=args.count, format=args.format)
        elif args.command == "write":
            try:
                value = int(args.value, 0)
                fmt = "u32"
            except ValueError:
                try:
                    value, fmt = float(args.value), "f32"
                except ValueError:
                    print("Error: invalid write value")
                    return 1
            command.update(address=args.address, value=value, format=fmt)
        elif args.command == "break":
            command.update(address=args.address, remove=args.remove)
        elif args.command == "watch":
            command.update(address=args.address, size=args.size, read=args.read, write=args.write)
        elif args.command == "step":
            command.update(count=args.count, timeout=args.timeout)
        elif args.command in ("continue", "cont"):
            command.update(timeout=args.timeout)
        elif args.command == "symbol":
            command.update(pattern=args.name)
        elif args.command == "input":
            command["request"] = {"operation": args.operation}
            for key in ("token", "x", "y", "duration"):
                if hasattr(args, key):
                    command["request"][key] = getattr(args, key)
        elif args.command == "capture":
            command["options"] = {
                key: getattr(args, key)
                for key in (
                    "timeout",
                    "attempts",
                    "settle",
                    "dwell",
                    "release_dwell",
                    "brightness_threshold",
                    "visible_fraction",
                )
            }
        elif args.command not in ("status", "stop", "regs", "resume", "halt"):
            print("Error: this command is not supported for owned sessions")
            return 1
        try:
            result = dbg_daemon.send_command(command, session=args.session)
            print(json.dumps(result, indent=2))
            return 0 if result.get("success") else 1
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Session unavailable: {exc}; no direct attachment was attempted")
            return 1

    if args.command not in ("symbol", "connect", "interactive", "i"):
        print("Error: --session is required; use launch to create an owned session")
        return 1

    cli = MeleeDebugCLI()
    if args.symbols:
        selected = dbg_daemon.symbols_path(args.symbols)
        if selected.is_file():
            cli.dbg.load_symbols(selected)
        cli._symbols_loaded = True

    if args.command == "connect":
        mode = "gdb" if args.gdb else "memory" if args.memory else "auto"
        return cli.cmd_connect(mode)
    elif args.command == "read":
        return cli.cmd_read(args.address, args.count, args.format)
    elif args.command == "write":
        return cli.cmd_write(args.address, args.value)
    elif args.command == "break":
        return cli.cmd_break(args.address, args.remove)
    elif args.command == "watch":
        return cli.cmd_watch(args.address, args.size, args.read, args.write)
    elif args.command == "step":
        return cli.cmd_step(args.count)
    elif args.command in ("continue", "cont"):
        return cli.cmd_continue()
    elif args.command == "halt":
        return cli.cmd_halt()
    elif args.command == "regs":
        return cli.cmd_regs()
    elif args.command == "symbol":
        return cli.cmd_symbol(args.name)
    elif args.command == "status":
        return cli.cmd_status()
    elif args.command in ("interactive", "i"):
        return cli.cmd_interactive()

    return 1


if __name__ == "__main__":
    sys.exit(main())
