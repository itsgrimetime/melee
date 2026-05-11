"""
Translation unit context generators.

Generates realistic compilation contexts (complete .c files) that affect
how mwcc generates code. Different contexts produce different register
allocation and code patterns.
"""

import random
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Variable:
    """A variable declaration."""

    name: str
    type: str
    storage: str = ""  # "", "static", "extern"
    initial: str | None = None

    def declare(self) -> str:
        parts = [p for p in [self.storage, self.type, self.name] if p]
        decl = " ".join(parts)
        if self.initial:
            decl += f" = {self.initial}"
        return decl + ";"


@dataclass
class Function:
    """A function definition or declaration."""

    name: str
    return_type: str
    params: list[tuple]  # [(type, name), ...]
    body: str
    storage: str = ""  # "", "static", "inline", "extern"

    def render(self) -> str:
        param_str = ", ".join(f"{t} {n}" for t, n in self.params)
        storage = f"{self.storage} " if self.storage else ""

        # Extern functions are declarations only (no body)
        if self.storage == "extern":
            # K&R style: empty () allows any args, (void) means no args
            decl_params = param_str if param_str else ""
            return f"{self.return_type} {self.name}({decl_params});"

        # Non-extern functions need (void) for no params
        if not param_str:
            param_str = "void"

        return f"""{storage}{self.return_type} {self.name}({param_str}) {{
{self.body}
}}"""


@dataclass
class Struct:
    """A struct/typedef definition."""

    name: str
    fields: list[tuple]  # [(type, name), ...]

    def render(self) -> str:
        fields_str = "\n    ".join(f"{t} {n};" for t, n in self.fields)
        return f"""typedef struct {self.name} {{
    {fields_str}
}} {self.name};"""


@dataclass
class TranslationUnit:
    """A complete compilable .c file."""

    structs: list[Struct] = field(default_factory=list)
    globals: list[Variable] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    target_function: str | None = None  # The function we care about

    def render(self) -> str:
        parts = [
            "/* Auto-generated translation unit */",
            "",
            # Type definitions (C89 style)
            "typedef signed char s8;",
            "typedef signed short s16;",
            "typedef signed int s32;",
            "typedef unsigned char u8;",
            "typedef unsigned short u16;",
            "typedef unsigned int u32;",
            "typedef float f32;",
            "typedef double f64;",
            "",
        ]

        # Structs
        for struct in self.structs:
            parts.append(struct.render())
            parts.append("")

        # Global/extern declarations
        for var in self.globals:
            parts.append(var.declare())
        if self.globals:
            parts.append("")

        # Functions
        for func in self.functions:
            parts.append(func.render())
            parts.append("")

        return "\n".join(parts)


class ContextGenerator:
    """Base class for generating compilation contexts."""

    name: str = "base"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        raise NotImplementedError


class MinimalContext(ContextGenerator):
    """Minimal context - just types and target function."""

    name = "minimal"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        # Minimal external declarations that snippets might reference
        return TranslationUnit(
            globals=[
                Variable("arr", "s32*", "extern"),
                Variable("src", "s32*", "extern"),
                Variable("dst", "s32*", "extern"),
                Variable("p", "s32*", "extern"),
                Variable("ptr", "void*", "extern"),
                Variable("n", "s32", "extern"),
                Variable("count", "s32", "extern"),
                Variable("x", "s32", "extern"),
                Variable("y", "s32", "extern"),
                Variable("a", "s32", "extern"),
                Variable("b", "s32", "extern"),
                Variable("c", "s32", "extern"),
                Variable("d", "s32", "extern"),
                Variable("sum", "s32", "extern"),
                Variable("result", "s32", "extern"),
                Variable("flags", "u32", "extern"),
                Variable("mask", "u32", "extern"),
                Variable("min", "s32", "extern"),
                Variable("max", "s32", "extern"),
                Variable("flag", "s32", "extern"),
                Variable("err", "s32", "extern"),
                Variable("failed", "s32", "extern"),
                Variable("state", "s32", "extern"),
                Variable("value", "s32", "extern"),
                Variable("cmd", "s32", "extern"),
                Variable("v", "s32", "extern"),
                Variable("new_val", "s32", "extern"),
                Variable("default_val", "s32", "extern"),
                Variable("min_val", "s32", "extern"),
                Variable("max_val", "s32", "extern"),
                Variable("total", "s32", "extern"),
                Variable("diff", "s32", "extern"),
                Variable("i", "s32", "extern"),
            ],
            functions=[
                Function("func", "void", [("s32", "x")], "    /* extern */", "extern"),
                Function("do_thing", "void", [], "    /* extern */", "extern"),
                Function("handle_a", "void", [], "    /* extern */", "extern"),
                Function("handle_b", "void", [], "    /* extern */", "extern"),
                Function("handle_c", "void", [], "    /* extern */", "extern"),
                Function(target_name, "void", [], f"    {target_snippet}"),
            ],
            target_function=target_name,
        )


