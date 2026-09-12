"""Bounded GALE01 setter experiment; run from the active repository root.

PYTHONPATH="$PWD/tools/melee-agent" python tools/dolphin-lblanguage-contract.py --dolphin /path/to/Dolphin --iso /path/to/game.iso
Only the owned emulator is terminated. The temporary profile is retained.
This exercises an API under controlled register setup, not a normal menu event.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

from src.dolphin_debug.debugger import ConnectionMode, DolphinDebugger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dolphin', required=True)
    parser.add_argument('--iso', required=True)
    parser.add_argument('--port', type=int, default=19193)
    args = parser.parse_args()
    profile = tempfile.mkdtemp(prefix='melee-lblanguage-contract-')
    command = [args.dolphin, '--user=' + profile, '--exec=' + args.iso,
               f'--config=Dolphin.General.GDBPort={args.port}',
               '--config=Dolphin.Core.CPUCore=0']
    result = {'command': command, 'profile': profile, 'cases': []}
    import src.dolphin_debug.debugger as implementation
    result['tool_module'] = implementation.__file__
    result['emulator_version'] = subprocess.check_output(
        [args.dolphin, '--version'], text=True).strip()
    debugger = DolphinDebugger(mode=ConnectionMode.GDB, gdb_port=args.port)
    # Reject an occupied port before launching; do not connect to an existing stub.
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    saved = {}
    storage = None
    original = None

    def packet(command):
        reply = debugger._gdb_send(command)
        if reply is None or reply.startswith('E'):
            raise RuntimeError((command, reply))
        return reply

    def read_register(index):
        value = packet(f'p{index:x}')
        assert len(value) == 8, value
        return int(value, 16)

    def write_register(index, value):
        assert packet(f'P{index:x}={value & 0xffffffff:08x}') == 'OK'
        assert read_register(index) == value & 0xffffffff

    try:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError('Dolphin exited before connection')
            if debugger.connect(timeout=.2):
                break
            time.sleep(.25)
        assert debugger.has_gdb
        assert debugger.halt(), debugger.last_error
        result['initial_stop'] = dict(debugger.last_execution)
        assert result['initial_stop']['confirmed'] and result['initial_stop']['fenced']
        assert packet('m80000000,6').lower() == '47414c453031'
        expected = '2c0300004d8000202c0300024c800020808d8840986400004e800020'
        result['function_bytes'] = packet('m8000ad98,1c').lower()
        assert result['function_bytes'] == expected
        result['original_dol_sha1'] = hashlib.sha1(Path('orig/GALE01/sys/main.dol').read_bytes()).hexdigest()
        assert result['original_dol_sha1'] == '08e0bf20134dfcb260699671004527b2d6bb1a45'
        # lwz r4,-0x77c0(r13) resolves the configured pointer at 0x804d3ee0.
        storage = int(packet('m804d3ee0,4'), 16)
        assert 0x80000000 <= storage < 0x81800000
        original = packet(f'm{storage:x},1')
        result['storage'] = hex(storage)
        for index in (3, 4, 13, 64, 66, 67):
            saved[index] = read_register(index)
        assert debugger.read_pc() == saved[64]
        for initial in (0, 1):
            for argument in (-2147483648, -1, 0, 1, 2, 2147483647):
                assert packet(f'M{storage:x},1:{initial:02x}') == 'OK'
                write_register(13, 0x804db6a0)
                write_register(3, argument)
                write_register(67, saved[64])
                write_register(64, 0x8000ad98)
                pcs = []
                for _ in range(8):
                    pc = debugger.read_pc()
                    pcs.append(hex(pc))
                    if pc == saved[64]:
                        break
                    assert 0x8000ad98 <= pc < 0x8000adb4
                    stop = debugger.step()
                    assert stop and stop.startswith(('T05', 'S05')), stop
                assert debugger.read_pc() == saved[64]
                returned = read_register(3)
                stored = int(packet(f'm{storage:x},1'), 16)
                assert returned == argument & 0xffffffff
                assert stored == (argument if argument in (0, 1) else initial)
                result['cases'].append({'initial': initial, 'argument': argument,
                                        'returned_u32': returned, 'stored': stored, 'pcs': pcs})
    finally:
        try:
            if original is not None:
                assert packet(f'M{storage:x},1:{original}') == 'OK'
                assert packet(f'm{storage:x},1') == original
            for index, value in saved.items():
                write_register(index, value)
            result['restored'] = bool(saved)
        finally:
            debugger.disconnect()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
