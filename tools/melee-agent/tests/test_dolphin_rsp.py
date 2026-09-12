"""Protocol peers test stream ownership without Dolphin or a game image."""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.dolphin_debug.daemon import DebugDaemon
from src.dolphin_debug.debugger import DolphinDebugger
from src.dolphin_debug.rsp_client import GDBClient


def frame(payload):
    return GDBClient._frame(payload)


def receive(sock):
    data = b""
    while not data.endswith(b"\x03"):
        data += sock.recv(1)
        if data.startswith(b"$") and b"#" in data and len(data.split(b"#")[1]) == 2:
            return data
    return data


def fence(server):
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p40")
    server.sendall(b"+" + frame("8000522c"))


@pytest.fixture
def peer():
    client, server = socket.socketpair()
    server.settimeout(1)
    gdb = GDBClient()
    gdb._attach(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        yield gdb, server, pool
        gdb.disconnect()
        server.close()
    gdb._reader.join(1)
    assert not gdb._reader.is_alive()


@pytest.mark.parametrize("split", range(1, len(frame("8000522c")) + 1))
def test_fragmented_packet(peer, split):
    gdb, server, pool = peer
    result = pool.submit(gdb._command, "p40")
    assert receive(server) == frame("p40")
    packet = b"+" + frame("8000522c")
    server.sendall(packet[:split])
    server.sendall(packet[split:])
    assert result.result(1) == "8000522c"
    assert server.recv(1) == b"+"


@pytest.mark.parametrize("packet", [b"$OK#00", b"$OK#zz", b"$OK#9", b"$abc", b"$a}b#20"])
def test_corrupt_or_truncated_reply_fails_closed(peer, packet):
    gdb, server, pool = peer
    result = pool.submit(gdb._command, "qAttached", 0.1)
    receive(server)
    server.sendall(packet)
    server.shutdown(socket.SHUT_WR)
    assert result.result(1) is None
    assert not gdb.is_connected
    assert server.recv(1) == b""


def test_size_and_overall_deadline(peer):
    gdb, server, pool = peer
    gdb.MAX_PACKET = 4
    result = pool.submit(gdb._command, "qAttached", 0.1)
    receive(server)
    server.sendall(b"$12345")
    assert result.result(1) is None
    assert "size" in gdb.last_error


def test_trickle_cannot_extend_transaction_deadline(peer):
    gdb, server, pool = peer
    result = pool.submit(gdb._command, "qAttached", 0.05)
    receive(server)
    started = time.monotonic()
    server.sendall(b"$")
    while not result.done():
        try:
            server.sendall(b"a")
        except OSError:
            break
        threading.Event().wait(0.005)
    assert result.result(1) is None
    assert time.monotonic() - started < 0.5
    assert not gdb.is_connected


def test_nak_replays_but_timeout_does_not(peer):
    gdb, server, pool = peer
    result = pool.submit(gdb._command, "M80000000,1:ff", 0.1)
    command = receive(server)
    server.sendall(b"-")
    assert receive(server) == command
    server.sendall(b"+" + frame("OK"))
    assert result.result(1) == "OK"
    assert server.recv(1) == b"+"
    result = pool.submit(gdb._command, "M80000000,1:00", 0.05)
    assert receive(server) == frame("M80000000,1:00")
    assert result.result(1) is None
    assert server.recv(1024) == b""


@pytest.mark.parametrize(
    "reply", ["S05", "T0540:8000522c;01:817ffff0;", "", "OK", "E01", "T05oops", "S0z", "W00", "X09"]
)
def test_step_requires_valid_stop(peer, reply):
    gdb, server, pool = peer
    result = pool.submit(gdb.step, 0.2)
    assert receive(server) == frame("s")
    server.sendall(b"+" + frame(reply))
    expected = reply if reply.startswith(("S05", "T0540:")) else None
    assert result.result(1) == expected
    assert (gdb.state == "stopped") == (expected is not None)
    assert server.recv(1) == b"+"


def test_continue_and_halt_share_stop_and_preserve_next_reply(peer):
    gdb, server, pool = peer
    run = pool.submit(gdb.continue_execution, 0.5)
    assert receive(server) == frame("c")
    server.sendall(b"+")
    assert gdb.read_memory(0x80000000, 1) is None
    assert "Busy" in gdb.last_error
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("T0540:8000522c;"))
    fence(server)
    assert run.result(1) == "T0540:8000522c;"
    assert halt.result(1)
    assert server.recv(1) == b"+"
    read = pool.submit(gdb._command, "p40")
    assert receive(server) == frame("p40")
    server.sendall(b"+" + frame("8000522c"))
    assert read.result(1) == "8000522c"


