"""
Advanced templates targeting specific opcode patterns that are
often tricky in decompilation.

These templates are designed to produce opcodes like:
- cntlzw, extrwi (boolean comparisons)
- xoris, lfd, fsubs (int-to-float conversion)
- crclr (variadic functions)
- lbz, lbzx, lhz (byte/halfword loads)
- rlwimi (bitfield insertion)
"""

from .templates import Template

# =============================================================================
# Boolean comparison patterns (produce cntlzw, extrwi, srwi)
# =============================================================================

BOOLEAN_TEMPLATES = [
    Template(
        name="bool_eq_to_u8",
        description="Equality comparison stored to u8 (produces cntlzw,extrwi)",
        code="""u8 selected;
    selected = ({a} == {b});
    *p = selected;""",
        slots={
            "a": ["x", "data[0]", "*p"],
            "b": ["y", "0", "idx"],
        },
    ),
    Template(
        name="bool_eq_as_arg",
        description="Equality comparison as function argument",
        code="""func4(ptr, (u8)idx, ({a} == {b}), 1);""",
        slots={
            "a": ["x", "data[0]"],
            "b": ["y", "idx", "0"],
        },
    ),
    Template(
        name="bool_ne_to_u8",
        description="Inequality to u8",
        code="""u8 selected;
    selected = ({a} != {b});
    *p = selected;""",
        slots={
            "a": ["x", "flags"],
            "b": ["0", "y"],
        },
    ),
    Template(
        name="bool_not",
        description="Logical not (produces cntlzw,srwi)",
        code="""u8 r;
    r = !{x};
    *p = r;""",
        slots={
            "x": ["x", "flag", "count"],
        },
    ),
    Template(
        name="bool_double_not",
        description="Double negation (coerce to bool)",
        code="""u8 r;
    r = !!{x};
    *p = r;""",
        slots={
            "x": ["x", "count"],
        },
    ),
]


# =============================================================================
# Integer-to-float conversion (produce xoris, lfd, fsubs with 0x4330 magic)
# =============================================================================

FLOAT_CONVERSION_TEMPLATES = [
    Template(
        name="int_to_float_cast",
        description="Integer to float cast (produces xoris,stw,lfd,fsubs)",
        code="""f32 f;
    f = (f32){x};
    func_f(f);""",
        slots={
            "x": ["i", "x", "count"],
        },
    ),
    Template(
        name="int_to_float_loop",
        description="Loop counter to float",
        code="""{type} i;
    f32 f;
    for (i = 0; i < n; i++) {{
        f = (f32)i;
        func_f(f);
    }}""",
        slots={},
        types=["s32"],
    ),
    Template(
        name="uint_to_float",
        description="Unsigned int to float",
        code="""f32 f;
    f = (f32)(u32){x};""",
        slots={
            "x": ["x", "count"],
        },
    ),
    Template(
        name="float_arithmetic",
        description="Float arithmetic operations",
        code="""f32 a, b, c;
    a = (f32)x;
    b = (f32)y;
    c = a {op} b;""",
        slots={
            "op": ["+", "-", "*", "/"],
        },
    ),
]


# =============================================================================
# Byte/halfword operations (produce lbz, lbzx, lhz, stb, sth)
# =============================================================================

BYTE_TEMPLATES = [
    Template(
        name="load_byte",
        description="Load byte from pointer",
        code="result = *((u8*){ptr});",
        slots={
            "ptr": ["p", "data", "ptr"],
        },
    ),
    Template(
        name="load_byte_offset",
        description="Load byte with offset",
        code="result = ((u8*){ptr})[{offset}];",
        slots={
            "ptr": ["p", "data"],
            "offset": ["0", "1", "i", "idx"],
        },
    ),
    Template(
        name="load_halfword",
        description="Load halfword",
        code="result = *((u16*){ptr});",
        slots={
            "ptr": ["p", "data"],
        },
    ),
    Template(
        name="store_byte",
        description="Store byte",
        code="*((u8*){ptr}) = {value};",
        slots={
            "ptr": ["p", "data"],
            "value": ["0", "x", "(u8)i"],
        },
    ),
    Template(
        name="byte_array_access",
        description="Byte array with index (produces lbzx)",
        code="""u8* arr;
    result = arr[{idx}];""",
        slots={
            "idx": ["i", "x", "offset"],
        },
    ),
    Template(
        name="struct_byte_field",
        description="Access byte field in struct",
        code="result = obj->byte_field;",
        slots={},
    ),
]


