"""Example mwcc-retro intervention hook (#545).

Run with:
  melee-agent debug retro dump <tu> -f <fn> \
      --gdb-py tools/mwcc_retro/hooks/example_intervene.py

The runtime calls `intervene(ctx)` inside the connected, descriptor-injected gdb
session. `ctx` (a RetroContext) exposes the write-capable substrate:

  ctx.addr(key)        -> a named VA from the 1.2.5n table (e.g. "debuglisting_flag")
  ctx.read(va, n)      -> bytes from the emulated inferior
  ctx.write(va, data)  -> write bytes into the inferior (exe on disk is untouched)
  ctx.u32(va) / ctx.set_u32(va, val)
  ctx.reg(name)        -> a register value (e.g. ctx.reg("pc"))
  ctx.brk(va)          -> set a software breakpoint
  ctx.cont()           -> continue to program exit (disconnect-tolerant)
  ctx.call(fn_va, *int_args) -> call a function with int/pointer args
  ctx.gdb / ctx.cad / ctx.table / ctx.fn / ctx.out_dir

This example demonstrates "intervene at a stage, observe/mutate, replay forward":
break at the IRO 'Starting function' push (CRT is up there), prove read +
register + write+readback work, then continue. Copy and adapt it to force a
specific compiler state and watch the downstream effect.
"""


def intervene(ctx):
    sf_push = ctx.addr("iro_starting_function_push")  # 0x42cd86 on 1.2.5n
    dbg_flag = ctx.addr("debuglisting_flag")          # 0x584226
    print(f"[hook] target fn={ctx.fn}  sf_push={sf_push:#x}  dbg_flag={dbg_flag:#x}")

    # Stage k: stop deep in compilation (CRT initialised).
    ctx.brk(sf_push)
    ctx.gdb.execute("continue")
    print(f"[hook] stopped at pc={ctx.reg('pc'):#x}")

    # Observe: read a known byte (the DEBUGLISTING option-default site is 0xc6).
    before = ctx.read(0x42C8DB, 1)
    print(f"[hook] read 0x42C8DB = {before.hex()} (expect c6)")

    # Mutate + verify: flip the DEBUGLISTING flag and read it back.
    ctx.write(dbg_flag, b"\x01")
    print(f"[hook] DEBUGLISTING after write = {ctx.read(dbg_flag, 1).hex()} (expect 01)")

    # Replay forward to completion.
    ctx.cont()
    print("[hook] done")
