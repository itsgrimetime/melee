"""Foreground owner and identity-checked RPC for isolated Dolphin sessions.

Launch through ``melee-agent dolphin launch``; clients select ``--session``.
"""

import configparser
import hashlib
import json
import math
import os
import signal
import socket
import stat
import sys
import threading
import time
import uuid
from pathlib import Path

from .debugger import ConnectionMode, DolphinDebugger
from .input_capture import Controller, NativeCapture, PipeChannel, bounded
from .launcher import DolphinLauncher
from .rsp_client import GDBClient


def symbols_path(override=None):
    return (
        Path(override).expanduser().resolve()
        if override
        else Path(__file__).resolve().parents[4] / "config/GALE01/symbols.txt"
    )


SYMBOLS_PATH = symbols_path()


def checked_directory(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError(f"Symlink session path refused: {path}")
    path = path.resolve()
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError(f"Session directory must be owned by this user with mode 0700: {path}")
    return path


def read_session(path):
    root = checked_directory(path)
    metadata = root / "session.json"
    if metadata.is_symlink() or not metadata.is_file():
        raise ValueError("Missing or unsafe session metadata")
    data = json.loads(metadata.read_text())
    if data.get("schema") != 1 or not isinstance(data.get("session_id"), str):
        raise ValueError("Invalid session identity")
    if data.get("endpoint") != str(root / "daemon.sock"):
        raise ValueError("Session endpoint does not match directory")
    return root, data


def prepare_profile(profile, port, interpreter=False):
    """Configure only the new, isolated profile, before device enumeration."""
    if os.name != "posix" or not hasattr(os, "mkfifo"):
        raise RuntimeError("Dolphin input sessions require POSIX FIFOs")
    config = profile / "Config"
    pipes = profile / "Pipes"
    config.mkdir(parents=True)
    pipes.mkdir()
    (profile / "ScreenShots").mkdir()
    for name in ("pad", "capture"):
        os.mkfifo(pipes / name, 0o600)
    dolphin = configparser.ConfigParser()
    dolphin.optionxform = str
    dolphin["General"] = {"GDBPort": str(port), "HotkeysRequireFocus": "False"}
    dolphin["Core"] = {"SIDevice0": "6"}
    if interpreter:
        dolphin["Core"]["CPUCore"] = "0"
    dolphin["Input"] = {"BackgroundInput": "True"}
    with (config / "Dolphin.ini").open("w") as out:
        dolphin.write(out)
    pad = {"Device": "Pipe/0/pad"}
    for name, token in {"A": "A", "B": "B", "X": "X", "Y": "Y", "Z": "Z", "Start": "START"}.items():
        pad[f"Buttons/{name}"] = f"`Button {token}`"
    for name in ("Up", "Down", "Left", "Right"):
        pad[f"D-Pad/{name}"] = f"`Button D_{name.upper()}`"
    for name in ("L", "R"):
        pad[f"Triggers/{name}"] = f"`Button {name}`"
        pad[f"Triggers/{name}-Analog"] = f"`Axis {name} +`"
    for group, token in (("Main Stick", "MAIN"), ("C-Stick", "C")):
        for direction, axis, sign in (("Up", "Y", "+"), ("Down", "Y", "-"), ("Left", "X", "-"), ("Right", "X", "+")):
            pad[f"{group}/{direction}"] = f"`Axis {token} {axis} {sign}`"
    gc = configparser.ConfigParser()
    gc.optionxform = str
    gc["GCPad1"] = pad
    with (config / "GCPadNew.ini").open("w") as out:
        gc.write(out)
    (config / "Hotkeys.ini").write_text("[Hotkeys]\nDevice = Pipe/0/capture\nGeneral/Take Screenshot = `Button X`\n")


class DebugDaemon:
    """Daemon that maintains GDB connection and serves commands."""

    def __init__(self):
        self.dbg: DolphinDebugger | None = None
        self.running = False
        self.server_socket: socket.socket | None = None
        self.session = None
        self.metadata = {}
        self.launcher = None
        self.controller = None
        self.capture_channel = None
        self.pad_channel = None
        self.capturer = None
        self.game_id = None
        self._threads = []
        self._bound = False
        self._endpoint_identity = None
        self._closing = False

    def handle_command(self, cmd: dict) -> dict:
        """Execute a command and return result."""
        action = cmd.get("action")
        result = {"success": False, "error": None, "data": None}

        if action == "stop":
            return {"success": True, "data": {"stopping": True}, "error": None}
        if not self.dbg or (not self.dbg.is_connected and action != "status"):
            result["error"] = "Not connected to Dolphin"
            return result

        try:
            if action == "status":
                result["data"] = {
                    "connected": self.dbg.is_connected,
                    "has_gdb": self.dbg.has_gdb,
                    "has_memory": False if self.session else self.dbg.has_memory_engine,
                    "game_id": self.game_id,
                    "session": self.metadata,
                    "execution_state": self.dbg.execution_state,
                    "execution": self.dbg.last_execution,
                    "breakpoints": len(self.dbg.breakpoints),
                    "symbols": len(self.dbg.symbols),
                }
                result["success"] = True

            elif action == "read":
                addr = cmd.get("address")
                count = cmd.get("count", 4)
                max_read = (GDBClient.MAX_PACKET - 1) // 2
                if type(count) is not int or not 1 <= count <= max_read:
                    raise ValueError(f"count must be an integer from 1 to {max_read} (RSP packet limit)")
                fmt = cmd.get("format", "hex")

                # Resolve address
                if isinstance(addr, str):
                    resolved = self.dbg.resolve_address(addr)
                    if resolved is None:
                        result["error"] = f"Cannot resolve address: {addr}"
                        return result
                    addr = resolved

                data = self.dbg.read_bytes(addr, count)
                if data:
                    if fmt == "hex":
                        result["data"] = data.hex()
                    elif fmt == "u32":
                        import struct

                        result["data"] = struct.unpack(">I", data[:4])[0]
                    elif fmt == "f32":
                        import struct

                        result["data"] = struct.unpack(">f", data[:4])[0]
                    elif fmt == "string":
                        result["data"] = data.split(b"\0", 1)[0].decode("utf-8", errors="replace")
                    else:
                        raise ValueError(f"Unknown read format: {fmt}")
                    result["success"] = True
                else:
                    result["error"] = self.dbg.last_error or "Read failed"

            elif action == "write":
                addr = cmd.get("address")
                value = cmd.get("value")
                fmt = cmd.get("format", "u32")

                if isinstance(addr, str):
                    resolved = self.dbg.resolve_address(addr)
                    if resolved is None:
                        result["error"] = f"Cannot resolve address: {addr}"
                        return result
                    addr = resolved

                if fmt == "f32":
                    result["success"] = self.dbg.write_f32(addr, float(value))
                else:
                    result["success"] = self.dbg.write_u32(addr, int(value))

            elif action == "break":
                addr = cmd.get("address")
                remove = cmd.get("remove", False)

                if isinstance(addr, str):
                    symbol = addr
                    resolved = self.dbg.resolve_address(addr)
                    if resolved is None:
                        result["error"] = f"Cannot resolve address: {addr}"
                        return result
                    addr = resolved
                else:
                    symbol = self.dbg.get_symbol_at(addr)

                if remove:
                    result["success"] = self.dbg.remove_breakpoint(addr)
                else:
                    result["success"] = self.dbg.set_breakpoint(addr, symbol)
                    if result["success"]:
                        result["data"] = {"address": addr, "symbol": symbol}

            elif action == "watch":
                addr = cmd.get("address")
                size = cmd.get("size", 4)
                write = cmd.get("write", True)
                read = cmd.get("read", False)

                if isinstance(addr, str):
                    resolved = self.dbg.resolve_address(addr)
                    if resolved is None:
                        result["error"] = f"Cannot resolve address: {addr}"
                        return result
                    addr = resolved

                result["success"] = self.dbg.set_watchpoint(addr, size, write, read)

            elif action in ("continue", "step", "halt"):
                timeout = cmd.get("timeout", 60.0 if action == "continue" else 5.0)
                if (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float))
                    or not math.isfinite(timeout)
                    or timeout <= 0
                    or timeout > 300
                ):
                    raise ValueError("timeout must be a positive finite number no greater than 300")
                if action == "step":
                    count = cmd.get("count", 1)
                    if type(count) is not int or not 1 <= count <= 10000:
                        raise ValueError("step count must be an integer from 1 to 10000")
                    completed, stop = 0, None
                    deadline = time.monotonic() + timeout
                    for _ in range(count):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        reply = self.dbg.step(timeout=remaining)
                        if reply is None:
                            break
                        completed += 1
                        stop = reply
                    result["data"] = {"requested": count, "completed": completed, "stop": stop}
                    result["success"] = completed == count
                elif action == "continue":
                    result["data"] = self.dbg.continue_execution(timeout=timeout)
                    result["success"] = result["data"] is not None
                else:
                    result["success"] = self.dbg.halt(timeout=timeout)
                result["execution_state"] = self.dbg.execution_state
                result["execution"] = self.dbg.last_execution
                if not result["success"]:
                    result["error"] = self.dbg.last_error or "Execution deadline reached; no further stop confirmed"

            elif action == "resume":
                previous = self.dbg.last_execution.get("run")
                stop = self.dbg.continue_execution(timeout=0.05)
                started = self.dbg.last_execution.get("run") != previous
                result["success"] = started and self.dbg.execution_state in ("running", "stopped")
                result["data"] = {
                    "request_issued": started,
                    "execution_state": self.dbg.execution_state,
                    "stop": stop,
                    "stop_confirmed": stop is not None,
                }
                if not result["success"]:
                    result["error"] = self.dbg.last_error

            elif action in ("input", "capture"):
                neutral = action == "input" and cmd.get("request", {}).get("operation") in ("release", "release-all")
                if self.dbg.execution_state != "running" and not neutral:
                    raise RuntimeError(
                        "Input/capture require running execution; explicitly resume this session first (release/release-all also work while stopped)"
                    )
                if action == "input":
                    if self.controller is None:
                        raise RuntimeError("This session has no controller pipe")
                    result["data"] = self.controller.request(**cmd.get("request", {}))
                else:
                    if self.capturer is None:
                        raise RuntimeError("This session has no native capture channel")
                    options = cmd.get("options", {})
                    allowed = {
                        "timeout",
                        "attempts",
                        "dwell",
                        "release_dwell",
                        "settle",
                        "brightness_threshold",
                        "visible_fraction",
                    }
                    if not isinstance(options, dict) or set(options) - allowed:
                        raise ValueError("Unsupported capture option; executable predicates are library-only")
                    result["data"] = self.capturer.capture(**options)
                result["success"] = True

            elif action == "regs":
                regs = self.dbg.read_registers()
                if regs:
                    pc = self.dbg.read_pc()
                    if pc is None:
                        raise RuntimeError(self.dbg.last_error or "Failed to read PC")
                    result["data"] = {**regs, "pc": pc}
                    result["success"] = True
                else:
                    result["error"] = self.dbg.last_error or "Failed to read registers"

            elif action == "symbol":
                pattern = cmd.get("pattern", "")
                matches = []
                for name, sym in self.dbg.symbols.items():
                    if pattern.lower() in name.lower():
                        matches.append({"name": name, "address": sym.address})
                        if len(matches) >= 50:
                            break
                result["data"] = matches
                result["success"] = True

            elif action == "resolve":
                addr = cmd.get("address")
                resolved = self.dbg.resolve_address(addr)
                if resolved is not None:
                    result["data"] = resolved
                    result["success"] = True
                else:
                    result["error"] = f"Cannot resolve: {addr}"

            else:
                result["error"] = f"Unknown action: {action}"

        except Exception as e:
            result["error"] = str(e)

        return result

    def handle_client(self, conn: socket.socket):
        """One bounded request per private session connection."""
        try:
            conn.settimeout(5)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    raise ValueError("Incomplete RPC request")
                data += chunk
                if len(data) > 65536:
                    raise ValueError("RPC request too large")
            cmd = json.loads(data.split(b"\n", 1)[0])
            if not isinstance(cmd, dict) or cmd.pop("session_id", None) != self.metadata.get("session_id"):
                raise ValueError("Session identity mismatch")
            result = self.handle_command(cmd)
            conn.sendall(json.dumps(result).encode() + b"\n")
            if cmd.get("action") == "stop":
                self.running = False  # acknowledge before teardown
        except Exception as exc:
            try:
                conn.sendall(json.dumps({"success": False, "error": str(exc)}).encode() + b"\n")
            except OSError:
                pass
        finally:
            conn.close()

    def _record(self, status, **extra):
        self.metadata.update(status=status, **extra)
        destination = self.session / "session.json"
        temporary = self.session / "session.json.tmp"
        if destination.is_symlink() or temporary.exists() or temporary.is_symlink():
            raise ValueError("Unsafe session metadata path")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(self.metadata, out, indent=2)
            out.write("\n")
        temporary.replace(destination)

    def start(
        self,
        iso_path=None,
        dolphin_path=None,
        session=None,
        profile=None,
        port=0,
        interpreter=False,
        symbols=None,
        timeout=30,
    ):
        """Foreground owner of one process and its only accepted GDB connection."""
        timeout = bounded(timeout, "launch timeout", 0.1, 300)
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer from 0 to 65535")
        proposed = Path(session).expanduser() if session else Path("/tmp") / f"dolphin-{uuid.uuid4().hex[:12]}"
        if proposed.exists() or proposed.is_symlink():
            raise ValueError(f"Refusing existing session: {proposed}")
        proposed = proposed.resolve()
        if len(os.fsencode(str(proposed / "daemon.sock"))) > 100:
            raise ValueError("Session socket path too long; use a short directory under /tmp")
        proposed.mkdir(mode=0o700)
        self.session = checked_directory(proposed)
        endpoint = self.session / "daemon.sock"
        self.metadata = {
            "schema": 1,
            "session_id": uuid.uuid4().hex,
            "created_at": time.time(),
            "endpoint": str(endpoint),
            "tool_module": str(Path(__file__).resolve()),
            "tool_python": sys.executable,
        }
        print(f"Session: {self.session} (foreground owner; keep this command running)", flush=True)
        previous_signals = {}
        log = None
        failed = False
        try:
            if threading.current_thread() is threading.main_thread():

                def shutdown(signum, frame):
                    self.running = False
                    self.metadata["shutdown_signal"] = signum
                    if not self._closing:
                        raise KeyboardInterrupt

                for number in (signal.SIGINT, signal.SIGTERM):
                    previous_signals[number] = signal.signal(number, shutdown)
            self._record("starting")
            self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server_socket.bind(str(endpoint))
            self._bound = True
            info = endpoint.lstat()
            self._endpoint_identity = (info.st_dev, info.st_ino)
            self.server_socket.listen(8)
            self.server_socket.settimeout(0.2)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
                port = probe.getsockname()[1]
            owned_profile = Path(profile).expanduser() if profile else self.session / "profile"
            if owned_profile.is_symlink() or owned_profile.resolve() == DolphinLauncher.DEFAULT_CONFIG_DIR.resolve():
                raise ValueError("Explicit profile must be isolated, never the normal Dolphin profile")
            if owned_profile.exists():
                raise ValueError("Explicit isolated profile must be a new directory")
            owned_profile.mkdir(mode=0o700)
            owned_profile = checked_directory(owned_profile)
            prepare_profile(owned_profile, port, interpreter)
            self.launcher = DolphinLauncher(dolphin_path=dolphin_path, config_dir=owned_profile, gdb_port=port)
            self.launcher.retain_config = True
            log = (self.session / "dolphin.log").open("xb")
            self.launcher.log_file = log
            selected_symbols = symbols_path(symbols)
            self.metadata.update(
                profile=str(owned_profile),
                iso=str(Path(iso_path).expanduser().resolve()),
                binary=str(Path(self.launcher.dolphin_binary).resolve()),
                gdb_port=port,
                interpreter=interpreter,
                symbols_path=str(selected_symbols),
                symbols_available=selected_symbols.is_file(),
            )
            self.metadata.update(
                emulator_version=self.launcher.version(),
                config_sha256={
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((owned_profile / "Config").glob("*.ini"))
                },
            )
            self._record("starting")
            self.running = True
            readiness_deadline = time.monotonic() + timeout
            if not self.launcher.launch(str(Path(iso_path).expanduser().resolve())):
                raise RuntimeError("Dolphin launch failed; inspect session dolphin.log")
            self._record("connecting", emulator_pid=self.launcher.process.pid, launch_argv=self.launcher.launch_argv)
            self.dbg = self.launcher.wait_for_gdb_ready(max(0.001, readiness_deadline - time.monotonic()))
            self.game_id = self.dbg.get_game_id()
            if selected_symbols.is_file():
                self.dbg.load_symbols(selected_symbols)

            def alive():
                return self.running and self.launcher.is_running()

            self.pad_channel = PipeChannel(owned_profile / "Pipes/pad", alive)
            self.capture_channel = PipeChannel(owned_profile / "Pipes/capture", alive)
            self.pad_channel.open(max(0.001, readiness_deadline - time.monotonic()))
            self.capture_channel.open(max(0.001, readiness_deadline - time.monotonic()))
            self.controller = Controller(self.pad_channel)
            self.controller.reset()
            self.capture_channel.write("RELEASE X")
            self.capturer = NativeCapture(self.capture_channel, owned_profile / "ScreenShots", alive, self.metadata)
            self._record("ready", game_id=self.game_id)
            print(
                f"Ready: initial halt confirmed; game={self.game_id}; symbols={len(self.dbg.symbols)}; port={port}",
                flush=True,
            )
            while self.running:
                if not self.launcher.is_running():
                    raise RuntimeError("Owned Dolphin exited")
                try:
                    conn, _ = self.server_socket.accept()
                except TimeoutError:
                    continue
                thread = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                self._threads = [t for t in self._threads if t.is_alive()]
                self._threads.append(thread)
                thread.start()
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            failed = True
            self.metadata["error"] = str(exc)
            print(f"Error: {exc}", flush=True)
        finally:
            self._closing = True
            self.running = False
            if self.server_socket:
                self.server_socket.close()
            # Active capture notices running=False; bounded input tap has a 30s cap.
            for thread in self._threads:
                thread.join(timeout=0.5)
            for channel in (self.pad_channel, self.capture_channel):
                if channel is not None:
                    # Best-effort reset while the owned reader is still alive.
                    channel.alive = lambda: self.launcher.is_running()
            try:
                if self.controller:
                    self.controller.reset()
                if self.capture_channel and self.capture_channel.fd is not None:
                    self.capture_channel.write("RELEASE X", timeout=0.1)
            except (OSError, RuntimeError, TimeoutError):
                pass
            finally:
                for channel in (self.pad_channel, self.capture_channel):
                    if channel:
                        channel.close()
                if self.launcher:
                    self.launcher.cleanup()
                if log:
                    log.close()
                if self._bound:
                    try:
                        info = endpoint.lstat()
                        if (info.st_dev, info.st_ino) == self._endpoint_identity and stat.S_ISSOCK(info.st_mode):
                            endpoint.unlink()
                        else:
                            failed = True
                            self.metadata["error"] = "Owned endpoint path was substituted; replacement left untouched"
                    except FileNotFoundError:
                        pass
                for number, handler in previous_signals.items():
                    signal.signal(number, handler)
                self._record("failed" if failed else "stopped", finished_at=time.time())
        return 1 if failed else 0


