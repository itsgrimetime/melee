#!/usr/bin/env python3
"""
Pre-commit style check for melee decompilation.

Validates coding guidelines derived from:
1. doldecomp/melee PR review feedback from maintainers
2. CONTRIBUTING.md coding guidelines
3. Community conventions

Usage:
    python tools/check-style.py [--fix] [files...]

Run without args to check staged files.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StyleViolation:
    """A style violation."""
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    fixable: bool = False
    severity: str = "error"  # "error" or "warning"

    def __str__(self):
        parts = []
        if self.file:
            parts.append(self.file)
            if self.line:
                parts.append(f":{self.line}")
            parts.append(": ")
        parts.append(self.message)
        return "".join(parts)


class StyleChecker:
    """Check C/H files for style violations."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).parent.parent
        self.errors: list[StyleViolation] = []
        self.warnings: list[StyleViolation] = []

    def get_staged_files(self) -> list[str]:
        """Get list of staged files."""
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True, text=True, check=True,
                cwd=self.project_root
            )
            return result.stdout.strip().split("\n") if result.stdout.strip() else []
        except subprocess.CalledProcessError:
            return []

    def get_staged_diff(self, file_path: str) -> str:
        """Get the staged diff for a file."""
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", file_path],
                capture_output=True, text=True, check=True,
                cwd=self.project_root
            )
            return result.stdout
        except subprocess.CalledProcessError:
            return ""

    def check_file(self, file_path: str, diff: Optional[str] = None) -> None:
        """Check a single file for style violations.

        Args:
            file_path: Path to the file
            diff: Optional diff content. If None, checks the whole file.
        """
        if diff:
            self._check_diff(file_path, diff)
        else:
            # Check the whole file
            full_path = self.project_root / file_path
            if full_path.exists():
                content = full_path.read_text()
                for i, line in enumerate(content.split("\n"), 1):
                    self._check_line(file_path, i, line)

    def _check_diff(self, file_path: str, diff: str) -> None:
        """Check only the added lines in a diff."""
        line_num = 0
        for line in diff.split("\n"):
            # Track line numbers in the new file
            if line.startswith("@@"):
                match = re.search(r'\+(\d+)', line)
                if match:
                    line_num = int(match.group(1)) - 1
                continue

            if line.startswith("+") and not line.startswith("+++"):
                line_num += 1
                content = line[1:]  # Remove + prefix
                self._check_line(file_path, line_num, content)
            elif not line.startswith("-"):
                line_num += 1

    def _check_line(self, file_path: str, line_num: int, content: str) -> None:
        """Check a single line for style violations."""
        stripped = content.strip()

        # Skip comments
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            return

        # =================================================================
        # BOOLEAN HANDLING
        # =================================================================

        # Check for TRUE/FALSE instead of true/false
        # PR feedback: "Use `true` and `false`, not `TRUE` and `FALSE`"
        if re.search(r'\bTRUE\b', content) and '#define' not in content:
            self.errors.append(StyleViolation(
                "Use 'true' not 'TRUE' (lowercase boolean literals required)",
                file_path, line_num
            ))
        if re.search(r'\bFALSE\b', content) and '#define' not in content:
            self.errors.append(StyleViolation(
                "Use 'false' not 'FALSE' (lowercase boolean literals required)",
                file_path, line_num
            ))

        # =================================================================
        # TYPE USAGE
        # =================================================================

        # Check for s32 instead of int
        # PR feedback: "use `int` (or `bool`) instead of `s32`"
        if re.search(r'\bs32\b', content) and '#define' not in content:
            self.warnings.append(StyleViolation(
                "Consider using 'int' instead of 's32'",
                file_path, line_num, severity="warning"
            ))

        # Check for M2C_UNK instead of UNK_T
        # PR feedback: "use `UNK_T` in place of `M2C_UNK`"
        if re.search(r'\bM2C_UNK\b', content):
            self.warnings.append(StyleViolation(
                "Use 'UNK_T' instead of 'M2C_UNK'",
                file_path, line_num, severity="warning"
            ))

        # =================================================================
        # FLOAT AND HEX LITERALS
        # =================================================================

        # Check for floating point literals without F suffix
        float_matches = re.findall(r'\b\d+\.\d+(?![FLfl\w])\b', content)
        for fm in float_matches:
            # Skip if in a comment
            if "//" in content:
                comment_start = content.index("//")
                try:
                    if content.index(fm) > comment_start:
                        continue
                except ValueError:
                    pass
            self.errors.append(StyleViolation(
                f"Float literal '{fm}' missing F suffix (use {fm}F for f32)",
                file_path, line_num
            ))

        # Check for lowercase hex (0xabc instead of 0xABC)
        hex_matches = re.findall(r'0x[0-9a-fA-F]+', content)
        for hm in hex_matches:
            hex_part = hm[2:]  # Remove 0x prefix
            if any(c.islower() and c.isalpha() for c in hex_part):
                self.errors.append(StyleViolation(
                    f"Hex literal '{hm}' should use uppercase (e.g., 0x{hex_part.upper()})",
                    file_path, line_num
                ))
                break  # Only report once per line

        # =================================================================
        # POINTER ARITHMETIC
        # =================================================================

        # Check for raw struct pointer arithmetic
        # PR feedback: "use M2C_FIELD or proper struct fields instead of pointer arithmetic"
        ptr_arith_match = re.search(
            r'\*\s*\(([^)]+\*)\)\s*\(\s*\(([^)]+\*)\)\s*([^+]+)\s*\+\s*([^)]+)\)',
            content
        )
        if ptr_arith_match:
            cast_type = ptr_arith_match.group(1).strip()
            ptr_expr = ptr_arith_match.group(3).strip()
            offset = ptr_arith_match.group(4).strip()
            self.errors.append(StyleViolation(
                f"Raw pointer arithmetic - use M2C_FIELD({ptr_expr}, {offset}, {cast_type}) or add struct field",
                file_path, line_num
            ))

        # Check for arrow+hex offset (->0x pattern)
        if re.search(r'->\s*0x[0-9a-fA-F]+', content):
            self.warnings.append(StyleViolation(
                "Direct offset access (->0x...) - consider adding struct field",
                file_path, line_num, severity="warning"
            ))

        # =================================================================
        # HEADER-SPECIFIC CHECKS (only for .h files)
        # =================================================================

        if file_path.endswith(".h"):
            # Check for underscore-prefixed struct names
            # PR feedback: "We don't prefix struct names with underscores anymore"
            if re.search(r'\bstruct\s+_\w+', content):
                self.errors.append(StyleViolation(
                    "Don't prefix struct names with underscores",
                    file_path, line_num
                ))

            # Check for relative includes in headers
            # PR feedback: "Headers should use angle bracket includes with full paths"
            if re.match(r'\s*#include\s+"[^/]', content):
                self.warnings.append(StyleViolation(
                    "Headers should use angle bracket includes (e.g., <melee/...>)",
                    file_path, line_num, severity="warning"
                ))

            # Check for types.h includes in headers
            # PR feedback: "Don't include types.h from headers - use forward declarations"
            if '#include' in content and 'types.h' in content and 'forward' not in content:
                self.warnings.append(StyleViolation(
                    "Consider using forward.h instead of types.h in headers",
                    file_path, line_num, severity="warning"
                ))

            # Check for .static.h includes in headers
            # PR feedback: ".static.h should only be included from .c files"
            if '#include' in content and '.static.h' in content:
                self.errors.append(StyleViolation(
                    ".static.h files should only be included from .c files",
                    file_path, line_num
                ))

        # =================================================================
        # C FILE-SPECIFIC CHECKS (only for .c files)
        # =================================================================

        if file_path.endswith(".c"):
            # Check for local extern declarations
            # PR feedback: "extern declarations should be avoided - prefer including headers"
            if re.match(r'^extern\s+(?:static\s+)?\w+[\w\s\*]*\s+\w+\s*[;\[]', stripped):
                if '(' not in content:  # Not a function declaration
                    self.warnings.append(StyleViolation(
                        "Local extern declaration - consider using header include",
                        file_path, line_num, severity="warning"
                    ))

            # Check for local sqrtf definition
            # PR feedback: "Include <math_ppc.h> instead of defining sqrtf locally"
            if re.match(r'^(extern|static)\s+.*\bsqrtf\b', stripped):
                self.errors.append(StyleViolation(
                    "Include <math_ppc.h> instead of defining sqrtf locally",
                    file_path, line_num
                ))

        # =================================================================
        # ITEM-SPECIFIC CHECKS
        # =================================================================

        # Check for 0xFFFFFFFF in tables (should use -1)
        # PR feedback: "use -1 instead of 0xFFFFFFFF in ItemStateTable"
        if '0xFFFFFFFF' in content:
            self.warnings.append(StyleViolation(
                "Consider using -1 instead of 0xFFFFFFFF (especially in ItemStateTable)",
                file_path, line_num, severity="warning"
            ))

        # =================================================================
        # EMPTY FUNCTION STYLE
        # =================================================================

        # Check for { return; } in void functions
        # PR feedback: "Empty void functions should use {} not { return; }"
        if re.search(r'void\s+\w+\s*\([^)]*\)\s*\{\s*return;\s*\}', content):
            self.warnings.append(StyleViolation(
                "Empty void functions should use {} not { return; }",
                file_path, line_num, severity="warning"
            ))

    def check_forbidden_files(self, files: list[str]) -> None:
        """Check for files that should never be modified."""
        forbidden_patterns = [
            r'^orig/',
            r'\.build_validated$',
            r'\.gitkeep$',
        ]

        for f in files:
            for pattern in forbidden_patterns:
                if re.search(pattern, f):
                    self.errors.append(StyleViolation(
                        f"File should not be modified: {f}",
                        f
                    ))
                    break

    def check_conflict_markers(self, file_path: str, content: str) -> None:
        """Check for merge conflict markers."""
        markers = ["<<<<<<<", "=======", ">>>>>>>"]
        for i, line in enumerate(content.split("\n"), 1):
            for marker in markers:
                if line.strip().startswith(marker):
                    self.errors.append(StyleViolation(
                        f"Merge conflict marker found: {marker}",
                        file_path, i
                    ))

    def check_include_guards(self, file_path: str, content: str) -> None:
        """Check for missing include guards in headers."""
        if file_path.endswith(".h"):
            if not re.search(r'#ifndef\s+\w+', content):
                self.errors.append(StyleViolation(
                    "Header missing include guard - use #ifndef/#define/#endif",
                    file_path
                ))

    def _derive_function_prefix(self, file_path: str) -> Optional[str]:
        """Derive expected function prefix from filename.

        Examples:
            mndiagram.c -> mnDiagram_
            itcapsule.c -> itCapsule_
            ftcommon.c -> ftCommon_

        Returns None if prefix cannot be determined.
        """
        # Known 2-letter module prefixes
        known_prefixes = {
            'mn', 'it', 'ft', 'lb', 'gr', 'gm', 'pl', 'cm', 'db',
            'ef', 'if', 'mp', 'sb', 'sc', 'ty', 'un', 'vi'
        }

        filename = Path(file_path).stem  # Remove .c extension
        if len(filename) < 3:
            return None

        # Try 2-letter prefix first
        if filename[:2].lower() in known_prefixes:
            module = filename[:2].lower()
            rest = filename[2:]
        # Try 3-letter prefix
        elif len(filename) >= 4 and filename[:3].lower() in {'col', 'map'}:
            module = filename[:3].lower()
            rest = filename[3:]
        else:
            # Default to 2-letter prefix
            module = filename[:2].lower()
            rest = filename[2:]

        if not rest:
            return None

        # Capitalize first letter of rest
        rest_capitalized = rest[0].upper() + rest[1:].lower()

        return f"{module}{rest_capitalized}_"

    def check_function_prefixes(self, file_path: str, content: str) -> None:
        """Check that non-static functions have the expected module prefix.

        PR feedback: "All non-static functions should be prefixed with the module name"
        """
        if not file_path.endswith(".c"):
            return

        expected_prefix = self._derive_function_prefix(file_path)
        if not expected_prefix:
            return

        # Extract module (first 2 letters) for shorthand prefixes
        module = expected_prefix.rstrip('_').lower()[:2]

        # Common shorthand prefixes (e.g., ftCo_ for ftCommon_)
        # Maps module to list of acceptable shortened forms
        shorthand_prefixes = {
            'ft': ['ftCo_', 'ftColl_'],  # ftCommon, ftCollision
            'it': ['itCo_'],  # itCommon
        }
        acceptable_prefixes = [expected_prefix, f"{module}_"]
        if module in shorthand_prefixes:
            acceptable_prefixes.extend(shorthand_prefixes[module])

        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # Skip if line is inside a comment or preprocessor
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('#'):
                continue
            if stripped.startswith('extern'):
                continue

            # Pattern: type funcname( at start of line, not static
            match = re.match(
                r'^(?!static\s)(?:\w+[\w\s\*]*?)\s+([A-Za-z_]\w*)\s*\(',
                line
            )
            if not match:
                continue

            func_name = match.group(1)

            # Skip known non-prefixed functions and standard library
            skip_names = {'main', 'fminf', 'fmaxf', 'sqrtf', 'fabsf', 'sinf', 'cosf'}
            if func_name in skip_names:
                continue

            # Skip underscore-prefixed inline helpers (e.g., _func_8007E2FC_inline)
            if func_name.startswith('_'):
                continue

            # Check if this is a function definition (has { nearby) not just declaration
            is_definition = False
            for j in range(i-1, min(i+4, len(lines))):
                if '{' in lines[j]:
                    is_definition = True
                    break
                if ';' in lines[j] and '{' not in lines[j]:
                    # This is a declaration, not definition
                    break

            if not is_definition:
                continue

            # Check if function has an acceptable prefix
            has_valid_prefix = any(func_name.startswith(p) for p in acceptable_prefixes)
            if not has_valid_prefix:
                self.warnings.append(StyleViolation(
                    f"Function '{func_name}' should be prefixed with '{expected_prefix}' or '{module}_'",
                    file_path, i, severity="warning"
                ))

    def check_static_ordering(self, file_path: str, content: str) -> None:
        """Check that static variable definitions appear before function definitions.

        PR feedback: "When linking, it's easier if these definitions are at the top of the file"
        """
        if not file_path.endswith(".c"):
            return

        lines = content.split('\n')
        first_func_line = None
        in_multiline_comment = False

        # Find the first function definition
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Track multiline comments
            if '/*' in stripped and '*/' not in stripped:
                in_multiline_comment = True
                continue
            if '*/' in stripped:
                in_multiline_comment = False
                continue
            if in_multiline_comment or stripped.startswith('//') or stripped.startswith('#'):
                continue

            # Look for function definition (type + name + open paren + has body nearby)
            # A function def has { on same line or next few lines
            if re.match(r'^(?:static\s+)?(?:\w+[\w\s\*]*?)\s+\w+\s*\([^;]*$', line):
                # Check if this is followed by a { within a few lines (function body)
                for j in range(i-1, min(i+4, len(lines))):
                    if '{' in lines[j]:
                        first_func_line = i
                        break
                if first_func_line:
                    break

        if not first_func_line:
            return

        # Now check for static variable definitions after first function
        in_multiline_comment = False
        for i, line in enumerate(lines[first_func_line:], first_func_line + 1):
            stripped = line.strip()

            # Track multiline comments
            if '/*' in stripped and '*/' not in stripped:
                in_multiline_comment = True
                continue
            if '*/' in stripped:
                in_multiline_comment = False
                continue
            if in_multiline_comment or stripped.startswith('//') or stripped.startswith('#'):
                continue

            # Look for static variable definitions (not functions)
            # Pattern: "static type name = " or "static type name;" or "static type name["
            static_var_match = re.match(
                r'^static\s+(?!inline\b)(\w+[\w\s\*]*?)\s+(\w+)\s*([=\[;])',
                stripped
            )
            if static_var_match:
                # Make sure it's not a function (no parentheses before = or ;)
                var_name = static_var_match.group(2)
                if '(' not in stripped.split('=')[0] if '=' in stripped else '(' not in stripped:
                    self.warnings.append(StyleViolation(
                        f"Static variable '{var_name}' defined after first function - consider moving to top of file",
                        file_path, i, severity="warning"
                    ))

    def run_on_staged(self) -> int:
        """Run checks on staged files.

        Returns:
            Exit code (0 = success, 1 = errors found)
        """
        staged_files = self.get_staged_files()
        if not staged_files:
            print("No staged files to check.")
            return 0

        # Check forbidden files
        self.check_forbidden_files(staged_files)

        # Check code files
        code_files = [f for f in staged_files if f.endswith((".c", ".h"))]

        for code_file in code_files:
            diff = self.get_staged_diff(code_file)
            if diff:
                self.check_file(code_file, diff)

            # Also check full file for some things
            full_path = self.project_root / code_file
            if full_path.exists():
                content = full_path.read_text()
                self.check_conflict_markers(code_file, content)
                if code_file.endswith(".h"):
                    self.check_include_guards(code_file, content)
                if code_file.endswith(".c"):
                    self.check_function_prefixes(code_file, content)
                    self.check_static_ordering(code_file, content)

        return self._print_results()

    def run_on_files(self, files: list[str]) -> int:
        """Run checks on specific files.

        Returns:
            Exit code (0 = success, 1 = errors found)
        """
        self.check_forbidden_files(files)

        for file_path in files:
            if file_path.endswith((".c", ".h")):
                full_path = Path(file_path)
                if not full_path.is_absolute():
                    full_path = self.project_root / file_path

                if full_path.exists():
                    content = full_path.read_text()
                    for i, line in enumerate(content.split("\n"), 1):
                        self._check_line(file_path, i, line)
                    self.check_conflict_markers(file_path, content)
                    if file_path.endswith(".h"):
                        self.check_include_guards(file_path, content)
                    if file_path.endswith(".c"):
                        self.check_function_prefixes(file_path, content)
                        self.check_static_ordering(file_path, content)

        return self._print_results()

    def _print_results(self) -> int:
        """Print results and return exit code."""
        if self.errors:
            print("\033[31mStyle errors (must fix):\033[0m")
            for e in self.errors:
                print(f"  \033[31m✗\033[0m {e}")

        if self.warnings:
            print("\n\033[33mWarnings (should review):\033[0m")
            for w in self.warnings:
                print(f"  \033[33m⚠\033[0m {w}")

        if self.errors:
            print(f"\n\033[31m{len(self.errors)} error(s) found\033[0m")
            print("See docs/STYLE_GUIDE.md for details on these conventions.")
            return 1
        elif self.warnings:
            print(f"\n\033[33m{len(self.warnings)} warning(s) - please review\033[0m")
            return 0
        else:
            print("\033[32m✓ No style issues found\033[0m")
            return 0


def main():
    parser = argparse.ArgumentParser(description="Check C/H files for style violations")
    parser.add_argument("files", nargs="*", help="Files to check (default: staged files)")
    parser.add_argument("--fix", action="store_true", help="Attempt to fix issues (not yet implemented)")
    args = parser.parse_args()

    checker = StyleChecker()

    if args.files:
        sys.exit(checker.run_on_files(args.files))
    else:
        sys.exit(checker.run_on_staged())


if __name__ == "__main__":
    main()
