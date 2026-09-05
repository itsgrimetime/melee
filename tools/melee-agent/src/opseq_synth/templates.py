"""
Template definitions for C code synthesis.

Templates are parameterized C code patterns that get expanded into
many variations for compilation and opcode extraction.

Note: mwcc is C89, so no C99 features (no for-loop declarations, no // comments in generated code)
"""

from dataclasses import dataclass, field
from itertools import product
from typing import Dict, List, Optional


@dataclass
class Template:
    """A parameterized C code template."""

    name: str
    code: str  # Template with {slot} placeholders
    slots: dict[str, list[str]]  # slot_name -> possible values
    types: list[str] | None = None  # Type variations to try (replaces {type})
    description: str = ""

    def expand(self) -> list[str]:
        """Generate all combinations for this template."""
        slot_names = list(self.slots.keys())
        slot_values = [self.slots[name] for name in slot_names]

        results = []
        for combination in product(*slot_values):
            code = self.code
            for name, value in zip(slot_names, combination):
                code = code.replace(f"{{{name}}}", value)

            # Handle type variations
            if self.types and "{type}" in code:
                for t in self.types:
                    typed_code = code.replace("{type}", t)
                    results.append(typed_code)
            else:
                results.append(code)

        return results

    def count(self) -> int:
        """Count total combinations for this template."""
        count = 1
        for values in self.slots.values():
            count *= len(values)
        if self.types:
            count *= len(self.types)
        return count


# =============================================================================
# Loop templates
# =============================================================================

LOOP_TEMPLATES = [
    Template(
        name="for_lt_inc",
        description="For loop with < comparison and increment",
        code="""{type} i;
    for (i = {init}; i < {bound}; {step}) {{
        {body}
    }}""",
        slots={
            "init": ["0", "1"],
            "bound": ["n", "count"],
            "step": ["i++", "++i", "i += 1"],
            "body": ["sum += arr[i];", "func(i);", "*dst++ = *src++;"],
        },
        types=["s32", "u32", "s16"],
    ),
    Template(
        name="for_le_inc",
        description="For loop with <= comparison",
        code="""{type} i;
    for (i = {init}; i <= {bound}; {step}) {{
        {body}
    }}""",
        slots={
            "init": ["0"],
            "bound": ["n", "n - 1", "count - 1"],
            "step": ["i++", "++i"],
            "body": ["sum += arr[i];", "func(i);"],
        },
        types=["s32", "u32"],
    ),
    Template(
        name="for_gt_dec",
        description="For loop counting down with > comparison",
        code="""{type} i;
    for (i = {init}; i > {bound}; {step}) {{
        {body}
    }}""",
        slots={
            "init": ["n", "n - 1", "count - 1"],
            "bound": ["0", "-1"],
            "step": ["i--", "--i", "i -= 1"],
            "body": ["sum += arr[i];", "func(i);"],
        },
        types=["s32", "s16"],
    ),
    Template(
        name="for_ge_dec",
        description="For loop counting down with >= comparison",
        code="""{type} i;
    for (i = {init}; i >= {bound}; {step}) {{
        {body}
    }}""",
        slots={
            "init": ["n - 1", "count - 1"],
            "bound": ["0"],
            "step": ["i--", "--i"],
            "body": ["sum += arr[i];", "func(i);"],
        },
        types=["s32"],
    ),
    Template(
        name="for_ne",
        description="For loop with != comparison",
        code="""{type} i;
    for (i = {init}; i != {bound}; {step}) {{
        {body}
    }}""",
        slots={
            "init": ["0", "n"],
            "bound": ["n", "0"],
            "step": ["i++", "i--"],
            "body": ["sum += arr[i];", "func(i);"],
        },
        types=["s32", "u32"],
    ),
    Template(
        name="while_decrement",
        description="While loop with decrementing counter",
        code="""while ({cond}) {{
        {body}
        {step}
    }}""",
        slots={
            "cond": ["n > 0", "n != 0", "n-- > 0", "--n >= 0"],
            "body": ["*dst++ = *src++;", "func(*p++);", "sum += *p++;"],
            "step": ["", "n--;", "p++;"],
        },
    ),
    Template(
        name="do_while",
        description="Do-while loop",
        code="""do {{
        {body}
    }} while ({cond});""",
        slots={
            "body": ["*dst++ = *src++;", "sum += arr[i]; i++;", "func(i); i++;"],
            "cond": ["--n > 0", "n-- > 0", "++i < count", "i++ < count"],
        },
    ),
    Template(
        name="while_ptr",
        description="While loop with pointer traversal",
        code="""while ({ptr} != NULL) {{
        {body}
        {ptr} = {ptr}->{next};
    }}""",
        slots={
            "ptr": ["p", "node", "cur"],
            "body": ["func(p);", "sum += p->value;", "count++;"],
            "next": ["next", "link"],
        },
    ),
]