def test_timeout_then_halt_recovers_same_run(peer):
    gdb, server, pool = peer
    run = pool.submit(gdb.continue_execution, 0.03)
    assert receive(server) == frame("c")
    server.sendall(b"+")
    assert run.result(1) is None
    assert gdb.state == "running"
    assert gdb.is_connected
    identity = gdb.last_execution["run"]
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("S05"))
    fence(server)
    assert halt.result(1)
    assert gdb.last_execution["run"] == identity
    assert server.recv(1) == b"+"
    assert gdb.halt()
    assert gdb.last_execution["already_stopped"]
    read = pool.submit(gdb.read_memory, 0x80000000, 1)
    assert receive(server) == frame("m80000000,1")
    server.sendall(b"+" + frame("ff"))
    assert read.result(1) == b"\xff"


def test_idle_halt_and_concurrent_reads(peer):
    gdb, server, pool = peer
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("S05"))
    fence(server)
    assert halt.result(1)
    assert server.recv(1) == b"+"
    a = pool.submit(gdb._command, "p40")
    assert receive(server) == frame("p40")
    b = pool.submit(gdb._command, "p01")
    server.sendall(b"+" + frame("80000000"))
    assert a.result(1) == "80000000"
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p01")
    server.sendall(b"+" + frame("817ffff0"))
    assert b.result(1) == "817ffff0"


def test_disconnect_releases_execution_and_halt(peer):
    gdb, server, pool = peer
    run = pool.submit(gdb.continue_execution, 1)
    receive(server)
    halt = pool.submit(gdb.halt, 1)
    assert receive(server) == b"\x03"
    server.shutdown(socket.SHUT_WR)
    assert run.result(1) is None
    assert not halt.result(1)
    assert not gdb.is_connected
    gdb.disconnect()
    gdb.disconnect()


def test_connect_needs_no_initial_ack():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = GDBClient("127.0.0.1", listener.getsockname()[1])
    assert client.connect(0.1)
    server, _ = listener.accept()
    original = client.sock
    assert client.connect(0.1)
    assert client.sock is original
    with ThreadPoolExecutor() as pool:
        result = pool.submit(client.query_attached)
        assert receive(server) == frame("qAttached")
        server.sendall(b"+" + frame("1"))
        assert result.result(1) == "1"
    client.disconnect()
    server.close()
    listener.close()


def test_daemon_partial_steps_and_status(peer):
    gdb, server, pool = peer
    debugger = DolphinDebugger()
    debugger._gdb = gdb
    daemon = DebugDaemon()
    daemon.dbg = debugger
    for count in [0, -1, True, 1.5, 10001]:
        assert not daemon.handle_command({"action": "step", "count": count})["success"]
    result = pool.submit(daemon.handle_command, {"action": "step", "count": 3, "timeout": 0.5})
    assert receive(server) == frame("s")
    assert daemon.handle_command({"action": "status"})["data"]["execution_state"] == "running"
    server.sendall(b"+" + frame("S05"))
    assert server.recv(1) == b"+"
    assert receive(server) == frame("s")
    server.sendall(b"+" + frame("E01"))
    reply = result.result(1)
    assert not reply["success"]
    assert reply["data"] == {"requested": 3, "completed": 1, "stop": "S05"}
    assert server.recv(1) == b"+"
    server.settimeout(0.02)
    with pytest.raises(socket.timeout):
        server.recv(1)


