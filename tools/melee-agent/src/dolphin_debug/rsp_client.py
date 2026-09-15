"""Dolphin's ASCII GDB RSP client, with one connection-owned stream reader."""

import re
import socket
import struct
import threading
import time
from dataclasses import dataclass


@dataclass
class _Transaction:
    command: str
    execution: bool
    run: int = 0
    response: str | None = None
    error: str | None = None
    done: bool = False
    retries: int = 0
    interrupted: bool = False
    fencing: bool = False
    fence_deadline: float | None = None
    stop: dict | None = None


def parse_stop(payload):
    """Return validated signal/PC metadata; '?' replies are not state evidence."""
    if not re.fullmatch(r"[ST][0-9a-fA-F]{2}.*", payload):
        return None
    fields = payload[3:]
    if payload[0] == "S" and fields:
        return None
    pc = None
    if fields:
        if not fields.endswith(";"):
            return None
        for field in fields[:-1].split(";"):
            if not re.fullmatch(r"(?:[0-9a-fA-F]+|thread|core|watch|rwatch|awatch):[0-9a-fA-F]+", field):
                return None
            key, value = field.split(":")
            if key == "40":
                if len(value) != 8:
                    return None
                pc = int(value, 16)
    return {"raw": payload, "signal": int(payload[1:3], 16), "pc": pc}


