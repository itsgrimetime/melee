# P0 Spike Findings — mwcc-retro substrate + fidelity gates (#541)

Date: 2026-06-10. Host: macOS arm64 (Darwin 24.5), gdb 17.1 (homebrew), cargo 1.85.

## Verdict: P0 PASS — all hard stop conditions cleared. Proceed to P1/P2.

## Build
- `cargo build -p retrowin32 -F x86-unicorn --profile lto` succeeds (~38s warm).
- **Binary path is NOT `<repo>/target/lto/retrowin32`.** The melee repo's
  `.cargo/config.toml` sets `[build] target-dir = "build/cargo"`, so any cargo
  build under the melee tree lands in `/Users/mike/code/melee/build/cargo/`.
  The actual binary is `build/cargo/lto/retrowin32` (14 MB arm64 Mach-O).
  → Bug fixed in `setup.py`: `_retrowin32_binary` now resolves the real target
  dir via `cargo metadata` instead of assuming `repo/target/`.
- retrowin32 LICENSE present (MIT-ish) — only cadmic lacks a license.

## retrowin32 CLI (confirmed by reading cli/src/main.rs + debugger.rs)
- Flags: `--gdb-stub` (switch), `--debug`, `-C/--chdir`, positional greedy
  `cmdline`. **There is NO `--gdb-port` flag.** The gdb port is hardcoded:
  `wait_for_gdb_connection(9001)` (debugger.rs:881). Reference connect script
  ships as `gdb-script`: `target remote localhost:9001`.
  → Bug fixed in `mwcc_retro_debugger.py main()`: dropped the bogus
  `--gdb-port=` arg; serialize on fixed port 9001 via a lockfile for
  parallel-agent safety; RETRO_PORT is informational only (always 9001).
- Invocation: `retrowin32 --gdb-stub <mwcceppc.exe> <mwcc args...>`.
- `wait_for_gdb_connection` accepts exactly ONE connection. **Do not pre-poll
  the port by connecting** — a readiness probe that opens a socket steals the
  single accept slot and gdb then times out. Launch the emulator, give it a
  beat, connect gdb directly.

## Fidelity gate — .o byte parity (the critical stop condition): PASS
- Control TU: `src/melee/mn/mnvibration.c` (real menu TU with floating point),
  compiled with the exact ninja mwcc args (`-O4,p -fp hardware -fp_contract on`
  …), `-MMD` dropped, `-o` redirected.
- wibo+sjiswrap path → md5 `d82db59766aa0f5f4320c87e902d1e43` (18520 bytes).
- retrowin32 path, identical args → md5 `d82db59766aa0f5f4320c87e902d1e43`.
- **BYTE-IDENTICAL.** unicorn's x86 emulation (incl. x87 FP folding) matches
  wibo exactly on FP-containing code. The emulator is a faithful oracle.

## gdb substrate probes (all against the running stub, i386)
1. attach (`set architecture i386; set osabi none; target remote :9001`) — ✓
2. read memory at known VA — ✓ (0x42C8DB → `c6 05 26 42 58 00 00`, the exact
   DEBUGLISTING option-default patch site)
3. write memory + readback — ✓ (wrote DEBUGLISTING flag 0x584226 = 1, read 0x01)
4. software breakpoint — ✓ hit `0x42CD86` (IRO "Starting function" push) cleanly
   **but only with `-O4,p`**; at -O0 the IRO optimizer path is skipped and the
   bp never fires (compiler just exits). Always probe with optimization on.
5. gdb `call` with **string-literal** args — ✗ "requires the program to have a
   function malloc": gdb can't marshal new strings into a no-symbol inferior.
6. gdb `call` with **pre-staged pointer** args — ✓: write the path/mode strings
   into scratch `.data` via memory-write, then `call fopen(ptrPath, ptrMode)`
   succeeds, returns a FILE*, and creates the file.

## Implications for P2 (front-end IRO tracing recipe)
All required primitives are confirmed working. The recipe is fully viable:
- DEBUGLISTING(0x584226)=1, DEBUG_GUARD(0x5882B8)=1 via memory-write.
- Stage a listing-filename string into scratch `.data` via memory-write;
  `call fopen(0x40C690)(pathPtr, modePtr)` (staged-pointer form) → FILE*;
  write that FILE* into PCFILE(0x580610).
- Patch the IRO_DumpAfterPhase flag-test `jz` (string-anchored) via memory-write
  at attach/break, read-before-write asserted.
- Per-function scoping: breakpoint at IRO_Optimizer entry, read `func->name`
  (+0xA chain); cadmic's linkname `call` passes an existing object pointer, which
  is the staged-pointer class that works — but reading `obj.name` avoids the
  call entirely and is preferred.

## Performance budget (informal)
- Warm TU compile under retrowin32 (mnvibration, -O4,p): a few seconds, same
  order as wibo. Diagnosis-grade as designed; fine for single-function dumps.