@pytest.mark.parametrize("method,reply", [("read_registers", "00" * 31 * 4), ("read_pc", "8000"), ("read_u32", "ff")])
def test_debugger_rejects_short_reads(peer, method, reply):
    gdb, server, pool = peer
    debugger = DolphinDebugger()
    debugger._gdb = gdb
    args = [0x80000000] if method == "read_u32" else []
    result = pool.submit(getattr(debugger, method), *args)
    receive(server)
    server.sendall(b"+" + frame(reply))
    assert result.result(1) is None


def test_late_stop_does_not_satisfy_next_execution(peer):
    gdb, server, pool = peer
    old = pool.submit(gdb.continue_execution, 0.02)
    assert receive(server) == frame("c")
    assert old.result(1) is None
    server.sendall(b"+" + frame("S05"))
    assert server.recv(1) == b"+"
    # Synchronize on delivery (ACK is written before metadata is published).
    with gdb._condition:
        assert gdb.state == "stopped"
    new = pool.submit(gdb.step, 0.3)
    assert receive(server) == frame("s")
    assert not new.done()
    server.sendall(b"+" + frame("T0540:80000004;"))
    assert new.result(1) == "T0540:80000004;"
    assert gdb.last_execution["run"] == 2


def test_replaced_socket_reader_cannot_deliver_to_new_session():
    original, old_peer = socket.socketpair()
    replacement, new_peer = socket.socketpair()
    entered, release = threading.Event(), threading.Event()

    class DelayedSocket:
        def settimeout(self, value):
            original.settimeout(value)

        def recv(self, size):
            data = original.recv(size)
            entered.set()
            assert release.wait(1)
            return data

        def shutdown(self, how):
            original.shutdown(how)

        def close(self):
            original.close()

    client = GDBClient()
    client._attach(DelayedSocket())
    old_reader = client._reader
    old_peer.sendall(frame("S05"))
    assert entered.wait(1)
    client.disconnect()
    client._attach(replacement)
    with ThreadPoolExecutor() as pool:
        query = pool.submit(client._command, "p40")
        assert receive(new_peer) == frame("p40")
        release.set()
        old_reader.join(1)
        assert not old_reader.is_alive()
        assert not query.done()
        new_peer.sendall(b"+" + frame("80000000"))
        assert query.result(1) == "80000000"
    client.disconnect()
    old_peer.close()
    new_peer.close()


@pytest.mark.parametrize("action,reply", [("cmd_step", "OK"), ("cmd_continue", "E01"), ("cmd_continue", None)])
def test_direct_cli_failure_is_nonzero(peer, monkeypatch, capsys, action, reply):
    from src.dolphin_debug.cli import MeleeDebugCLI

    gdb, server, pool = peer
    cli = MeleeDebugCLI()
    cli.dbg._gdb = gdb
    monkeypatch.setattr(cli, "_use_daemon", lambda: False)
    monkeypatch.setattr(cli, "_ensure_connected", lambda: True)
    original = gdb.continue_execution
    monkeypatch.setattr(gdb, "continue_execution", lambda timeout=60: original(0.02))
    result = pool.submit(getattr(cli, action))
    receive(server)
    if reply is not None:
        server.sendall(b"+" + frame(reply))
    assert result.result(1) == 1
    output = capsys.readouterr().out
    assert "Stopped: None" not in output
    assert "Stepped" not in output


@pytest.mark.parametrize("delayed", [False, True])
def test_interrupt_empty_trailer_cannot_steal_register_reply(peer, delayed):
    gdb, server, pool = peer
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("S05") + (b"" if delayed else frame("")))
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p40")
    if not delayed:
        assert server.recv(1) == b"+"
    server.sendall((frame("") if delayed else b"") + b"+" + frame("80000000"))
    assert halt.result(1)
    assert server.recv(1) == b"+"
    if delayed:
        assert server.recv(1) == b"+"
    read = pool.submit(gdb._command, "p40")
    assert receive(server) == frame("p40")
    server.sendall(b"+" + frame("80000000"))
    assert read.result(1) == "80000000"
    assert gdb.is_connected


