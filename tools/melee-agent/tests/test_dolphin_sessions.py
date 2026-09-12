"""Owned process/session regression tests; no game ISO or DME attachment needed."""

import configparser
import errno
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.dolphin_debug import ConnectionMode, DolphinDebugger, cli, daemon
from src.dolphin_debug.input_capture import Controller, NativeCapture, PipeChannel
from src.dolphin_debug.launcher import DolphinLauncher


@pytest.fixture
def short_root():
    with tempfile.TemporaryDirectory(prefix="md-test-", dir="/tmp") as directory:
        yield Path(directory)


class FakeDebugger:
    connections = []

    def __init__(self, **kwargs):
        assert kwargs["mode"] == ConnectionMode.GDB
        self.options = kwargs
        self.is_connected = False
        self.has_gdb = True
        self.has_memory_engine = False
        self.execution_state = "unknown"
        self.last_execution = {}
        self.last_error = None
        self.symbols = {}
        self.breakpoints = {}
        self.connect_calls = 0

    def connect(self, timeout):
        self.connect_calls += 1
        self.connections.append(self)
        self.is_connected = True
        return True

    def halt(self, timeout):
        self.execution_state = "stopped"
        return True

    def disconnect(self):
        self.is_connected = False

    def get_game_id(self):
        return "GALE01"

    def load_symbols(self, path):
        self.symbols["test_symbol"] = object()

    def resolve_address(self, addr):
        return 0x80000000 if addr == "test_symbol" else int(addr, 0)

    def read_bytes(self, addr, count):
        return b"hello\0world"[:count]

    def step(self, timeout):
        return "S05"


@pytest.fixture
def fake_launch(short_root, monkeypatch):
    binary, iso = short_root / "Dolphin", short_root / "game.iso"
    binary.touch()
    iso.touch()
    processes = []

    class Process:
        pid = 12345

        def __init__(self, command, **kwargs):
            assert "--user" in command and "--exec" in command
            assert kwargs["stdout"] != subprocess.PIPE
            assert kwargs["stderr"] != subprocess.PIPE
            self.command = command
            self.running = True
            self.reaped = False
            self.terminated = False
            self.readers = []
            profile = Path(command[command.index("--user") + 1])
            for name in ("pad", "capture"):
                self.readers.append(os.open(profile / "Pipes" / name, os.O_RDONLY | os.O_NONBLOCK))
            processes.append(self)

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

        def wait(self, timeout=None):
            self.reaped = True
            self.running = False
            for fd in self.readers:
                os.close(fd)
            self.readers.clear()
            return 0

        def kill(self):
            self.running = False

    monkeypatch.setattr(DolphinLauncher, "version", lambda self: "fake Dolphin test binary")
    monkeypatch.setattr("src.dolphin_debug.launcher.subprocess.Popen", Process)
    monkeypatch.setattr("src.dolphin_debug.debugger.DolphinDebugger", FakeDebugger)
    return binary, iso, processes


def wait_ready(path, future):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if future.done():
            pytest.fail(f"Session exited early: {future.result()}")
        try:
            data = json.loads((path / "session.json").read_text())
            if data.get("status") == "ready":
                return data
        except (OSError, ValueError):
            pass
        time.sleep(0.01)
    pytest.fail("Session never became ready")


def test_two_foreground_sessions_have_private_connections_and_rpc_stop(short_root, fake_launch, monkeypatch):
    binary, iso, processes = fake_launch
    normal = short_root / "normal"
    normal.mkdir()
    (normal / "settings").write_bytes(b"user config")
    monkeypatch.setattr(DolphinLauncher, "DEFAULT_CONFIG_DIR", normal)
    services = [daemon.DebugDaemon(), daemon.DebugDaemon()]
    paths = [short_root / "a", short_root / "b"]
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(service.start, str(iso), str(binary), path, timeout=0.5)
            for service, path in zip(services, paths)
        ]
        try:
            records = [wait_ready(path, future) for path, future in zip(paths, futures)]
            assert records[0]["gdb_port"] != records[1]["gdb_port"]
            assert records[0]["endpoint"] != records[1]["endpoint"]
            for path, service in zip(paths, services):
                assert (
                    daemon.send_command(
                        {"action": "read", "address": "test_symbol", "count": 11, "format": "string"}, session=path
                    )["data"]
                    == "hello"
                )
                assert daemon.send_command({"action": "step", "count": 2}, session=path)["data"]["completed"] == 2
                assert service.dbg.connect_calls == 1
            assert not any(future.done() for future in futures)
            assert daemon.send_command({"action": "stop"}, session=paths[0])["success"]
            assert futures[0].result(3) == 0
            assert not futures[1].done()
            assert daemon.send_command({"action": "status"}, session=paths[1])["success"]
            process_a = next(p for p in processes if str(paths[0].resolve() / "profile") in p.command)
            process_b = next(p for p in processes if str(paths[1].resolve() / "profile") in p.command)
            assert process_a.reaped and process_a.terminated
            assert not process_b.reaped
            assert not (paths[0] / "daemon.sock").exists()
            assert json.loads((paths[0] / "session.json").read_text())["status"] == "stopped"
            assert (paths[0] / "profile/Config/Dolphin.ini").exists()
            assert (normal / "settings").read_bytes() == b"user config"
        finally:
            for path, future, service in zip(paths, futures, services):
                if not future.done():
                    service.running = False
            for future in futures:
                future.result(5)


