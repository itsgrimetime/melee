# Build mwcc_debug.dll (lmgr326b.dll replacement) via MinGW cross-compile.
# See docs/mwcc-debug-poc-design.md for context.

CC := i686-w64-mingw32-gcc
CFLAGS := -shared -m32 -nostdlib -fno-stack-protector -Os
# --kill-at: strip @N stdcall suffix from exports (matches lmgr326b.dll ABI).
# --entry=_DllMain@12: explicit DLL entry point. With -nostdlib we opt out of
#   MinGW's default _DllMainCRTStartup wrapper, so Windows needs to know to
#   call DllMain directly when the DLL loads.
LDFLAGS := -Wl,--kill-at -Wl,--entry=_DllMain@12
# kernel32 needed for VirtualProtect (would be implicit without -nostdlib).
LIBS := -lkernel32

# Output as lmgr326b.dll because that's the filename mwcceppc.exe loads.
OUT := ../../build/tools/mwcc_debug/lmgr326b.dll

SRCS := mwcc_debug.c
DEF  := mwcc_debug.def

.PHONY: all clean

all: $(OUT)

$(OUT): $(SRCS) $(DEF)
	@mkdir -p $(dir $(OUT))
	$(CC) $(CFLAGS) $(LDFLAGS) $(DEF) -o $@ $(SRCS) $(LIBS)

clean:
	rm -f $(OUT)
