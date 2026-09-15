import configparser

import pytest

from src.dolphin_debug.debugger import DolphinDebugger
from src.dolphin_debug.launcher import DolphinLauncher


def test_launch_uses_configured_user_directory(tmp_path, monkeypatch):
    binary = tmp_path / "Dolphin"
    iso = tmp_path / "game.iso"
    binary.touch()
    iso.touch()
    launcher = DolphinLauncher(dolphin_path=str(binary), config_dir=tmp_path / "profile")
    calls = []

    class Process:
        pid = 123

    def launch(command, **kwargs):
        calls.append(command)
        return Process()

    monkeypatch.setattr("src.dolphin_debug.launcher.subprocess.Popen", launch)
    assert launcher.launch(str(iso))
    assert calls[0] == [str(binary), "--user", str(tmp_path / "profile"), "--exec", str(iso)]


def test_gdb_configuration_preserves_profile_settings(tmp_path):
    launcher = DolphinLauncher(config_dir=tmp_path, gdb_port=19192)
    launcher.config_file.parent.mkdir()
    original = "[Core]\nCPUCore = 0\n[General]\nISOPath0 = /games\n"
    launcher.config_file.write_text(original)
    launcher.configure_gdb_stub()
    config = configparser.ConfigParser()
    config.read(launcher.config_file)
    assert config.getint("General", "GDBPort") == 19192
    assert config.get("General", "ISOPath0") == "/games"
    assert config.getint("Core", "CPUCore") == 0
    assert not config.has_option("Core", "GDBPort")
    launcher.disable_gdb_stub()
    config.read(launcher.config_file)
    assert config.getint("General", "GDBPort") == -1
    launcher.cleanup()
    assert launcher.config_file.read_text() == original


@pytest.mark.parametrize("reply, expected", [
    ("8000522C", 0x8000522C), ("00000000", 0),
    (None, None), ("E01", None), ("", None),
    ("T0540:80005340;", None), ("zzzzzzzz", None), ("80 00 52", None),
])
def test_read_pc_uses_individual_register_packet(monkeypatch, reply, expected):
    debugger = DolphinDebugger()
    debugger._gdb.sock = object()
    commands = []

    def command(value):
        commands.append(value)
        return reply

    monkeypatch.setattr(debugger, "_gdb_send", command)
    assert debugger.read_pc() == expected
    assert commands == ["p40"]