def test_launch_failures_reap_and_retain_evidence(short_root, fake_launch, monkeypatch):
    binary, iso, processes = fake_launch
    monkeypatch.setattr(FakeDebugger, "connect", lambda *args, **kwargs: False)
    service = daemon.DebugDaemon()
    path = short_root / "failed"
    assert service.start(str(iso), str(binary), path, timeout=0.1) == 1
    assert processes[0].reaped and processes[0].terminated
    assert not (path / "daemon.sock").exists()
    assert json.loads((path / "session.json").read_text())["status"] == "failed"
    assert (path / "dolphin.log").exists()


def test_existing_session_and_normal_profile_refused(short_root, fake_launch, monkeypatch):
    binary, iso, processes = fake_launch
    existing = short_root / "existing"
    existing.mkdir()
    marker = existing / "daemon.sock"
    marker.write_text("do not unlink")
    with pytest.raises(ValueError, match="existing session"):
        daemon.DebugDaemon().start(str(iso), str(binary), existing)
    assert marker.read_text() == "do not unlink"
    normal = short_root / "normal"
    normal.mkdir()
    monkeypatch.setattr(DolphinLauncher, "DEFAULT_CONFIG_DIR", normal)
    assert daemon.DebugDaemon().start(str(iso), str(binary), short_root / "refused", profile=normal) == 1
    link = short_root / "link"
    link.symlink_to(normal, target_is_directory=True)
    with pytest.raises(ValueError, match="isolated profile"):
        DolphinLauncher(config_dir=link)
    assert processes == []


def test_stale_metadata_never_signals_pid(short_root, monkeypatch):
    path = short_root / "stale"
    path.mkdir(mode=0o700)
    (path / "session.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "session_id": "stale",
                "emulator_pid": os.getpid(),
                "endpoint": str(path.resolve() / "daemon.sock"),
            }
        )
    )
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("stale PID signaled"))
    assert daemon.stop_daemon(path) == 1
    assert not daemon.is_running(path)
    (path / "session.json").write_text("{}")
    assert daemon.stop_daemon(path) == 1


def test_socket_path_limit_and_symlink_preflight(short_root):
    with pytest.raises(ValueError, match="too long"):
        daemon.DebugDaemon().start("missing", session=short_root / ("x" * 100))
    symlink = short_root / "link"
    symlink.symlink_to(short_root)
    with pytest.raises(ValueError, match="existing session"):
        daemon.DebugDaemon().start("missing", session=symlink)


def test_profile_mapping_and_default_cpu(short_root):
    profile = short_root / "profile"
    profile.mkdir()
    daemon.prepare_profile(profile, 19192)
    config = configparser.ConfigParser()
    config.read(profile / "Config/Dolphin.ini")
    assert config.getint("General", "GDBPort") == 19192
    assert not config.has_option("Core", "CPUCore")
    assert config.getboolean("Input", "BackgroundInput")
    assert not config.getboolean("General", "HotkeysRequireFocus")
    config.read(profile / "Config/GCPadNew.ini")
    assert config.get("GCPad1", "Device") == "Pipe/0/pad"
    assert config.get("GCPad1", "Buttons/Start") == "`Button START`"
    assert config.get("GCPad1", "Triggers/L-Analog") == "`Axis L +`"