class GDBClient:
    MAX_PACKET = 1024 * 1024
    FRAME_TIMEOUT = 5.0

    def __init__(self, host="localhost", port=9090):
        self.host, self.port = host, port
        self.sock = None
        self._condition = threading.Condition(threading.RLock())
        self._writer = threading.Lock()
        self._commands = threading.Lock()
        self._pending = None
        self._reader = None
        self._run = 0
        self._interrupt_trailer = False
        self.state = "disconnected"
        self.last_error = None
        self.last_execution = {}

    @property
    def is_connected(self):
        return self.sock is not None

    def connect(self, timeout=10.0):
        with self._condition:
            if self.sock is not None:
                return True
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(timeout)
                sock.connect((self.host, self.port))
            except OSError as exc:
                sock.close()
                self.last_error = f"Connection failed: {exc}"
                return False
            self._attach(sock)
            return True

    def _attach(self, sock):
        """Adopt a connected socket (also used by deterministic protocol tests)."""
        self.sock = sock
        sock.settimeout(0.05)
        self.state = "unknown"
        self._interrupt_trailer = False
        self.last_error = None
        self._reader = threading.Thread(target=self._read_loop, args=(sock,), daemon=True)
        self._reader.start()

    def disconnect(self, error="Disconnected; the isolated emulator may require restart"):
        with self._condition:
            sock, self.sock = self.sock, None
            self.state = "disconnected"
            self.last_error = error
            if self._pending:
                self._pending.error = error
                self._pending.done = True
                self._pending = None
            self._condition.notify_all()
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    @staticmethod
    def _frame(command):
        payload = command.encode("ascii")
        return b"$" + payload + b"#" + f"{sum(payload) % 256:02x}".encode()

    def _write(self, data):
        try:
            with self._writer:
                if self.sock is None:
                    raise OSError("Disconnected")
                self.sock.sendall(data)
            return True
        except OSError as exc:
            self.disconnect(f"Write failed: {exc}; the isolated emulator may require restart")
            return False

    def _check_fence_deadline(self):
        """Check under the connection condition, including while bytes arrive."""
        tx = self._pending
        if tx and tx.fence_deadline is not None and time.monotonic() >= tx.fence_deadline:
            raise ValueError("Interrupt register fence timed out")

    def _read_loop(self, sock):
        buffer = bytearray()
        frame_started = None
        try:
            while self.sock is sock:
                try:
                    chunk = sock.recv(4096)
                except TimeoutError:
                    with self._condition:
                        if self.sock is sock:
                            self._check_fence_deadline()
                    if frame_started and time.monotonic() - frame_started > self.FRAME_TIMEOUT:
                        raise ValueError("Incomplete packet deadline exceeded")
                    continue
                if not chunk:
                    raise ValueError("EOF during packet" if buffer else "EOF")
                with self._condition:
                    # A replaced socket must never ACK or satisfy the new session.
                    if self.sock is not sock:
                        return
                    buffer.extend(chunk)
                    while buffer:
                        self._check_fence_deadline()
                        if buffer[0] in b"+-":
                            ack = buffer.pop(0)
                            if ack == ord("+") and self._pending is not None:
                                self._interrupt_trailer = False
                            if ack == ord("-"):
                                with self._condition:
                                    tx = self._pending
                                    if tx is None or tx.retries >= 2:
                                        raise ValueError("Unexpected or repeated command NAK")
                                    tx.retries += 1
                                    self._write(self._frame(tx.command))
                            continue
                        if buffer[0] != ord("$"):
                            raise ValueError("Invalid packet prefix")
                        if frame_started is None:
                            frame_started = time.monotonic()
                        if time.monotonic() - frame_started > self.FRAME_TIMEOUT:
                            raise ValueError("Incomplete packet deadline exceeded")
                        end = buffer.find(b"#", 1)
                        if (end < 0 and len(buffer) > self.MAX_PACKET) or end > self.MAX_PACKET:
                            raise ValueError("Packet size limit exceeded")
                        if end < 0 or len(buffer) < end + 3:
                            break
                        payload = bytes(buffer[1:end])
                        checksum = bytes(buffer[end + 1 : end + 3])
                        if not re.fullmatch(b"[0-9a-fA-F]{2}", checksum) or sum(payload) % 256 != int(checksum, 16):
                            raise ValueError("Invalid packet checksum")
                        if any(c < 32 or c > 126 for c in payload) or any(c in payload for c in b"}*${"):
                            raise ValueError("Unsupported packet encoding")
                        del buffer[: end + 3]
                        frame_started = None
                        self._check_fence_deadline()
                        if not self._write(b"+"):
                            return
                        self._deliver(payload.decode("ascii"))
        except (OSError, ValueError) as exc:
            with self._condition:
                if self.sock is sock:
                    self.disconnect(f"Protocol failure: {exc}; the isolated emulator may require restart")

    def _deliver(self, payload):
        with self._condition:
            self._check_fence_deadline()
            tx = self._pending
            # Dolphin 2509 emits one empty packet after an interrupt stop.
            # Only accept that trailer before the next command ACK/reply, so
            # an empty response to an acknowledged command remains its response.
            if self._interrupt_trailer and payload == "":
                self._interrupt_trailer = False
                return
            self._interrupt_trailer = False
            if tx is None:
                # A validated unsolicited stop updates state, never a future command.
                stop = parse_stop(payload)
                if stop:
                    self.state = "stopped"
                    self.last_execution = {**stop, "run": self._run, "confirmed": True}
                    return
                raise ValueError("Unsolicited reply")
            if tx.execution:
                stop = parse_stop(payload)
                if tx.interrupted and stop:
                    # Some Dolphin builds report Ctrl-C from both the command
                    # and CPU threads. Fence the interrupt with a register read
                    # before releasing this run or permitting another command.
                    tx.stop = stop
                    self._interrupt_trailer = True
                    if not tx.fencing:
                        tx.fencing = True
                        tx.fence_deadline = time.monotonic() + self.FRAME_TIMEOUT
                        tx.command = "p40"
                        tx.retries = 0
                        self._write(self._frame("p40"))
                    return
                if tx.fencing:
                    if re.fullmatch(r"[0-9a-fA-F]{8}", payload):
                        stop = {**tx.stop, "pc": int(payload, 16), "fenced": True}
                        payload = tx.stop["raw"]
                    else:
                        stop = None
                if stop:
                    self.state = "stopped"
                    self.last_execution = {**stop, "run": tx.run, "confirmed": True}
                else:
                    tx.error = f"Execution did not return a valid stop: {payload!r}"
                    self.last_error = tx.error
                    self.state = "unknown"
                    self.last_execution = {"run": tx.run, "confirmed": False, "reply": payload}
            tx.response = payload
            tx.done = True
            self._pending = None
            self._condition.notify_all()

    def _wait(self, tx, timeout):
        deadline = time.monotonic() + timeout
        with self._condition:
            while not tx.done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.last_error = (
                        "Execution timeout; no stop confirmed"
                        if tx.execution
                        else "Command timeout; the isolated emulator may require restart"
                    )
                    if not tx.execution:
                        self.disconnect(self.last_error)
                    return None
                self._condition.wait(remaining)
            if tx.error:
                self.last_error = tx.error
                return None
            return tx.response

    def _command(self, cmd, timeout=5.0):
        if cmd in ("s", "c"):
            return self._execute(cmd, timeout)
        deadline = time.monotonic() + timeout
        with self._condition:
            if self._pending and self._pending.execution:
                self.last_error = "Busy: execution pending"
                return None
        if not self._commands.acquire(timeout=max(0, timeout)):
            self.last_error = "Busy: command queue deadline exceeded"
            return None
        try:
            with self._condition:
                if not self.sock:
                    self.last_error = "Disconnected"
                    return None
                if self._pending:
                    self.last_error = "Busy: execution pending"
                    return None
                if time.monotonic() >= deadline:
                    self.last_error = "Busy: command queue deadline exceeded"
                    return None
                tx = _Transaction(cmd, False)
                self._pending = tx
                self.last_error = None
                self._write(self._frame(cmd))
            return self._wait(tx, max(0, deadline - time.monotonic()))
        finally:
            self._commands.release()

    def _execute(self, cmd, timeout):
        with self._condition:
            if not self.sock or self._pending:
                self.last_error = "Busy: command pending" if self.sock else "Disconnected"
                return None
            self._run += 1
            tx = _Transaction(cmd, True, self._run)
            self._pending = tx
            self.state = "running"
            self.last_error = None
            self.last_execution = {"run": tx.run, "confirmed": False}
            self._write(self._frame(cmd))
        return self._wait(tx, timeout)

    def continue_execution(self, timeout=60.0):
        return self._execute("c", timeout)

    def step(self, timeout=5.0):
        return self._execute("s", timeout)

    def halt(self, timeout=5.0):
        with self._condition:
            if not self.sock:
                self.last_error = "Disconnected"
                return False
            if self.state == "stopped" and not self._pending:
                self.last_execution = {**self.last_execution, "already_stopped": True}
                self.last_error = None
                return True
            tx = self._pending
            if tx and not tx.execution:
                self.last_error = "Busy: command pending"
                return False
            if tx is None:
                self._run += 1
                tx = _Transaction("", True, self._run)
                self._pending = tx
                self.last_execution = {"run": tx.run, "confirmed": False}
            if not tx.interrupted:
                tx.interrupted = True
                self.last_error = None
                self._write(b"\x03")
        return self._wait(tx, timeout) is not None

    # High-level commands

    def read_memory(self, address: int, length: int) -> bytes | None:
        """
        Read memory from the target.

        Args:
            address: Memory address (GameCube addresses start at 0x80000000)
            length: Number of bytes to read

        Returns:
            Bytes read, or None on failure
        """
        # GDB protocol: m<addr>,<length>
        # Address is sent without the 0x prefix
        response = self._command(f"m{address:x},{length:x}")
        if response is None or response.startswith("E"):
            return None

        # Response is hex-encoded bytes
        try:
            data = bytes.fromhex(response)
            if len(response) != length * 2 or len(data) != length:
                self.last_error = "Invalid memory reply length"
                return None
            return data
        except ValueError:
            self.last_error = "Invalid memory hex response"
            return None

    def read_u32(self, address: int) -> int | None:
        """Read a 32-bit big-endian value (PowerPC native)."""
        data = self.read_memory(address, 4)
        if data is None:
            return None
        return struct.unpack(">I", data)[0]

    def read_u16(self, address: int) -> int | None:
        """Read a 16-bit big-endian value."""
        data = self.read_memory(address, 2)
        if data is None:
            return None
        return struct.unpack(">H", data)[0]

    def read_u8(self, address: int) -> int | None:
        """Read an 8-bit value."""
        data = self.read_memory(address, 1)
        if data is None:
            return None
        return data[0]

    def read_f32(self, address: int) -> float | None:
        """Read a 32-bit big-endian float."""
        data = self.read_memory(address, 4)
        if data is None:
            return None
        return struct.unpack(">f", data)[0]

    def write_memory(self, address: int, data: bytes) -> bool:
        """
        Write memory to the target.

        Args:
            address: Memory address
            data: Bytes to write

        Returns:
            True on success
        """
        # GDB protocol: M<addr>,<length>:<hex data>
        hex_data = data.hex()
        response = self._command(f"M{address:x},{len(data):x}:{hex_data}")
        return response == "OK"

    def write_u32(self, address: int, value: int) -> bool:
        """Write a 32-bit big-endian value."""
        return self.write_memory(address, struct.pack(">I", value))

    def read_registers(self) -> dict | None:
        """
        Read all CPU registers.

        Returns dict with keys: gpr (list of 32), fpr (list of 32),
        pc, msr, cr, lr, ctr, xer
        """
        response = self._command("g")
        if response is None or response.startswith("E"):
            return None

        try:
            data = bytes.fromhex(response)
        except ValueError:
            return None

        # PowerPC register layout from GDB (varies by stub implementation)
        # Typically: 32 GPRs (4 bytes each), then FPRs, then special registers
        # This may need adjustment based on Dolphin's actual layout
        if len(data) < 128:  # At minimum 32 GPRs
            return None

        regs = {}
        offset = 0

        # 32 General Purpose Registers (32-bit each)
        regs["gpr"] = []
        for i in range(32):
            val = struct.unpack(">I", data[offset : offset + 4])[0]
            regs["gpr"].append(val)
            offset += 4

        # The rest depends on the stub's register layout
        # For now, just store the remaining data
        regs["_raw_remaining"] = data[offset:]

        return regs

    def set_breakpoint(self, address: int, kind: int = 4) -> bool:
        """
        Set a software breakpoint.

        Args:
            address: Address to break at
            kind: Breakpoint kind (4 = 4-byte instruction for PowerPC)
        """
        response = self._command(f"Z0,{address:x},{kind}")
        return response == "OK"

    def remove_breakpoint(self, address: int, kind: int = 4) -> bool:
        """Remove a software breakpoint."""
        response = self._command(f"z0,{address:x},{kind}")
        return response == "OK"

    def set_watchpoint(self, address: int, length: int, write: bool = True, read: bool = False) -> bool:
        """
        Set a memory watchpoint.

        Args:
            address: Address to watch
            length: Size of region
            write: Break on write
            read: Break on read
        """
        if write and read:
            wp_type = "4"  # Access watchpoint
        elif write:
            wp_type = "2"  # Write watchpoint
        elif read:
            wp_type = "3"  # Read watchpoint
        else:
            return False

        response = self._command(f"Z{wp_type},{address:x},{length}")
        return response == "OK"

    def remove_watchpoint(self, address: int, length: int, write: bool = True, read: bool = False) -> bool:
        """Remove a memory watchpoint."""
        if write and read:
            wp_type = "4"
        elif write:
            wp_type = "2"
        elif read:
            wp_type = "3"
        else:
            return False

        response = self._command(f"z{wp_type},{address:x},{length}")
        return response == "OK"

    def kill(self) -> bool:
        """Kill the target process."""
        response = self._command("k")
        return response is not None

    def query_supported(self) -> str | None:
        """Query supported features."""
        return self._command("qSupported")

    def query_attached(self) -> str | None:
        """Query if attached to existing process."""
        return self._command("qAttached")

    def get_stop_reason(self) -> str | None:
        """Get the reason the target stopped."""
        return self._command("?")

    def detach(self) -> bool:
        """Detach from the target."""
        response = self._command("D")
        return response == "OK"