# =============================================================================
# Branch/comparison templates
# =============================================================================

BRANCH_TEMPLATES = [
    Template(
        name="if_else",
        description="Simple if-else",
        code="""if ({cond}) {{
        {body_true}
    }} else {{
        {body_false}
    }}""",
        slots={
            "cond": ["x == 0", "x < 0", "x > 0", "x != 0", "x & 1", "flag"],
            "body_true": ["return a;", "result = a;", "func();"],
            "body_false": ["return b;", "result = b;"],
        },
    ),
    Template(
        name="if_else_if",
        description="If-else-if chain",
        code="""if ({cond1}) {{
        {body1}
    }} else if ({cond2}) {{
        {body2}
    }} else {{
        {body3}
    }}""",
        slots={
            "cond1": ["x == 0", "x < 0", "x > 0"],
            "cond2": ["x == 1", "x < n", "x > n"],
            "body1": ["return 0;", "result = a;"],
            "body2": ["return 1;", "result = b;"],
            "body3": ["return -1;", "result = c;"],
        },
    ),
    Template(
        name="ternary",
        description="Ternary conditional",
        code="result = {cond} ? {true_val} : {false_val};",
        slots={
            "cond": ["x > 0", "x == 0", "x < y", "x & mask", "flag"],
            "true_val": ["a", "x + 1", "*p", "1"],
            "false_val": ["b", "0", "default_val", "-1"],
        },
    ),
    Template(
        name="and_chain",
        description="Logical AND chain",
        code="""if ({c1} && {c2}) {{
        {body}
    }}""",
        slots={
            "c1": ["x > 0", "x >= min", "ptr != NULL", "flag"],
            "c2": ["x < max", "y > 0", "count > 0"],
            "body": ["return 1;", "result = x;", "do_thing();"],
        },
    ),
    Template(
        name="or_chain",
        description="Logical OR chain",
        code="""if ({c1} || {c2}) {{
        {body}
    }}""",
        slots={
            "c1": ["x == 0", "x < 0", "err"],
            "c2": ["y == 0", "ptr == NULL", "failed"],
            "body": ["return -1;", "result = -1;"],
        },
    ),
    Template(
        name="nested_ternary",
        description="Nested ternary (common in decompiled code)",
        code="result = {c1} ? {v1} : {c2} ? {v2} : {v3};",
        slots={
            "c1": ["x < 0", "x == 0"],
            "c2": ["x > 0", "x > y"],
            "v1": ["-1", "a"],
            "v2": ["1", "b"],
            "v3": ["0", "c"],
        },
    ),
]


# =============================================================================
# Switch templates
# =============================================================================

