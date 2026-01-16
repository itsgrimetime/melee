"""
mwcc compilation wrapper.

Compiles C snippets using the same compiler and flags as Melee,
then disassembles to extract opcodes.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .contexts import TranslationUnit
from .opcodes import OpcodeSequence, extract_opcodes


@dataclass
class CompileResult:
    """Result of compiling a snippet."""

    success: bool
    source: str
    opcodes: OpcodeSequence | None
    asm: str | None
    error: str | None
    template_name: str = ""
    context_name: str = ""


# Exact cflags used for Melee compilation
# These must match what the game was compiled with
MWCC_CFLAGS = [
    "-O4,p",
    "-nodefaults",
    "-proc",
    "gekko",
    "-fp",
    "hardware",
    "-Cpp_exceptions",
    "off",
    "-enum",
    "int",
    "-fp_contract",
    "on",
    "-inline",
    "auto",
    "-align",
    "powerpc",
    "-pragma",
    '"cats off"',
    "-str",
    "reuse",
    "-msgstyle",
    "std",
    "-nowraplines",
    "-warn",
    "off",
    "-maxerrors",
    "0",
    "-nofail",
    "-DNDEBUG=1",
    "-DM2CTX",
    "-RTTI",
    "off",
]

# Compiler version used for most Melee code
MWCC_VERSION = "GC/1.2.5n"

# Use wibo instead of wine for much faster compilation
USE_WIBO = True


def find_melee_root() -> Path | None:
    """Find the melee repository root."""
    # Try common locations
    candidates = [
        Path(__file__).parents[2] / "melee",  # melee-decomp/melee
        Path.home() / "code" / "melee",
        Path.home() / "code" / "melee-decomp" / "melee",
    ]

    for path in candidates:
        if (path / "build" / "compilers").exists():
            return path

    return None


def get_compiler_path(melee_root: Path) -> Path:
    """Get path to mwcc compiler."""
    return melee_root / "build" / "compilers" / MWCC_VERSION / "mwcceppc.exe"


def get_dtk_path(melee_root: Path) -> Path:
    """Get path to dtk disassembler."""
    return melee_root / "build" / "tools" / "dtk"


def get_wibo_path(melee_root: Path) -> Path:
    """Get path to wibo (lightweight wine alternative)."""
    return melee_root / "build" / "tools" / "wibo"


class Compiler:
    """Wrapper for mwcc compilation."""

    def __init__(self, melee_root: Path | None = None, use_wibo: bool = USE_WIBO):
        self.melee_root = melee_root or find_melee_root()
        if not self.melee_root:
            raise RuntimeError("Could not find melee repository. Set melee_root explicitly.")

        self.compiler = get_compiler_path(self.melee_root)
        self.dtk = get_dtk_path(self.melee_root)
        self.wibo = get_wibo_path(self.melee_root) if use_wibo else None
        self.use_wibo = use_wibo and self.wibo and self.wibo.exists()

        if not self.compiler.exists():
            raise RuntimeError(f"Compiler not found: {self.compiler}")
        if not self.dtk.exists():
            raise RuntimeError(f"dtk not found: {self.dtk}")
        if use_wibo and not self.use_wibo:
            print(f"Warning: wibo not found at {self.wibo}, falling back to wine")

    def compile(
        self,
        translation_unit: TranslationUnit,
        template_name: str = "",
        context_name: str = "",
    ) -> CompileResult:
        """
        Compile a translation unit and extract opcodes.

        Args:
            translation_unit: The TranslationUnit to compile
            template_name: Name of template (for metadata)
            context_name: Name of context (for metadata)

        Returns:
            CompileResult with opcodes or error
        """
        source = translation_unit.render()

        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = Path(tmpdir) / "synth.c"
            obj_path = Path(tmpdir) / "synth.o"
            asm_path = Path(tmpdir) / "synth.s"

            src_path.write_text(source)

            # Compile with mwcc via wibo (fast) or wine (slow fallback)
            if self.use_wibo:
                cmd = [
                    str(self.wibo),
                    str(self.compiler),
                    "-c",
                    *MWCC_CFLAGS,
                    "-o",
                    str(obj_path),
                    str(src_path),
                ]
            else:
                cmd = [
                    "wine",
                    str(self.compiler),
                    "-c",
                    *MWCC_CFLAGS,
                    "-o",
                    str(obj_path),
                    str(src_path),
                ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=30,
                    cwd=str(self.melee_root),
                )
            except subprocess.TimeoutExpired:
                return CompileResult(
                    success=False,
                    source=source,
                    opcodes=None,
                    asm=None,
                    error="Compilation timed out",
                    template_name=template_name,
                    context_name=context_name,
                )

            # Check for compilation errors
            # mwcc outputs errors to stdout, not stderr
            output = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            # Filter out wine noise
            error_lines = []
            for line in output.splitlines():
                if "Error:" in line or "error:" in line.lower():
                    error_lines.append(line)

            if error_lines or not obj_path.exists():
                return CompileResult(
                    success=False,
                    source=source,
                    opcodes=None,
                    asm=None,
                    error="\n".join(error_lines) if error_lines else "Compilation failed",
                    template_name=template_name,
                    context_name=context_name,
                )

            # Disassemble with dtk
            dtk_cmd = [
                str(self.dtk),
                "elf",
                "disasm",
                str(obj_path),
                str(asm_path),
            ]

            try:
                dtk_result = subprocess.run(
                    dtk_cmd,
                    capture_output=True,
                    timeout=10,
                )
            except subprocess.TimeoutExpired:
                return CompileResult(
                    success=False,
                    source=source,
                    opcodes=None,
                    asm=None,
                    error="Disassembly timed out",
                    template_name=template_name,
                    context_name=context_name,
                )

            if not asm_path.exists():
                return CompileResult(
                    success=False,
                    source=source,
                    opcodes=None,
                    asm=None,
                    error=f"Disassembly failed: {dtk_result.stderr.decode()}",
                    template_name=template_name,
                    context_name=context_name,
                )

            asm = asm_path.read_text()

            # Extract opcodes for target function
            target = translation_unit.target_function or "target_func"
            opcodes = extract_opcodes(asm, target)

            return CompileResult(
                success=True,
                source=source,
                opcodes=opcodes,
                asm=asm,
                error=None,
                template_name=template_name,
                context_name=context_name,
            )

    def compile_snippet(
        self,
        snippet: str,
        context_generator,
        template_name: str = "",
    ) -> CompileResult:
        """
        Convenience method to compile a snippet with a context generator.

        Args:
            snippet: C code snippet (function body)
            context_generator: ContextGenerator instance to use
            template_name: Name of template (for metadata)

        Returns:
            CompileResult with opcodes or error
        """
        tu = context_generator.generate(snippet)
        return self.compile(
            tu,
            template_name=template_name,
            context_name=context_generator.name,
        )