def test_launcher_restores_first_config_and_removes_new_config(short_root):
    launch = DolphinLauncher(config_dir=short_root)
    launch.configure_gdb_stub()
    launch.configure_gdb_stub()
    launch.cleanup()
    assert not launch.config_file.exists()
    original = "[General]\nGDBPort=42\n"
    launch.config_file.write_text(original)
    launch.configure_gdb_stub()
    launch.configure_gdb_stub()
    launch.cleanup()
    assert launch.config_file.read_text() == original


def test_kill_is_followed_by_wait(short_root):
    class Process:
        calls = []

        def poll(self):
            return None

        def terminate(self):
            self.calls.append("terminate")

        def kill(self):
            self.calls.append("kill")

        def wait(self, timeout):
            self.calls.append("wait")
            if self.calls.count("wait") == 1:
                raise subprocess.TimeoutExpired("Dolphin", timeout)

    launcher = DolphinLauncher(config_dir=short_root)
    process = launcher.process = Process()
    launcher.stop()
    assert process.calls == ["terminate", "wait", "kill", "wait"]


def test_launcher_retains_real_single_accept_gdb_client(short_root):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    launcher = DolphinLauncher(config_dir=short_root, gdb_port=listener.getsockname()[1])
    launcher.process = type("Alive", (), {"poll": lambda self: None})()

    def stub():
        conn, _ = listener.accept()
        with conn:
            conn.settimeout(2)
            assert conn.recv(1) == b"\x03"
            conn.sendall(b"$S05#b8")
            assert conn.recv(1) == b"+"
            for reply in (b"80000000", b"12345678", b"S05"):
                command = b""
                while b"#" not in command or len(command.split(b"#")[-1]) < 2:
                    command += conn.recv(1)
                conn.sendall(b"+" + b"$" + reply + b"#" + f"{sum(reply) % 256:02x}".encode())
                assert conn.recv(1) == b"+"

    with ThreadPoolExecutor(1) as pool:
        peer = pool.submit(stub)
        try:
            debugger = launcher.wait_for_gdb_ready(1)
            assert debugger is launcher.wait_for_gdb_ready(1)
            assert debugger.read_u32(0x80000000) == 0x12345678
            assert debugger.step(0.5) == "S05"
            peer.result(2)
        finally:
            if launcher.debugger:
                launcher.debugger.disconnect()
            listener.close()


class RecordingPipe:
    def __init__(self, on_press=None):
        self.commands = []
        self.on_press = on_press
        self.alive = lambda: True

    def write(self, command, timeout=2):
        self.commands.append((command, time.monotonic()))
        if command.startswith("PRESS") and self.on_press:
            self.on_press()


@pytest.mark.parametrize(
    "input_request",
    [
        dict(operation="tap", token="A\nPRESS B"),
        dict(operation="tap", token="A", duration=float("nan")),
        dict(operation="tap", token="A", duration=float("inf")),
        dict(operation="stick", token="MAIN", x=-1, y=0.5),
        dict(operation="stick", token="UNKNOWN", x=0.5, y=0.5),
        dict(operation="trigger", token="L", x=1.1),
        dict(operation="trigger", token="L", x=float("nan")),
    ],
)
def test_invalid_input_never_writes(input_request):
    pipe = RecordingPipe()
    with pytest.raises(ValueError):
        Controller(pipe).request(**input_request)
    assert pipe.commands == []


def test_taps_are_serialized_and_release_after_exception():
    pipe = RecordingPipe()
    controller = Controller(pipe)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(controller.request, "tap", "A", duration=0.05)
        b = pool.submit(controller.request, "tap", "B", duration=0.05)
        a.result()
        b.result()
    commands = [x[0] for x in pipe.commands]
    assert commands in (
        ["PRESS A", "RELEASE A", "PRESS B", "RELEASE B"],
        ["PRESS B", "RELEASE B", "PRESS A", "RELEASE A"],
    )
    assert pipe.commands[1][1] - pipe.commands[0][1] >= 0.04
    pipe.on_press = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        controller.request("tap", "START")
    assert pipe.commands[-1][0] == "RELEASE START"
    controller.reset()
    assert pipe.commands[-4:][0][0] == "SET MAIN 0.5 0.5"
    assert not controller.held