SWITCH_TEMPLATES = [
    Template(
        name="switch_dense_4",
        description="Dense switch with 4 cases",
        code="""switch ({expr}) {{
        case 0: {case0}
        case 1: {case1}
        case 2: {case2}
        case 3: {case3}
        default: {default}
    }}""",
        slots={
            "expr": ["x", "x & 3", "state"],
            "case0": ["return a;", "result = 0; break;"],
            "case1": ["return b;", "result = 1; break;"],
            "case2": ["return c;", "result = 2; break;"],
            "case3": ["return d;", "result = 3; break;"],
            "default": ["return -1;", "break;"],
        },
    ),
    Template(
        name="switch_sparse",
        description="Sparse switch (values not contiguous)",
        code="""switch ({expr}) {{
        case {v0}: {case0}
        case {v1}: {case1}
        case {v2}: {case2}
        default: {default}
    }}""",
        slots={
            "expr": ["x", "cmd"],
            "v0": ["0", "1"],
            "v1": ["5", "10", "0x10"],
            "v2": ["100", "255"],
            "case0": ["return a;", "handle_a(); break;"],
            "case1": ["return b;", "handle_b(); break;"],
            "case2": ["return c;", "handle_c(); break;"],
            "default": ["return -1;", "break;"],
        },
    ),
    Template(
        name="switch_fallthrough",
        description="Switch with fallthrough cases",
        code="""switch ({expr}) {{
        case 0:
        case 1:
            {body01}
        case 2:
            {body2}
        default:
            {default}
    }}""",
        slots={
            "expr": ["x", "state"],
            "body01": ["a = 1;", "func();"],
            "body2": ["b = 2; break;", "return;"],
            "default": ["break;", "c = 0; break;"],
        },
    ),
]


# =============================================================================
# Bitfield/masking templates
# =============================================================================

BITFIELD_TEMPLATES = [
    Template(
        name="mask_and_shift_right",
        description="Extract bits with shift and mask",
        code="result = ({expr} >> {shift}) & {mask};",
        slots={
            "expr": ["x", "value", "flags"],
            "shift": ["0", "4", "8", "16", "24"],
            "mask": ["0xF", "0xFF", "0x1", "0x3", "0x7"],
        },
    ),
    Template(
        name="mask_and_shift_left",
        description="Shift left then mask",
        code="result = ({expr} << {shift}) & {mask};",
        slots={
            "expr": ["x", "value"],
            "shift": ["1", "2", "4", "8"],
            "mask": ["0xFF", "0xFFFF", "0x100"],
        },
    ),
    Template(
        name="set_bits",
        description="Set specific bits",
        code="{target} = ({target} & ~{mask}) | ({value} & {mask});",
        slots={
            "target": ["x", "flags"],
            "mask": ["0xF", "0xFF", "0x1", "0x80"],
            "value": ["v", "new_val", "1"],
        },
    ),
    Template(
        name="clear_bits",
        description="Clear specific bits",
        code="{target} &= ~{mask};",
        slots={
            "target": ["x", "flags"],
            "mask": ["0x1", "0x80", "0xFF", "0xF"],
        },
    ),
    Template(
        name="test_bit",
        description="Test a bit and branch",
        code="""if ({expr} & {mask}) {{
        {body}
    }}""",
        slots={
            "expr": ["flags", "x", "state"],
            "mask": ["1", "0x80", "0x100", "0x8000"],
            "body": ["return 1;", "result = a;", "do_thing();"],
        },
    ),
    Template(
        name="rlwinm_pattern",
        description="Rotate and mask (maps to rlwinm)",
        code="result = (x << {shift}) | (x >> (32 - {shift}));",
        slots={
            "shift": ["1", "4", "8", "16"],
        },
    ),
]


# =============================================================================
# Struct/pointer templates
# =============================================================================