def test_ack_closes_interrupt_trailer_window(peer):
    gdb, server, pool = peer
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("S05"))
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p40")
    server.sendall(b"+" + frame(""))
    assert not halt.result(1)
    assert gdb.state != "stopped"


def test_double_interrupt_stop_fenced_before_new_step(peer):
    gdb, server, pool = peer
    run = pool.submit(gdb.continue_execution, 0.5)
    assert receive(server) == frame("c")
    server.sendall(b"+")
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("T0540:8034ca84;") + frame(""))
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p40")
    assert server.recv(1) == b"+"
    assert gdb.step(0.01) is None
    assert not halt.done()
    server.sendall(frame("T0540:8034ca7c;") + b"+" + frame("8034ca7c"))
    assert halt.result(1)
    assert run.result(1) == "T0540:8034ca7c;"
    assert gdb.last_execution["pc"] == 0x8034CA7C
    assert server.recv(1) == b"+"
    assert server.recv(1) == b"+"
    step = pool.submit(gdb.step, 0.5)
    assert receive(server) == frame("s")
    assert not step.done()
    server.sendall(b"+" + frame("T0540:8034ca80;"))
    assert step.result(1) == "T0540:8034ca80;"


def test_failed_connect_closes_socket(monkeypatch):
    class Refused:
        closed = False

        def settimeout(self, value):
            pass

        def connect(self, address):
            raise ConnectionRefusedError("test refusal")

        def close(self):
            self.closed = True

    sock = Refused()
    monkeypatch.setattr("src.dolphin_debug.rsp_client.socket.socket", lambda *args: sock)
    client = GDBClient()
    assert not client.connect(0.01)
    assert sock.closed
    assert not client.is_connected


def test_nak_retries_are_bounded(peer):
    gdb, server, pool = peer
    result = pool.submit(gdb.step, 0.5)
    for _ in range(3):
        assert receive(server) == frame("s")
        server.sendall(b"-")
    assert result.result(1) is None
    assert not gdb.is_connected
    assert "NAK" in gdb.last_error


def test_query_stop_reply_does_not_confirm_halted(peer):
    gdb, server, pool = peer
    result = pool.submit(gdb.get_stop_reason)
    assert receive(server) == frame("?")
    server.sendall(b"+" + frame("S0f"))
    assert result.result(1) == "S0f"
    assert gdb.state == "unknown"


def test_queued_read_has_bounded_wait_without_disrupting_owner(peer):
    gdb, server, pool = peer
    first = pool.submit(gdb._command, "p40", 0.5)
    assert receive(server) == frame("p40")
    assert gdb._command("p01", 0.01) is None
    assert gdb.is_connected
    server.sendall(b"+" + frame("80000000"))
    assert first.result(1) == "80000000"


def test_interrupt_fence_deadline_fails_closed(peer):
    gdb, server, pool = peer
    gdb.FRAME_TIMEOUT = 0.03
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("S05"))
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p40")
    assert not halt.result(1)
    assert not gdb.is_connected
    assert "fence" in gdb.last_error


@pytest.mark.parametrize("traffic", [b"+", frame("T0540:8000522c;")], ids=["acks", "duplicate-stops"])
def test_interrupt_fence_deadline_survives_continuous_traffic(peer, traffic):
    gdb, server, pool = peer
    gdb.FRAME_TIMEOUT = 0.03
    halt = pool.submit(gdb.halt, 0.5)
    assert receive(server) == b"\x03"
    server.sendall(frame("S05"))
    assert server.recv(1) == b"+"
    assert receive(server) == frame("p40")
    started = time.monotonic()
    # No socket timeout can occur while these bytes arrive. A broken deadline
    # check accepts the late register reply and incorrectly reports success.
    while time.monotonic() - started < 0.12:
        try:
            server.sendall(traffic)
        except OSError:
            break
        threading.Event().wait(0.005)
    try:
        server.sendall(b"+" + frame("8000522c"))
    except OSError:
        pass
    assert not halt.result(1)
    assert not gdb.is_connected
    assert gdb.state == "disconnected"
    assert not gdb.last_execution.get("confirmed", False)
    assert "fence timed out" in gdb.last_error