# =============================================================================
# Bitfield operations (produce rlwimi, rlwinm, extrwi, insrwi)
# =============================================================================

BITFIELD_ADVANCED_TEMPLATES = [
    Template(
        name="rlwimi_insert",
        description="Insert bits (produces rlwimi)",
        code="""flags = (flags & ~{mask}) | (({src} << {shift}) & {mask});""",
        slots={
            "mask": ["0xF0", "0xFF00", "0x0F"],
            "src": ["x", "n"],
            "shift": ["4", "8", "0"],
        },
    ),
    Template(
        name="rlwimi_byte_insert",
        description="Insert byte into word (produces rlwimi)",
        code="""u32 val;
    val = flags;
    val = (val & 0xFFFFFF00) | ((u32)byte_val & 0xFF);
    flags = val;""",
        slots={},
    ),
    Template(
        name="bitfield_extract",
        description="Extract bitfield",
        code="result = ({x} >> {shift}) & {mask};",
        slots={
            "x": ["flags", "n"],
            "shift": ["4", "8", "16"],
            "mask": ["0xF", "0xFF", "0x3"],
        },
    ),
    Template(
        name="sign_extend_byte",
        description="Sign extend byte to word",
        code="result = (s32)(s8){x};",
        slots={
            "x": ["byte_val", "*p"],
        },
    ),
    Template(
        name="sign_extend_half",
        description="Sign extend halfword to word",
        code="result = (s32)(s16){x};",
        slots={
            "x": ["half_val", "*p"],
        },
    ),
]


# =============================================================================
# Variadic functions (produce crclr)
# =============================================================================

VARIADIC_TEMPLATES = [
    Template(
        name="printf_call",
        description="Printf-style call (produces crclr)",
        code="""extern void OSReport(char*, ...);
    OSReport("value: %d", {arg});""",
        slots={
            "arg": ["x", "i", "count"],
        },
    ),
    Template(
        name="printf_multi_arg",
        description="Printf with multiple args",
        code="""extern void OSReport(char*, ...);
    OSReport("x=%d y=%d", {a}, {b});""",
        slots={
            "a": ["x", "i"],
            "b": ["y", "j"],
        },
    ),
    Template(
        name="printf_float",
        description="Printf with float arg (produces crclr, different ABI handling)",
        code="""extern void OSReport(char*, ...);
    f32 f;
    f = (f32)x;
    OSReport("f=%f", f);""",
        slots={},
    ),
]


# =============================================================================
# Address calculations (produce lis, addi pairs)
# =============================================================================

ADDRESS_TEMPLATES = [
    Template(
        name="global_access",
        description="Access global variable",
        code="result = g_value;",
        slots={},
    ),
    Template(
        name="global_write",
        description="Write global variable",
        code="g_value = {x};",
        slots={
            "x": ["0", "x", "result"],
        },
    ),
    Template(
        name="function_pointer",
        description="Call through function pointer",
        code="callback(x);",
        slots={},
    ),
]


# =============================================================================
# Indexed operations (produce lwzx, stbx, etc.)
# =============================================================================

INDEXED_TEMPLATES = [
    Template(
        name="indexed_word_load",
        description="Indexed word load (produces lwzx)",
        code="""s32* base;
    result = base[{idx}];""",
        slots={
            "idx": ["i", "offset", "x >> 2"],
        },
    ),
    Template(
        name="indexed_byte_load",
        description="Indexed byte load (produces lbzx)",
        code="""u8* base;
    result = base[{idx}];""",
        slots={
            "idx": ["i", "offset"],
        },
    ),
    Template(
        name="computed_offset",
        description="Computed offset access",
        code="""s32* base;
    s32 off;
    off = {idx} * 4;
    result = *(s32*)((u8*)base + off);""",
        slots={
            "idx": ["i", "x"],
        },
    ),
]


