# Build mwcc_debug.dll (lmgr326b.dll replacement) via MinGW cross-compile.
# See docs/mwcc-debug-poc-design.md for context.

CC := i686-w64-mingw32-gcc
CFLAGS := -shared -m32 -nostdlib -fno-stack-protector -Os
LDFLAGS := -Wl,--kill-at

# Output as lmgr326b.dll because that's the filename mwcceppc.exe loads.
OUT := ../../build/tools/mwcc_debug/lmgr326b.dll

SRCS := mwcc_debug.c
DEF  := mwcc_debug.def

.PHONY: all clean

all: $(OUT)

$(OUT): $(SRCS) $(DEF)
	@mkdir -p $(dir $(OUT))
	$(CC) $(CFLAGS) $(LDFLAGS) $(DEF) -o $@ $(SRCS)

clean:
	rm -f $(OUT)