def test_fifo_real_reader_required_and_partial_writes(short_root, monkeypatch):
    path = short_root / "pipe"
    os.mkfifo(path)
    channel = PipeChannel(path)
    with pytest.raises(TimeoutError, match="No Dolphin reader"):
        channel.open(0.03)
    reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    channel.open(0.1)
    original = os.write
    attempts = [errno.EINTR, errno.EAGAIN, None, None]

    def write(fd, data):
        outcome = attempts.pop(0) if attempts else None
        if outcome:
            raise OSError(outcome, "injected")
        return original(fd, data[:2])

    monkeypatch.setattr(os, "write", write)
    channel.write("PRESS A", timeout=0.2)
    assert os.read(reader, 100) == b"PRESS A\n"
    os.close(reader)
    with pytest.raises(RuntimeError, match="input pipe failed"):
        channel.write("RELEASE A")
    channel.close()


def test_fifo_rejects_regular_file_and_symlink(short_root):
    regular = short_root / "file"
    regular.touch()
    with pytest.raises(ValueError, match="Not a FIFO"):
        PipeChannel(regular).open(0.1)
    fifo = short_root / "fifo"
    os.mkfifo(fifo)
    link = short_root / "link"
    link.symlink_to(fifo)
    with pytest.raises(ValueError, match="Not a FIFO"):
        PipeChannel(link).open(0.1)


def test_capture_freshness_black_retry_and_hash(short_root):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (16, 16), "red").save(short_root / "old.png")
    count = 0

    def capture():
        nonlocal count
        count += 1
        Image.new("RGB", (16, 16), (16, 16, 16) if count == 1 else (80, 90, 100)).save(
            short_root / f"frame_2026-09-07_{count}.png"
        )

    pipe = RecordingPipe(capture)
    result = NativeCapture(pipe, short_root).capture(timeout=3, dwell=0.01, release_dwell=0.01)
    assert result["attempts"] == 2
    assert result["rejections"][0]["reason"] == "black/near-black quality filter"
    assert result["visible_fraction"] == 1
    assert result["sha256"] == hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest()
    assert not result["predicate_requested"]
    assert (
        result["game_state_validation"]
        == "not established by capture; predicate acceptance alone is not semantic evidence"
    )
    assert pipe.commands[-1][0] == "RELEASE X"


def test_capture_waits_for_partial_png(short_root):
    Image = pytest.importorskip("PIL.Image")
    contents = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(contents, format="PNG")
    png = contents.getvalue()

    def capture():
        path = short_root / "new.png"
        path.write_bytes(png[:12])

        def finish():
            time.sleep(0.15)
            path.write_bytes(png)

        threading.Thread(target=finish).start()

    result = NativeCapture(RecordingPipe(capture), short_root).capture(timeout=2, dwell=0.01, release_dwell=0.01)
    assert result["sha256"] == hashlib.sha256(png).hexdigest()
    assert result["attempts"] == 1


def test_capture_corrupt_retry_and_library_predicate(short_root):
    Image = pytest.importorskip("PIL.Image")
    count = 0

    def capture():
        nonlocal count
        count += 1
        path = short_root / f"{count}.png"
        if count == 1:
            path.write_bytes(b"corrupt")
        else:
            Image.new("RGB", (16, 16), "white").save(path)

    predicate_calls = []

    def accept(image, metadata):
        predicate_calls.append(metadata)
        return len(predicate_calls) == 2

    result = NativeCapture(RecordingPipe(capture), short_root).capture(
        timeout=3, attempts=3, dwell=0.01, release_dwell=0.01, accept_capture=accept
    )
    assert result["attempts"] == 3
    assert result["predicate_requested"] and result["predicate_passed"]
    assert any(r["reason"] == "caller predicate rejected" for r in result["rejections"])


def test_capture_timeout_does_not_deliver_stale_frame(short_root):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (16, 16), "white").save(short_root / "old.png")
    pipe = RecordingPipe()
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        NativeCapture(pipe, short_root).capture(timeout=0.2, dwell=0.01, release_dwell=0.01)
    assert time.monotonic() - start < 0.5
    assert [cmd for cmd, _ in pipe.commands] == ["RELEASE X", "PRESS X", "RELEASE X"]


def test_capture_predicate_exception_is_explicit(short_root):
    Image = pytest.importorskip("PIL.Image")
    pipe = RecordingPipe(lambda: Image.new("RGB", (8, 8), "white").save(short_root / "new.png"))

    def fail(*args):
        raise ValueError("predicate broken")

    with pytest.raises(RuntimeError, match="Capture predicate failed: predicate broken"):
        NativeCapture(pipe, short_root).capture(timeout=1, dwell=0.01, release_dwell=0.01, accept_capture=fail)