# =============================================================================
# Combined/complex patterns
# =============================================================================

COMPLEX_TEMPLATES = [
    Template(
        name="loop_with_byte_cmp",
        description="Loop comparing bytes (common in menus)",
        code="""{type} i;
    u8* data;
    for (i = 0; i < n; i++) {{
        u8 selected = (data[i] == target);
        func4(obj, (u8)i, selected, 1);
    }}""",
        slots={},
        types=["s32"],
    ),
    Template(
        name="float_array_init",
        description="Initialize float array",
        code="""{type} i;
    f32* arr;
    for (i = 0; i < n; i++) {{
        arr[i] = (f32)i;
    }}""",
        slots={},
        types=["s32"],
    ),
    Template(
        name="bitfield_loop",
        description="Loop setting bitfields",
        code="""{type} i;
    u32 flags;
    for (i = 0; i < 8; i++) {{
        if (data[i]) {{
            flags |= (1 << i);
        }}
    }}""",
        slots={},
        types=["s32"],
    ),
]


# =============================================================================
# Missing opcodes: fmr, sth, sthx, stbx, extlwi, subis
# =============================================================================

MISSING_OPCODE_TEMPLATES = [
    # fmr - floating point move register
    Template(
        name="float_copy",
        description="Float register copy (produces fmr)",
        code="""f32 a, b;
    a = (f32)x;
    b = a;
    func_f(b);""",
        slots={},
    ),
    Template(
        name="float_param_copy",
        description="Copy float parameter (produces fmr)",
        code="""f32 temp;
    temp = (f32)x;
    func_f(temp);
    func_f(temp);""",
        slots={},
    ),
    # sth - store halfword
    Template(
        name="store_halfword",
        description="Store halfword to pointer (produces sth)",
        code="""u16* dst;
    *dst = (u16){val};""",
        slots={
            "val": ["x", "0", "n"],
        },
    ),
    Template(
        name="store_halfword_offset",
        description="Store halfword with offset (produces sth)",
        code="""u16* dst;
    dst[{idx}] = (u16)x;""",
        slots={
            "idx": ["0", "1", "i"],
        },
    ),
    # sthx - store halfword indexed
    Template(
        name="store_halfword_indexed",
        description="Store halfword with computed index (produces sthx)",
        code="""u16* base;
    s32 off;
    off = i * 2;
    *(u16*)((u8*)base + off) = (u16)x;""",
        slots={},
    ),
    # stbx - store byte indexed (we have lbzx but not stbx)
    Template(
        name="store_byte_indexed",
        description="Store byte with computed index (produces stbx)",
        code="""u8* base;
    s32 off;
    off = i;
    *(u8*)((u8*)base + off) = (u8)x;""",
        slots={},
    ),
    # extlwi - extract and left justify (extract then shift left)
    Template(
        name="extract_left_justify",
        description="Extract bits and left justify (produces extlwi)",
        code="""result = ((flags >> {src_shift}) & {mask}) << {dst_shift};""",
        slots={
            "src_shift": ["8", "16", "4"],
            "mask": ["0xF", "0xFF"],
            "dst_shift": ["28", "24", "16"],
        },
    ),
    # subis - subtract immediate shifted (large negative values)
    Template(
        name="large_negative_const",
        description="Large negative constant (may produce subis/addis)",
        code="""s32 val;
    val = {const};
    result = x + val;""",
        slots={
            "const": ["-0x10000", "-0x20000", "-65536"],
        },
    ),
    Template(
        name="large_address_offset",
        description="Large address calculation",
        code="""s32* base;
    result = base[{idx}];""",
        slots={
            "idx": ["0x1000", "0x2000", "-0x1000"],
        },
    ),
]


# All advanced templates
ADVANCED_TEMPLATES = (
    BOOLEAN_TEMPLATES
    + FLOAT_CONVERSION_TEMPLATES
    + BYTE_TEMPLATES
    + BITFIELD_ADVANCED_TEMPLATES
    + VARIADIC_TEMPLATES
    + ADDRESS_TEMPLATES
    + INDEXED_TEMPLATES
    + COMPLEX_TEMPLATES
    + MISSING_OPCODE_TEMPLATES
)