class WithStructsContext(ContextGenerator):
    """Context with struct definitions for struct-related templates."""

    name = "with_structs"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        basic_struct = Struct(
            "BasicObj",
            [
                ("s32", "x"),
                ("s32", "y"),
                ("s32", "state"),
                ("s32", "value"),
                ("u32", "flags"),
                ("s32", "data[8]"),
            ],
        )

        nested_struct = Struct(
            "InnerData",
            [
                ("s32", "x"),
                ("s32", "value"),
                ("s32", "count"),
            ],
        )

        outer_struct = Struct(
            "OuterObj",
            [
                ("InnerData*", "inner"),
                ("InnerData*", "data"),
                ("InnerData*", "state"),
                ("s32", "x"),
            ],
        )

        linked_struct = Struct(
            "LinkedNode",
            [
                ("struct LinkedNode*", "next"),
                ("struct LinkedNode*", "link"),
                ("s32", "value"),
            ],
        )

        return TranslationUnit(
            structs=[basic_struct, nested_struct, outer_struct, linked_struct],
            globals=[
                Variable("ptr", "BasicObj*", "extern"),
                Variable("obj", "OuterObj*", "extern"),
                Variable("this", "BasicObj*", "extern"),
                Variable("node", "LinkedNode*", "extern"),
                Variable("cur", "LinkedNode*", "extern"),
                Variable("p", "LinkedNode*", "extern"),
                Variable("result", "s32", "extern"),
                Variable("n", "s32", "extern"),
                Variable("i", "s32", "extern"),
                Variable("count", "s32", "extern"),
                Variable("sum", "s32", "extern"),
                Variable("v", "s32", "extern"),
                Variable("x", "s32", "extern"),
                Variable("flags", "u32", "extern"),
            ],
            functions=[
                # Note: extern functions are declarations only (no body)
                Function("func", "void", [("s32", "x")], "", "extern"),
                Function(target_name, "void", [], f"    {target_snippet}"),
            ],
            target_function=target_name,
        )


class WithHelpersContext(ContextGenerator):
    """Context with helper functions that may get inlined."""

    name = "with_helpers"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        helpers = [
            Function("helper_get", "s32", [("s32*", "p")], "    return *p;", "static inline"),
            Function("helper_set", "void", [("s32*", "p"), ("s32", "v")], "    *p = v;", "static inline"),
            Function("helper_add", "s32", [("s32", "a"), ("s32", "b")], "    return a + b;", "static inline"),
            Function(
                "helper_clamp",
                "s32",
                [("s32", "x"), ("s32", "lo"), ("s32", "hi")],
                "    if (x < lo) return lo;\n    if (x > hi) return hi;\n    return x;",
                "static",
            ),
            Function("helper_abs", "s32", [("s32", "x")], "    return x < 0 ? -x : x;", "static inline"),
            Function("helper_min", "s32", [("s32", "a"), ("s32", "b")], "    return a < b ? a : b;", "static inline"),
            Function("helper_max", "s32", [("s32", "a"), ("s32", "b")], "    return a > b ? a : b;", "static inline"),
        ]

        return TranslationUnit(
            globals=[
                Variable("arr", "s32*", "extern"),
                Variable("n", "s32", "extern"),
                Variable("count", "s32", "extern"),
                Variable("x", "s32", "extern"),
                Variable("y", "s32", "extern"),
                Variable("result", "s32", "extern"),
                Variable("sum", "s32", "extern"),
                Variable("p", "s32*", "extern"),
                Variable("src", "s32*", "extern"),
                Variable("dst", "s32*", "extern"),
            ],
            functions=[
                *helpers,
                Function("func", "void", [("s32", "x")], "    /* extern */", "extern"),
                Function("do_thing", "void", [], "    /* extern */", "extern"),
                Function(target_name, "void", [], f"    {target_snippet}"),
            ],
            target_function=target_name,
        )


