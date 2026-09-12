"""Bounded GALE01 mnDiagram API experiment; interpreter, isolated profile.
Run from the repository root with PYTHONPATH="$PWD/tools/melee-agent".
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import time
from src.dolphin_debug.debugger import ConnectionMode, DolphinDebugger
import src.dolphin_debug.debugger as implementation

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--dolphin", required=True)
p.add_argument("--iso", required=True)
p.add_argument("--output", required=True)
p.add_argument("--port", type=int, default=19326)
a = p.parse_args()
profile = tempfile.mkdtemp(prefix="melee-mndiagram-contract-")
command = [
    a.dolphin,
    "--user=" + profile,
    "--exec=" + a.iso,
    f"--config=Dolphin.General.GDBPort={a.port}",
    "--config=Dolphin.Core.CPUCore=0",
]
r = {
    "command": command,
    "profile": profile,
    "tool_module": implementation.__file__,
    "emulator": subprocess.check_output([a.dolphin, "--version"], text=True).strip(),
    "revision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "cases": [],
    "verified_functions": {},
}
dol = Path("orig/GALE01/sys/main.dol").read_bytes()
r["dol_sha1"] = hashlib.sha1(dol).hexdigest()
assert r["dol_sha1"] == "08e0bf20134dfcb260699671004527b2d6bb1a45"


def dol_bytes(addr, size):
    for i in range(18):
        offset = struct.unpack_from(">I", dol, i * 4)[0]
        start = struct.unpack_from(">I", dol, 0x48 + i * 4)[0]
        length = struct.unpack_from(">I", dol, 0x90 + i * 4)[0]
        if start <= addr and addr + size <= start + length:
            return dol[offset + addr - start : offset + addr - start + size]
    raise ValueError(hex(addr))


symbols = {}
for line in Path("config/GALE01/symbols.txt").read_text().splitlines():
    m = re.match(r"(\w+) = \.text:0x([0-9A-Fa-f]+);.*size:0x([0-9A-Fa-f]+)", line)
    if m:
        symbols[m[1]] = (int(m[2], 16), int(m[3], 16))
names = [
    "mnDiagram_IsDistanceOverflow",
    "mnDiagram_ConvertDistanceForDisplay",
    "mnDiagram_FormatDecimalNumber",
    "mnDiagram_FormatTime",
    "mnDiagram_IntToStr",
    "lbLang_IsSavedLanguageUS",
    "gmMainLib_8015CC58",
    "__cvt_fp2unsigned",
    "mn_GetDigitCount",
    "mn_GetDigitAt",
    "powi",
]
with socket.socket() as probe:
    probe.bind(("127.0.0.1", a.port))
process = subprocess.Popen(
    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
dbg = DolphinDebugger(mode=ConnectionMode.GDB, gdb_port=a.port)
saved = {}
memory = []


def packet(s):
    v = dbg._gdb_send(s)
    if v is None or v.startswith("E"):
        raise RuntimeError((s, v))
    return v


def read(addr, n):
    return packet(f"m{addr:x},{n:x}").lower()


def write(addr, data):
    assert packet(f"M{addr:x},{len(data) // 2:x}:{data}") == "OK"
    assert read(addr, len(data) // 2) == data.lower()


def reg(i):
    return packet(f"p{i:x}")


def setreg(i, v):
    data = v if isinstance(v, str) else f"{v & 0xFFFFFFFF:08x}"
    assert packet(f"P{i:x}={data}") == "OK"
    assert reg(i).lower() == data.lower(), (i, data, reg(i))


def save_memory(addr, size):
    # Bound each read below Dolphin RSP packet limit.
    for offset in range(0, size, 512):
        memory.append((addr + offset, read(addr + offset, min(512, size - offset))))


def invoke(name, args):
    for i in range(3, 11):
        setreg(i, args[i - 3] if i - 3 < len(args) else 0)
    setreg(1, 0x817EF000)
    setreg(2, 0x804DF9E0)
    setreg(13, 0x804DB6A0)
    setreg(65, (int(saved[65], 16) | 0x2000) & ~0x8000)
    setreg(67, return_pc)
    setreg(64, symbols[name][0])
    pcs = []
    for _ in range(4000):
        pc = dbg.read_pc()
        if pc == return_pc:
            break
        assert any(
            start <= pc < start + size for start, size in (symbols[n] for n in names)
        ), hex(pc)
        pcs.append(hex(pc))
        stop = dbg.step()
        assert stop and stop.startswith(("T05", "S05")), stop
    assert dbg.read_pc() == return_pc, (name, "step budget exceeded")
    assert int(reg(1), 16) == 0x817EF000
    return {
        "function": name,
        "args": args,
        "return_u32": int(reg(3), 16),
        "steps": len(pcs),
        "pcs": pcs,
    }


try:
    for _ in range(100):
        assert process.poll() is None, "emulator exited"
        if dbg.connect(timeout=0.2):
            break
        time.sleep(0.2)
    assert dbg.has_gdb
    assert dbg.halt(), dbg.last_error
    r["initial_stop"] = dict(dbg.last_execution)
    assert r["initial_stop"]["confirmed"] and r["initial_stop"]["fenced"]
    assert read(0x80000000, 6) == "47414c453031"
    for name in names:
        addr, size = symbols[name]
        code = read(addr, size)
        assert code == dol_bytes(addr, size).hex(), name
        r["verified_functions"][name] = {
            "address": hex(addr),
            "size": size,
            "bytes": code,
        }
    for i in range(71):
        saved[i] = reg(i)
    return_pc = int(saved[64], 16)
    r["initial_pc"] = hex(return_pc)
    r["initial_registers"] = saved
    save_memory(0x817EE000, 0x1100)
    save_memory(0x817F0000, 64)
    base = int(read(0x804D3EE0, 4), 16)
    assert 0x80000000 <= base < 0x81800000
    # Decode the verified lwz/addi accessor and lbz in the language predicate.
    accessor = bytes.fromhex(r["verified_functions"]["gmMainLib_8015CC58"]["bytes"])
    predicate = bytes.fromhex(
        r["verified_functions"]["lbLang_IsSavedLanguageUS"]["bytes"]
    )
    assert accessor[:4].hex() == "806d8840"
    assert accessor[4:6].hex() == "3863"
    assert predicate[16:18].hex() == "8803"
    language_addr = (
        base
        + int.from_bytes(accessor[6:8], "big", signed=True)
        + int.from_bytes(predicate[18:20], "big", signed=True)
    )
    r["language_pointer"] = {"base": hex(base), "saved_language": hex(language_addr)}
    save_memory(language_addr, 1)
    assert read(0x804D4FA4, 1) == "00"
    for lang in (0, 1):
        write(language_addr, f"{lang:02x}")
        for distance in (
            0,
            30,
            31,
            99,
            100,
            99999,
            100000,
            100001,
            160933,
            160934,
            160935,
            200000,
            321868,
            0xFFFFFFFF,
        ):
            for name in names[:2]:
                case = invoke(name, [distance])
                case.update(language=lang, distance=distance)
                if name == names[0]:
                    expected = int(distance >= (160934 if lang else 100000))
                else:
                    expected = (
                        (
                            distance // 160934
                            if distance >= 160934
                            else int(distance / 30.4788)
                        )
                        if lang
                        else (
                            distance // 100000
                            if distance >= 100000
                            else distance // 100
                        )
                    )
                case["expected"] = expected
                assert case["return_u32"] == expected, case
                r["cases"].append(case)
            print(f"distance language={lang} value={distance} passed", flush=True)
    for name, inputs, expected in [
        (names[2], [0, 0], "0"),
        (names[2], [0, 2], "0.00"),
        (names[2], [5, 2], "0.05"),
        (names[2], [12345, 2], "123.45"),
        (names[2], [999999, 2], "9999.99"),
        (names[2], [9999999, 0], "9999999"),
        (names[2], [9999999, 2], "99999.99"),
        (names[3], [0], "0:00"),
        (names[3], [59], "0:59"),
        (names[3], [60], "1:00"),
        (names[3], [599999], "9999:59"),
        (names[3], [600000], "10000:00"),
        (names[3], [5999999], "99999:59"),
        (names[4], [0], "0"),
        (names[4], [42], "42"),
        (names[4], [9999999], "9999999"),
        (names[4], [99999999], "99999999"),
    ]:
        write(0x817F0000, "a5" * 64)
        case = invoke(name, [0x817F0000] + inputs)
        data = bytes.fromhex(read(0x817F0000, 64))
        expected_bytes = expected.encode() + b"\0"
        assert data == expected_bytes + b"\xa5" * (64 - len(expected_bytes)), (
            name,
            inputs,
            data,
        )
        case.update(output=expected, output_hex=data.hex(), expected=expected)
        r["cases"].append(case)
        print(f"{name}{inputs} -> {expected}", flush=True)
    r["passed"] = True
except BaseException as e:
    r["error"] = repr(e)
    raise
finally:
    try:
        for addr, data in reversed(memory):
            write(addr, data)
        for i, value in saved.items():
            setreg(i, value)
        r["restored_memory_regions"] = len(memory)
        r["restored_registers"] = len(saved)
        r["restored"] = bool(saved) and bool(memory)
    finally:
        dbg.disconnect()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        Path(a.output).write_text(json.dumps(r, indent=2) + "\n")
        print("result: " + a.output, flush=True)
