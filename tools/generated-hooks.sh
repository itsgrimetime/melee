#!/bin/bash
# Pre-commit hooks for melee decompilation
# Generated from PR feedback analysis

set -e

# Get list of staged C files
STAGED_C_FILES=$(git diff --cached --name-only --diff-filter=ACMR | grep -E "\.(c|h)$" || true)

if [ -z "$STAGED_C_FILES" ]; then
    exit 0
fi

# raw_pointer_arithmetic (9 occurrences in PR feedback)
# Using raw pointer arithmetic instead of proper struct field access or M2C_FIELD macro
# Check for raw pointer arithmetic patterns
git diff --cached -- '*.c' | grep -E '\*(.*\*)\(\(char\*\)' && echo "ERROR: Use M2C_FIELD or proper struct fields"
git diff --cached -- '*.c' | grep -E '\*(.*\*)\(\(u8\*\)' && echo "ERROR: Use M2C_FIELD or proper struct fields"

# true_false_case (2 occurrences in PR feedback)
# Using TRUE/FALSE macros instead of lowercase true/false
# Check for TRUE/FALSE usage (should use true/false)
git diff --cached -- '*.c' '*.h' | grep -E '^\+.*\b(TRUE|FALSE)\b' && echo "ERROR: Use lowercase true/false instead of TRUE/FALSE"

# unnecessary_casts (3 occurrences in PR feedback)
# Unnecessary casts, especially HSD_GObj casts - fix argument types instead
# Check for suspicious HSD_GObj casts that might indicate wrong types
git diff --cached -- '*.c' | grep -E '^\+.*(HSD_GObj\s*\*)' | grep -v 'user_data' && echo "WARNING: Check if HSD_GObj cast is necessary"

# local_extern_declarations (3 occurrences in PR feedback)
# Using local extern declarations instead of including proper headers
# Flag new extern declarations in .c files (should use headers)
git diff --cached -- '*.c' | grep -E '^\+\s*extern\s+' && echo "WARNING: Consider using header includes instead of local extern"

# struct_naming (1 occurrences in PR feedback)
# Struct names should not be prefixed with underscores
# Check for underscore-prefixed struct names
git diff --cached -- '*.h' | grep -E '^\+.*struct\s+_' && echo "ERROR: Don't prefix struct names with underscores"

# struct_field_missing (6 occurrences in PR feedback)
# Struct needs a new field added instead of using offset arithmetic
# Check for suspicious offset patterns that should be struct fields
git diff --cached -- '*.c' | grep -E '^\+.*->\s*0x[0-9a-fA-F]+' && echo "WARNING: Consider adding struct field instead of offset"

# include_path_style (2 occurrences in PR feedback)
# Headers should use angle brackets with full paths, .c files can use relative
# Check for relative includes in headers (should use angle brackets)
git diff --cached -- '*.h' | grep -E '^\+\s*#include\s+"' && echo "WARNING: Headers should use angle bracket includes with full paths"

# types_h_in_header (5 occurrences in PR feedback)
# Don't include types.h from headers - use forward declarations instead
# Check for types.h includes in headers
git diff --cached -- '*.h' | grep -E '^\+.*#include.*types\.h' && echo "WARNING: Use forward declarations instead of including types.h in headers"

# static_h_in_header (1 occurrences in PR feedback)
# .static.h files should only be included from .c files
# Check for .static.h includes in headers
git diff --cached -- '*.h' | grep -E '^\+.*#include.*\.static\.h' && echo "ERROR: .static.h should only be included from .c files"

# missing_include_guard (2 occurrences in PR feedback)
# All headers need include guards
# Check for missing include guards in headers
for f in $(git diff --cached --name-only -- '*.h'); do
    if ! grep -q '#ifndef' "$f"; then
        echo "ERROR: $f missing include guard"
    fi
done

# empty_function_style (2 occurrences in PR feedback)
# Empty void functions should use {} not { return; }
# Check for { return; } in void functions
git diff --cached -- '*.c' | grep -E '^\+.*void.*\{\s*return;\s*\}' && echo "WARNING: Empty void functions should use {} not { return; }"

# stack_padding_macro (2 occurrences in PR feedback)
# Use PAD_STACK(n) instead of manual stack padding variables
# Check for manual stack padding patterns
git diff --cached -- '*.c' | grep -E '^\+.*int\s+_?pad|\+.*\(void\)\s*_?pad' && echo "WARNING: Use PAD_STACK macro instead of manual padding"

# use_int_not_s32 (2 occurrences in PR feedback)
# Use int (or bool) instead of s32, use UNK_T instead of M2C_UNK
# Check for s32 and M2C_UNK usage
git diff --cached -- '*.c' '*.h' | grep -E '^\+.*(\bs32\b|M2C_UNK)' && echo "WARNING: Use int instead of s32, UNK_T instead of M2C_UNK"

# math_header_include (1 occurrences in PR feedback)
# Include <math_ppc.h> for math functions instead of defining locally
# Check for local sqrtf definitions
git diff --cached -- '*.c' | grep -E '^\+.*(extern|static).*sqrtf' && echo "ERROR: Include <math_ppc.h> instead of defining sqrtf locally"

# item_state_table (2 occurrences in PR feedback)
# ItemStateTable: use -1 instead of 0xFFFFFFFF, infer types from position
# Check for 0xFFFFFFFF in ItemStateTable
git diff --cached -- '*.c' | grep -E '^\+.*0xFFFFFFFF' && echo "WARNING: Use -1 instead of 0xFFFFFFFF in ItemStateTable"

# symbol_rename_mismatch (1 occurrences in PR feedback)
# When renaming in symbols.txt, also rename the function definition
# CI check: symbol renames should include function definition renames