def send_command(cmd: dict, timeout: float = 60.0, session=None) -> dict:
    """Explicit session RPC; never attach or signal a recorded emulator PID."""
    if session is None:
        raise ValueError("An explicit --session directory is required")
    root, metadata = read_session(session)
    endpoint = root / "daemon.sock"
    info = endpoint.lstat()
    if not stat.S_ISSOCK(info.st_mode):
        raise ValueError("Session endpoint is not a socket")
    cmd = dict(cmd, session_id=metadata["session_id"])
    requested = cmd.get("timeout", cmd.get("options", {}).get("timeout", timeout))
    rpc_timeout = max(bounded(timeout, "RPC timeout", 0.1, 300), bounded(requested, "request timeout", 0.001, 300)) + 2
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(rpc_timeout)
        sock.connect(str(endpoint))
        sock.sendall(json.dumps(cmd).encode() + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                raise RuntimeError("Session closed without an RPC response")
            data += chunk
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("RPC response too large")
        return json.loads(data.split(b"\n", 1)[0])


def is_running(session=None) -> bool:
    if session is None:
        return False
    try:
        return send_command({"action": "status"}, timeout=1, session=session).get("success", False)
    except (OSError, ValueError, RuntimeError):
        return False


def stop_daemon(session=None):
    try:
        result = send_command({"action": "stop"}, session=session)
        print(json.dumps(result))
        return 0 if result.get("success") else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Session unavailable: {exc}")
        return 1