class GameLikeContext(ContextGenerator):
    """Context mimicking typical Melee code structure."""

    name = "game_like"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        # GObj-like structure
        gobj = Struct(
            "GObj",
            [
                ("struct GObj*", "next"),
                ("struct GObj*", "prev"),
                ("void*", "data"),
                ("s32", "kind"),
                ("u32", "flags"),
            ],
        )

        # Fighter/Entity-like structure
        entity = Struct(
            "Entity",
            [
                ("f32", "pos_x"),
                ("f32", "pos_y"),
                ("f32", "pos_z"),
                ("f32", "vel_x"),
                ("f32", "vel_y"),
                ("f32", "vel_z"),
                ("s32", "state"),
                ("s32", "timer"),
                ("s32", "frame"),
                ("u32", "flags"),
                ("void*", "data"),
            ],
        )

        # State info
        state_info = Struct(
            "StateInfo",
            [
                ("s32", "id"),
                ("s32", "frame"),
                ("s32", "substate"),
                ("void*", "callback"),
            ],
        )

        return TranslationUnit(
            structs=[gobj, entity, state_info],
            globals=[
                Variable("gp", "Entity*", "extern"),
                Variable("fp", "Entity*", "extern"),
                Variable("gobj", "GObj*", "extern"),
                Variable("state_table", "StateInfo*", "extern"),
                Variable("frame_count", "s32", "extern"),
                Variable("result", "s32", "extern"),
                Variable("n", "s32", "extern"),
                Variable("i", "s32", "extern"),
                Variable("x", "s32", "extern"),
                Variable("y", "s32", "extern"),
                Variable("count", "s32", "extern"),
                Variable("sum", "s32", "extern"),
                Variable("flags", "u32", "extern"),
                Variable("state", "s32", "extern"),
            ],
            functions=[
                Function("get_state", "s32", [("Entity*", "e")], "    return e->state;", "static inline"),
                Function("set_state", "void", [("Entity*", "e"), ("s32", "s")], "    e->state = s;", "static inline"),
                Function("func", "void", [("s32", "x")], "    /* extern */", "extern"),
                Function("do_thing", "void", [], "    /* extern */", "extern"),
                Function("handle_a", "void", [], "    /* extern */", "extern"),
                Function("handle_b", "void", [], "    /* extern */", "extern"),
                Function("handle_c", "void", [], "    /* extern */", "extern"),
                Function(target_name, "void", [("Entity*", "entity")], f"    {target_snippet}"),
            ],
            target_function=target_name,
        )


class WithStaticsContext(ContextGenerator):
    """Context with static variables (affects addressing modes)."""

    name = "with_statics"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        return TranslationUnit(
            globals=[
                # Static variables
                Variable("s_counter", "s32", "static", "0"),
                Variable("s_buffer[32]", "s32", "static"),  # Array syntax in name
                Variable("s_flags", "u32", "static", "0"),
                Variable("s_ptr", "s32*", "static", "0"),
                # Extern variables
                Variable("arr", "s32*", "extern"),
                Variable("n", "s32", "extern"),
                Variable("x", "s32", "extern"),
                Variable("result", "s32", "extern"),
                Variable("sum", "s32", "extern"),
                Variable("count", "s32", "extern"),
                Variable("flags", "u32", "extern"),
                Variable("i", "s32", "extern"),
            ],
            functions=[
                Function("func", "void", [("s32", "x")], "    /* extern */", "extern"),
                Function("do_thing", "void", [], "    /* extern */", "extern"),
                Function(target_name, "void", [], f"    {target_snippet}"),
            ],
            target_function=target_name,
        )


class AdvancedContext(ContextGenerator):
    """Context with declarations for advanced templates (floats, bytes, variadic, etc.)."""

    name = "advanced"

    def generate(self, target_snippet: str, target_name: str = "target_func") -> TranslationUnit:
        # Struct with byte fields
        byte_struct = Struct(
            "ByteData",
            [
                ("u8", "byte_field"),
                ("u8", "bytes[8]"),
                ("u16", "half_val"),
                ("s32", "value"),
            ],
        )

        return TranslationUnit(
            structs=[byte_struct],
            globals=[
                # Basic types
                Variable("x", "s32", "extern"),
                Variable("y", "s32", "extern"),
                Variable("i", "s32", "extern"),
                Variable("j", "s32", "extern"),
                Variable("n", "s32", "extern"),
                Variable("count", "s32", "extern"),
                Variable("idx", "s32", "extern"),
                Variable("offset", "s32", "extern"),
                Variable("result", "s32", "extern"),  # Renamed to avoid collision
                Variable("flag", "s32", "extern"),
                Variable("flags", "u32", "extern"),
                Variable("target", "u8", "extern"),
                Variable("byte_val", "u8", "extern"),
                Variable("half_val", "s16", "extern"),
                # Pointers
                Variable("p", "u8*", "extern"),
                Variable("data", "u8*", "extern"),
                Variable("ptr", "void*", "extern"),
                Variable("obj", "ByteData*", "extern"),
                # Globals (will produce lis/addi)
                Variable("g_value", "s32"),
                # Note: function pointers need special handling
            ],
            functions=[
                # Standard functions
                Function("func", "void", [("s32", "x")], "", "extern"),
                Function("func_f", "void", [("f32", "f")], "", "extern"),
                Function("func4", "void", [("void*", "a"), ("u8", "b"), ("u8", "c"), ("s32", "d")], "", "extern"),
                # Variadic (OSReport) - use K&R style (no prototype) to allow variadic calls
                Function("OSReport", "void", [], "", "extern"),
                Function(target_name, "void", [], f"    {target_snippet}"),
            ],
            target_function=target_name,
        )


# All available context generators
ALL_CONTEXTS = [
    MinimalContext(),
    WithStructsContext(),
    WithHelpersContext(),
    GameLikeContext(),
    WithStaticsContext(),
    AdvancedContext(),
]


def get_context_by_name(name: str) -> ContextGenerator | None:
    """Get a context generator by name."""
    for ctx in ALL_CONTEXTS:
        if ctx.name == name:
            return ctx
    return None


def get_all_context_names() -> list[str]:
    """Get names of all available contexts."""
    return [ctx.name for ctx in ALL_CONTEXTS]