STRUCT_TEMPLATES = [
    Template(
        name="struct_read",
        description="Read struct member",
        code="result = {base}->{field};",
        slots={
            "base": ["ptr", "obj", "this"],
            "field": ["x", "state", "value", "flags", "data"],
        },
    ),
    Template(
        name="struct_write",
        description="Write struct member",
        code="{base}->{field} = {value};",
        slots={
            "base": ["ptr", "obj", "this"],
            "field": ["x", "state", "value", "flags"],
            "value": ["0", "v", "x + 1", "result"],
        },
    ),
    Template(
        name="struct_array_read",
        description="Read from array in struct",
        code="result = {base}->{array}[{index}];",
        slots={
            "base": ["ptr", "obj"],
            "array": ["data", "items", "values"],
            "index": ["i", "0", "n - 1"],
        },
    ),
    Template(
        name="nested_struct",
        description="Nested struct access",
        code="result = {base}->{mid}->{field};",
        slots={
            "base": ["ptr", "obj"],
            "mid": ["inner", "data", "state"],
            "field": ["x", "value", "count"],
        },
    ),
    Template(
        name="offset_cast",
        description="Offset and cast (common in Melee)",
        code="result = *({type}*)((u8*){base} + {offset});",
        slots={
            "base": ["ptr", "obj"],
            "offset": ["0x10", "0x20", "0x40", "0x100"],
        },
        types=["s32", "f32", "u32"],
    ),
]


# =============================================================================
# Arithmetic templates
# =============================================================================

ARITHMETIC_TEMPLATES = [
    Template(
        name="add_sub",
        description="Basic arithmetic",
        code="result = {a} {op} {b};",
        slots={
            "a": ["x", "a", "*p"],
            "op": ["+", "-"],
            "b": ["y", "1", "n"],
        },
    ),
    Template(
        name="multiply",
        description="Multiplication",
        code="result = {a} * {b};",
        slots={
            "a": ["x", "a"],
            "b": ["y", "2", "4", "n"],
        },
    ),
    Template(
        name="divide",
        description="Division",
        code="result = {a} / {b};",
        slots={
            "a": ["x", "total"],
            "b": ["y", "2", "4", "n"],
        },
    ),
    Template(
        name="modulo",
        description="Modulo operation",
        code="result = {a} % {b};",
        slots={
            "a": ["x", "i"],
            "b": ["n", "4", "8", "16"],
        },
    ),
    Template(
        name="clamp",
        description="Clamp value to range",
        code="""if ({x} < {min}) {{ {x} = {min}; }}
    if ({x} > {max}) {{ {x} = {max}; }}""",
        slots={
            "x": ["x", "value", "result"],
            "min": ["0", "min_val", "-100"],
            "max": ["100", "max_val", "255"],
        },
    ),
    Template(
        name="abs",
        description="Absolute value",
        code="result = {x} < 0 ? -{x} : {x};",
        slots={
            "x": ["x", "value", "diff"],
        },
    ),
    Template(
        name="min_max",
        description="Min/max selection",
        code="result = {a} {cmp} {b} ? {a} : {b};",
        slots={
            "a": ["x", "a"],
            "b": ["y", "b"],
            "cmp": ["<", ">"],
        },
    ),
]


# =============================================================================
# All templates
# =============================================================================

ALL_TEMPLATES = (
    LOOP_TEMPLATES + BRANCH_TEMPLATES + SWITCH_TEMPLATES + BITFIELD_TEMPLATES + STRUCT_TEMPLATES + ARITHMETIC_TEMPLATES
)


def get_templates_by_category(category: str) -> list[Template]:
    """Get templates by category name."""
    categories = {
        "loops": LOOP_TEMPLATES,
        "branches": BRANCH_TEMPLATES,
        "switches": SWITCH_TEMPLATES,
        "bitfields": BITFIELD_TEMPLATES,
        "structs": STRUCT_TEMPLATES,
        "arithmetic": ARITHMETIC_TEMPLATES,
        "all": ALL_TEMPLATES,
    }
    return categories.get(category, [])


def count_all_combinations() -> int:
    """Count total combinations across all templates."""
    return sum(t.count() for t in ALL_TEMPLATES)