def test_session_cli_never_falls_back(short_root, monkeypatch, capsys):
    monkeypatch.setattr(DolphinDebugger, "connect", lambda *args, **kwargs: pytest.fail("direct connection"))
    assert cli.main(["--session", str(short_root), "read", "test_symbol", "-n", "4"]) == 1
    assert "no direct attachment" in capsys.readouterr().out
    assert cli.main(["status"]) == 1


def test_cli_forwards_session_read_and_write(monkeypatch, capsys):
    seen = []

    def send(command, **kwargs):
        seen.append((command, kwargs))
        return {"success": True, "data": "hello"}

    monkeypatch.setattr(daemon, "send_command", send)
    assert cli.main(["--session", "/tmp/owned", "read", "named", "-n", "12", "-f", "string"]) == 0
    assert seen[0][0] == {"action": "read", "address": "named", "count": 12, "format": "string"}
    assert seen[0][1]["session"] == "/tmp/owned"
    assert "hello" in capsys.readouterr().out
    assert cli.main(["--session", "/tmp/owned", "write", "named", "0x1234"]) == 0
    assert seen[-1][0]["value"] == 0x1234


def test_symbol_lookup_is_local_and_override_visible(short_root, monkeypatch, capsys):
    symbols = short_root / "symbols.txt"
    symbols.write_text("lbLang_Test = .text:0x80005200; // type:function size:0x4 scope:global\n")
    monkeypatch.setattr(DolphinDebugger, "connect", lambda *args: pytest.fail("symbol lookup connected"))
    assert cli.main(["--symbols", str(symbols), "symbol", "lbLang_Test"]) == 0
    assert "80005200" in capsys.readouterr().out
    assert daemon.symbols_path() == Path(__file__).resolve().parents[3] / "config/GALE01/symbols.txt"


def test_typer_forwarding_and_discovery(monkeypatch):
    from typer.testing import CliRunner

    from src.cli import app, capabilities

    runner = CliRunner()
    result = runner.invoke(app, ["dolphin", "--help"])
    assert result.exit_code == 0
    assert "--session" in result.output and "capture" in result.output
    seen = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 7)
    result = runner.invoke(app, ["dolphin", "--session", "/tmp/test", "input", "tap", "START"])
    assert result.exit_code == 7
    assert seen == [["--session", "/tmp/test", "input", "tap", "START"]]
    commands = {item.name for item in capabilities.command_capabilities()}
    assert "dolphin" in commands
    for alias in (
        "dolphin",
        "runtime",
        "runtime validation",
        "controller",
        "controller capture",
        "capture",
        "screenshot",
        "game input",
    ):
        assert capabilities.TASK_ALIASES[alias] == ["dolphin"]


def test_gdb_package_imports_without_optional_dme_or_pillow():
    script = """
import builtins
real = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'dolphin_memory_engine' or name.startswith('PIL'):
        raise ImportError('intentionally unavailable')
    return real(name, *args, **kwargs)
builtins.__import__ = guarded
from src.dolphin_debug import DolphinDebugger, ConnectionMode
from src.dolphin_debug.daemon import DebugDaemon
from src.dolphin_debug.input_capture import image_decoder
assert DolphinDebugger(mode=ConnectionMode.GDB)
try:
    image_decoder()
except RuntimeError as exc:
    assert 'melee-agent[dolphin]' in str(exc)
else:
    raise AssertionError('capture decoder should be unavailable')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_capture_queue_deadline_is_bounded(short_root):
    pytest.importorskip("PIL.Image")
    capture = NativeCapture(RecordingPipe(), short_root)
    capture.lock.acquire()
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="queue deadline"):
            capture.capture(timeout=0.1, dwell=0.01, release_dwell=0.01)
    finally:
        capture.lock.release()
    assert 0.09 <= time.monotonic() - start < 0.4


def test_release_is_allowed_stopped_but_press_does_not_unpause():
    service = daemon.DebugDaemon()
    service.dbg = FakeDebugger(mode=ConnectionMode.GDB)
    service.dbg.is_connected = True
    service.dbg.execution_state = "stopped"
    pipe = RecordingPipe()
    service.controller = Controller(pipe)
    assert service.handle_command({"action": "input", "request": {"operation": "release", "token": "A"}})["success"]
    assert service.handle_command({"action": "input", "request": {"operation": "release-all"}})["success"]
    commands = list(pipe.commands)
    result = service.handle_command({"action": "input", "request": {"operation": "press", "token": "A"}})
    assert not result["success"] and "resume" in result["error"]
    assert pipe.commands == commands
    assert service.dbg.execution_state == "stopped"


def test_capture_exit_releases_hotkey(short_root):
    pytest.importorskip("PIL.Image")
    active = [True]
    pipe = RecordingPipe(lambda: active.__setitem__(0, False))
    with pytest.raises(RuntimeError, match="Owned Dolphin exited"):
        NativeCapture(pipe, short_root, alive=lambda: active[0]).capture(timeout=1, dwell=0.01, release_dwell=0.01)
    assert pipe.commands[-1][0] == "RELEASE X"


def test_rpc_rejects_wrong_identity_without_stopping_service():
    service = daemon.DebugDaemon()
    service.running = True
    service.metadata = {"session_id": "correct"}
    a, b = socket.socketpair()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(service.handle_client, a)
        b.sendall(b'{"session_id":"incorrect","action":"stop"}\n')
        data = b.recv(4096)
        future.result(1)
    b.close()
    assert not json.loads(data)["success"]
    assert service.running


def test_explicit_occupied_port_fails_before_launch(short_root, fake_launch):
    binary, iso, processes = fake_launch
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        path = short_root / "occupied"
        assert daemon.DebugDaemon().start(str(iso), str(binary), path, port=listener.getsockname()[1]) == 1
    assert not processes
    assert not (path / "daemon.sock").exists()
    assert json.loads((path / "session.json").read_text())["status"] == "failed"


def test_missing_symbols_is_visible_in_session_metadata(short_root, fake_launch):
    binary, iso, processes = fake_launch
    service, path = daemon.DebugDaemon(), short_root / "missing-symbols"
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            service.start, str(iso), str(binary), path, symbols=short_root / "not-present", timeout=0.5
        )
        try:
            data = wait_ready(path, future)
            assert data["symbols_available"] is False
            assert data["emulator_version"] == "fake Dolphin test binary"
            assert "--user" in data["launch_argv"]
            assert set(data["config_sha256"]) == {"Dolphin.ini", "GCPadNew.ini", "Hotkeys.ini"}
            assert service.dbg.symbols == {}
        finally:
            service.running = False
            future.result(3)


def test_capture_rpc_does_not_accept_executable_predicates():
    service = daemon.DebugDaemon()
    service.dbg = FakeDebugger(mode=ConnectionMode.GDB)
    service.dbg.is_connected = True
    service.dbg.execution_state = "running"
    service.capturer = object()
    result = service.handle_command({"action": "capture", "options": {"accept_capture": "eval(...)"}})
    assert not result["success"] and "library-only" in result["error"]


def test_oversized_session_read_never_reaches_transport(monkeypatch):
    from src.dolphin_debug import GDBClient

    service = daemon.DebugDaemon()
    service.dbg = FakeDebugger(mode=ConnectionMode.GDB)
    service.dbg.is_connected = True
    monkeypatch.setattr(service.dbg, "read_bytes", lambda *args: pytest.fail("oversized read reached transport"))
    result = service.handle_command({"action": "read", "address": "test_symbol", "count": GDBClient.MAX_PACKET // 2})
    assert not result["success"] and "RSP packet limit" in result["error"]


def test_poc_reuses_retained_readiness_client_and_cleans_owned_launch(monkeypatch):
    from src.dolphin_debug import poc

    events = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def connect(self):
            pytest.fail("POC attempted a second connection")

        def query_supported(self):
            return ""

        def get_stop_reason(self):
            return "S05"

        def disconnect(self):
            events.append("disconnect")

    retained = Client()

    class Launcher:
        def __init__(self, **kwargs):
            pass

        def launch(self, *args, **kwargs):
            return True

        def wait_for_gdb_ready(self, timeout):
            return type("Debugger", (), {"_gdb": retained})()

        def cleanup(self):
            events.append("cleanup")

    monkeypatch.setattr(poc, "GDBClient", Client)
    monkeypatch.setattr(poc, "DolphinLauncher", Launcher)
    for name in ("test_memory_read", "test_registers", "test_breakpoints"):

        def probe(client):
            assert client is retained
            return True

        monkeypatch.setattr(poc, name, probe)
    monkeypatch.setattr(sys, "argv", ["poc", "--iso", "/tmp/game.iso"])
    assert poc.main() == 0
    assert events == ["disconnect", "cleanup"]
