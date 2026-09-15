#!/usr/bin/env python3
"""
data-layout.py - Analyze DOL data layout and generate struct definitions

Usage:
    python data-layout.py <symbol_prefix> [--melee-root <path>]
    python data-layout.py mnDataDel_803EF8
    python data-layout.py --address 0x803EF870 --size 0x100

This tool:
1. Reads symbols from config/GALE01/symbols.txt
2. Reads actual data from build/GALE01/main.dol
3. Analyzes the data to infer types (floats, ints, strings, pointers)
4. Generates C struct definitions matching the layout
"""

import argparse
import struct
import re
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

@dataclass
class Symbol:
    name: str
    address: int
    size: int
    section: str
    scope: str
    data_type: Optional[str] = None

@dataclass
class DOLSection:
    name: str
    address: int
    size: int
    file_offset: int

def parse_symbols(symbols_path: Path, prefix: str = None, address_range: Tuple[int, int] = None) -> List[Symbol]:
    """Parse symbols.txt and filter by prefix or address range."""
    symbols = []
    pattern = re.compile(
        r'^(\w+)\s*=\s*\.(\w+):0x([0-9A-Fa-f]+);\s*//\s*type:(\w+)\s+size:0x([0-9A-Fa-f]+)\s+scope:(\w+)(?:\s+.*)?$'
    )

    with open(symbols_path) as f:
        for line in f:
            line = line.strip()
            m = pattern.match(line)
            if m:
                name, section, addr_str, sym_type, size_str, scope = m.groups()
                addr = int(addr_str, 16)
                size = int(size_str, 16)

                # Filter by prefix
                if prefix and not name.startswith(prefix):
                    continue

                # Filter by address range
                if address_range:
                    start, end = address_range
                    if addr < start or addr >= end:
                        continue

                # Only include data symbols
                if sym_type == 'object' and section in ('data', 'sdata', 'rodata', 'bss', 'sbss'):
                    # Extract data type hint if present
                    data_type = None
                    if 'data:' in line:
                        m2 = re.search(r'data:(\w+)', line)
                        if m2:
                            data_type = m2.group(1)

                    symbols.append(Symbol(name, addr, size, section, scope, data_type))

    return sorted(symbols, key=lambda s: s.address)

def parse_dol_sections(dol_path: Path) -> List[DOLSection]:
    """Parse DOL header to get section information."""
    sections = []

    with open(dol_path, 'rb') as f:
        # DOL header format:
        # 0x00: 7 text section offsets (u32 each)
        # 0x1C: 11 data section offsets (u32 each)
        # 0x48: 7 text section addresses (u32 each)
        # 0x64: 11 data section addresses (u32 each)
        # 0x90: 7 text section sizes (u32 each)
        # 0xAC: 11 data section sizes (u32 each)

        # Read all header data
        header = f.read(0x100)

        def read_u32(offset):
            return struct.unpack('>I', header[offset:offset+4])[0]

        # Text sections (0-6)
        for i in range(7):
            file_off = read_u32(0x00 + i*4)
            addr = read_u32(0x48 + i*4)
            size = read_u32(0x90 + i*4)
            if size > 0:
                sections.append(DOLSection(f'.text{i}', addr, size, file_off))

        # Data sections (0-10)
        section_names = ['.data', '.data1', '.data2', '.data3', '.data4',
                        '.data5', '.data6', '.data7', '.data8', '.data9', '.data10']
        for i in range(11):
            file_off = read_u32(0x1C + i*4)
            addr = read_u32(0x64 + i*4)
            size = read_u32(0xAC + i*4)
            if size > 0:
                sections.append(DOLSection(section_names[i], addr, size, file_off))

    return sections

def addr_to_file_offset(addr: int, sections: List[DOLSection]) -> Optional[int]:
    """Convert memory address to file offset."""
    for sec in sections:
        if sec.address <= addr < sec.address + sec.size:
            return sec.file_offset + (addr - sec.address)
    return None

def read_dol_data(dol_path: Path, addr: int, size: int, sections: List[DOLSection]) -> Optional[bytes]:
    """Read data from DOL at given address."""
    file_off = addr_to_file_offset(addr, sections)
    if file_off is None:
        return None

    with open(dol_path, 'rb') as f:
        f.seek(file_off)
        return f.read(size)

def is_likely_float(data: bytes, offset: int) -> Tuple[bool, float]:
    """Check if 4 bytes at offset look like a reasonable float."""
    if offset + 4 > len(data):
        return False, 0.0

    val = struct.unpack('>f', data[offset:offset+4])[0]

    # Check for common float patterns
    # NaN or Inf
    if val != val or abs(val) == float('inf'):
        return False, val

    # Zero is valid
    if val == 0.0:
        return True, val

    # Reasonable range for game floats
    if abs(val) < 100000 and abs(val) > 1e-10:
        return True, val

    return False, val

def is_likely_string(data: bytes, offset: int) -> Tuple[bool, str]:
    """Check if bytes at offset look like a null-terminated string."""
    if offset >= len(data):
        return False, ""

    # Look for null terminator within reasonable distance
    end = offset
    while end < len(data) and end - offset < 256:
        if data[end] == 0:
            break
        # Check if printable ASCII
        if data[end] < 32 or data[end] > 126:
            if data[end] != 0x0A:  # Allow newline
                return False, ""
        end += 1

    if end == offset:
        return False, ""

    if end - offset < 2:  # Too short
        return False, ""

    try:
        s = data[offset:end].decode('ascii')
        # Must have some letters
        if any(c.isalpha() for c in s):
            return True, s
    except:
        pass

    return False, ""

def is_likely_pointer(val: int) -> bool:
    """Check if value looks like a pointer."""
    # Common GameCube memory ranges
    if 0x80000000 <= val <= 0x81800000:  # Main RAM
        return True
    # Physical addresses - but require minimum value to avoid small integers
    if 0x00010000 <= val <= 0x01800000:  # Physical addresses (min 64KB)
        return True
    return False

def analyze_data(data: bytes, base_addr: int, symbols: List[Symbol]) -> List[Dict]:
    """Analyze data bytes and infer field types."""
    fields = []
    offset = 0

    while offset < len(data):
        field = {'offset': offset, 'addr': base_addr + offset}

        # Check for string first (higher priority)
        is_str, str_val = is_likely_string(data, offset)
        if is_str:
            # Align string length to 4 bytes
            str_len = len(str_val) + 1  # Include null
            aligned_len = (str_len + 3) & ~3
            field['type'] = 'string'
            field['value'] = str_val
            field['size'] = aligned_len
            fields.append(field)
            offset += aligned_len
            continue

        # Need at least 4 bytes for most types
        if offset + 4 > len(data):
            if offset + 2 <= len(data):
                val16 = struct.unpack('>H', data[offset:offset+2])[0]
                field['type'] = 's16'
                field['value'] = val16 if val16 < 0x8000 else val16 - 0x10000
                field['size'] = 2
                fields.append(field)
                offset += 2
                continue
            field['type'] = 'u8'
            field['value'] = data[offset]
            field['size'] = 1
            fields.append(field)
            offset += 1
            continue

        # If not 4-byte aligned, check for s16 first
        if offset % 4 != 0 and offset + 2 <= len(data):
            val16 = struct.unpack('>H', data[offset:offset+2])[0]
            # Small positive s16 or negative s16
            if (0 < val16 < 0x1000) or (val16 >= 0xFF00):
                field['type'] = 's16'
                field['value'] = val16 if val16 < 0x8000 else val16 - 0x10000
                field['size'] = 2
                fields.append(field)
                offset += 2
                continue

        # Read as big-endian u32
        val = struct.unpack('>I', data[offset:offset+4])[0]

        # Check for float
        is_float, float_val = is_likely_float(data, offset)
        if is_float:
            field['type'] = 'f32'
            field['value'] = float_val
            field['size'] = 4
            fields.append(field)
            offset += 4
            continue

        # Check for packed s16 pattern (0x00XX00YY where both XX and YY are non-zero)
        hi_half = (val >> 16) & 0xFFFF
        lo_half = val & 0xFFFF
        hi_hi = (hi_half >> 8) & 0xFF
        lo_hi = (lo_half >> 8) & 0xFF
        # Pattern: both high bytes are 0x00 (or 0xFF for negative) AND both low bytes are non-zero
        # This distinguishes packed s16 from small s32 (which has hi_half == 0)
        hi_lo = hi_half & 0xFF
        lo_lo = lo_half & 0xFF
        if ((hi_hi == 0x00 and lo_hi == 0x00) or (hi_hi == 0xFF and lo_hi == 0xFF)):
            # Only if both halves have meaningful non-zero low bytes
            if hi_lo > 0 and lo_lo > 0:
                # Looks like packed s16, start s16 parsing
                val16 = hi_half
                field['type'] = 's16'
                field['value'] = val16 if val16 < 0x8000 else val16 - 0x10000
                field['size'] = 2
                fields.append(field)
                offset += 2
                continue

        # Check for pointer
        if is_likely_pointer(val):
            field['type'] = 'void*'
            field['value'] = f'0x{val:08X}'
            field['size'] = 4
            fields.append(field)
            offset += 4
            continue

        # Check for small integers (s32 vs s16)
        # If on 4-byte boundary and value is a small s32, prefer s32
        is_aligned = (offset % 4 == 0)

        # Small s32 check (0-1000 or small negative)
        if is_aligned and (val < 1000 or val > 0xFFFFFC00):
            field['type'] = 's32'
            field['value'] = val if val < 0x80000000 else val - 0x100000000
            field['size'] = 4
            fields.append(field)
            offset += 4
            continue

        # Check for s16 pair (when not a clean s32)
        if offset + 2 <= len(data):
            val16 = struct.unpack('>H', data[offset:offset+2])[0]
            # If it looks like a reasonable s16/u16 and next 2 bytes also do
            # Only trigger if both halves have meaningful values (not 0x0000 + small)
            if (val16 > 0 and val16 < 0x8000) or (val16 >= 0xFF00):
                if offset + 4 <= len(data):
                    next16 = struct.unpack('>H', data[offset+2:offset+4])[0]
                    if (next16 > 0 and next16 < 0x8000) or next16 >= 0xFF00:
                        field['type'] = 's16'
                        field['value'] = val16 if val16 < 0x8000 else val16 - 0x10000
                        field['size'] = 2
                        fields.append(field)
                        offset += 2
                        continue

        # Default to s32
        field['type'] = 's32'
        field['value'] = val if val < 0x80000000 else val - 0x100000000
        field['size'] = 4
        fields.append(field)
        offset += 4

    return fields

def group_into_arrays(fields: List[Dict]) -> List[Dict]:
    """Group consecutive same-type fields into arrays."""
    if not fields:
        return []

    result = []
    i = 0

    while i < len(fields):
        field = fields[i].copy()

        # Check for array pattern
        if field['type'] in ('s32', 'f32', 's16', 'u16', 'void*'):
            count = 1
            j = i + 1
            while j < len(fields):
                if fields[j]['type'] != field['type']:
                    break
                if fields[j]['offset'] != field['offset'] + count * field['size']:
                    break
                count += 1
                j += 1

            if count > 1:
                field['count'] = count
                field['values'] = [fields[k]['value'] for k in range(i, i + count)]
                i = j
                result.append(field)
                continue

        result.append(field)
        i += 1

    return result

def format_field_value(field: Dict) -> str:
    """Format a field value for display."""
    if field['type'] == 'f32':
        if 'count' in field:
            return ', '.join(f'{v:.1f}f' for v in field['values'])
        return f"{field['value']:.6g}f"
    elif field['type'] == 'string':
        return repr(field['value'])
    elif field['type'] == 'void*':
        if 'count' in field:
            return ', '.join(field['values'])
        return field['value']
    elif field['type'] in ('s32', 's16'):
        if 'count' in field:
            return ', '.join(str(v) for v in field['values'])
        return str(field['value'])
    else:
        return str(field['value'])

def generate_struct_def(symbol: Symbol, fields: List[Dict]) -> str:
    """Generate a C struct definition from analyzed fields."""
    lines = []
    lines.append(f"/* {symbol.name} @ 0x{symbol.address:08X} ({symbol.size} bytes) */")
    lines.append(f"struct {symbol.name}_t {{")

    for field in fields:
        offset = field['offset']
        ftype = field['type']
        size = field.get('count', 1) * field['size']
        value = format_field_value(field)

        if ftype == 'string':
            lines.append(f"    /* +0x{offset:02X} */ char str_{offset:02X}[0x{size:X}];  // {value}")
        elif 'count' in field:
            lines.append(f"    /* +0x{offset:02X} */ {ftype} x{offset:X}[{field['count']}];  // {{{value}}}")
        else:
            lines.append(f"    /* +0x{offset:02X} */ {ftype} x{offset:X};  // {value}")

    lines.append(f"}};  // size = 0x{symbol.size:X}")
    return '\n'.join(lines)

def print_hex_dump(data: bytes, base_addr: int, fields: List[Dict]):
    """Print annotated hex dump."""
    field_idx = 0
    offset = 0

    while offset < len(data):
        # Find field at this offset
        field = None
        if field_idx < len(fields) and fields[field_idx]['offset'] == offset:
            field = fields[field_idx]
            field_idx += 1

        # Print 16 bytes per line
        line_start = offset
        line_end = min(offset + 16, len(data))

        hex_str = ' '.join(f'{data[i]:02X}' for i in range(line_start, line_end))
        ascii_str = ''.join(chr(data[i]) if 32 <= data[i] < 127 else '.' for i in range(line_start, line_end))

        annotation = ""
        if field:
            annotation = f"  <- {field['type']}"
            if field['type'] == 'string':
                annotation += f" {repr(field['value'])}"
            elif field['type'] == 'f32':
                annotation += f" = {field['value']:.6g}"
            elif 'count' in field:
                annotation += f"[{field['count']}]"

        print(f"  +0x{line_start:03X} | {hex_str:<48} | {ascii_str}{annotation}")
        offset = line_end

def print_combined_layout(symbols: List[Symbol], dol_path: Path, sections: List[DOLSection]):
    """Print combined layout of adjacent symbols as one virtual struct."""
    if not symbols:
        return

    # Sort by address
    symbols = sorted(symbols, key=lambda s: s.address)
    base_addr = symbols[0].address

    # Calculate total span
    last_sym = symbols[-1]
    total_size = (last_sym.address + last_sym.size) - base_addr

    print(f"\n{'='*70}")
    print(f"COMBINED LAYOUT (as accessed from base 0x{base_addr:08X})")
    print(f"Total span: 0x{total_size:X} ({total_size} bytes)")
    print(f"{'='*70}\n")

    # Read all data
    data = read_dol_data(dol_path, base_addr, total_size, sections)
    if not data:
        print("Could not read data")
        return

    # Print with symbol annotations
    print("Offset  | Symbol              | Hex                                              | ASCII")
    print("-" * 100)

    offset = 0
    sym_idx = 0

    while offset < len(data):
        # Find which symbol this offset belongs to
        abs_addr = base_addr + offset
        current_sym = None
        sym_offset = 0

        for sym in symbols:
            if sym.address <= abs_addr < sym.address + sym.size:
                current_sym = sym
                sym_offset = abs_addr - sym.address
                break

        # Determine line end
        line_end = min(offset + 16, len(data))

        # Build hex and ASCII strings
        hex_parts = []
        ascii_str = ""
        for i in range(offset, line_end):
            hex_parts.append(f'{data[i]:02X}')
            ascii_str += chr(data[i]) if 32 <= data[i] < 127 else '.'

        hex_str = ' '.join(hex_parts)

        # Symbol name (truncated)
        if current_sym:
            sym_name = current_sym.name[-18:] if len(current_sym.name) > 18 else current_sym.name
            sym_info = f"{sym_name}+0x{sym_offset:02X}"
        else:
            sym_info = "(gap)"

        print(f"+0x{offset:03X} | {sym_info:19} | {hex_str:<48} | {ascii_str}")
        offset = line_end

    # Now print a suggested combined struct
    print(f"\n{'='*70}")
    print("SUGGESTED COMBINED STRUCT")
    print(f"{'='*70}\n")

    print(f"/* Combined view from base 0x{base_addr:08X} */")
    print(f"struct MnDataDelCombined {{")

    for sym in symbols:
        rel_offset = sym.address - base_addr
        print(f"    /* +0x{rel_offset:02X} */ /* {sym.name} ({sym.size} bytes) */")

        # Read this symbol's data
        sym_data = read_dol_data(dol_path, sym.address, sym.size, sections)
        if sym_data:
            fields = analyze_data(sym_data, sym.address, symbols)
            fields = group_into_arrays(fields)

            for field in fields:
                field_offset = rel_offset + field['offset']
                ftype = field['type']
                value = format_field_value(field)

                if ftype == 'string':
                    size = field['size']
                    print(f"    /* +0x{field_offset:02X} */ char x{field_offset:X}[0x{size:X}];  // {value}")
                elif 'count' in field:
                    print(f"    /* +0x{field_offset:02X} */ {ftype} x{field_offset:X}[{field['count']}];  // {{{value}}}")
                else:
                    print(f"    /* +0x{field_offset:02X} */ {ftype} x{field_offset:X};  // {value}")

    print(f"}};  // total size = 0x{total_size:X}")

def main():
    parser = argparse.ArgumentParser(description='Analyze DOL data layout')
    parser.add_argument('prefix', nargs='?', help='Symbol name prefix to filter (e.g., mnDataDel_803EF8)')
    parser.add_argument('--melee-root', default='/Users/mike/code/melee', help='Path to melee repo')
    parser.add_argument('--address', type=lambda x: int(x, 0), help='Start address (hex)')
    parser.add_argument('--size', type=lambda x: int(x, 0), help='Size in bytes (hex)')
    parser.add_argument('--generate-struct', action='store_true', help='Generate C struct definitions')
    parser.add_argument('--combined', action='store_true', help='Show combined layout of all matching symbols')
    parser.add_argument('--context', type=int, default=0, help='Show N bytes before/after each symbol')
    args = parser.parse_args()

    melee_root = Path(args.melee_root)
    symbols_path = melee_root / 'config' / 'GALE01' / 'symbols.txt'
    dol_path = melee_root / 'build' / 'GALE01' / 'main.dol'

    if not symbols_path.exists():
        print(f"Error: symbols.txt not found at {symbols_path}")
        return 1

    if not dol_path.exists():
        print(f"Error: main.dol not found at {dol_path}")
        return 1

    # Parse DOL sections
    sections = parse_dol_sections(dol_path)

    # Get symbols
    if args.address and args.size:
        # Manual address range mode
        symbols = [Symbol('manual', args.address, args.size, 'data', 'global')]
    elif args.prefix:
        symbols = parse_symbols(symbols_path, prefix=args.prefix)
    else:
        print("Error: Must specify either a symbol prefix or --address/--size")
        return 1

    if not symbols:
        print(f"No symbols found matching prefix '{args.prefix}'")
        return 1

    print(f"Found {len(symbols)} symbols:\n")

    # Combined mode - show all symbols as one virtual struct
    if args.combined and len(symbols) > 1:
        print_combined_layout(symbols, dol_path, sections)
        return 0

    for sym in symbols:
        print(f"{'='*70}")
        print(f"{sym.name}")
        print(f"  Address: 0x{sym.address:08X}")
        print(f"  Size:    0x{sym.size:X} ({sym.size} bytes)")
        print(f"  Section: .{sym.section}")
        if sym.data_type:
            print(f"  Type hint: {sym.data_type}")
        print()

        # Read data
        read_size = sym.size + args.context
        read_addr = sym.address
        data = read_dol_data(dol_path, read_addr, read_size, sections)

        if data is None:
            print("  (Could not read data from DOL)")
            continue

        # Analyze
        fields = analyze_data(data[:sym.size], sym.address, symbols)
        fields = group_into_arrays(fields)

        # Print hex dump
        print("  Hex dump:")
        print_hex_dump(data[:sym.size], sym.address, fields)

        # Print struct definition
        if args.generate_struct:
            print()
            print("  Suggested struct:")
            struct_def = generate_struct_def(sym, fields)
            for line in struct_def.split('\n'):
                print(f"  {line}")

        print()

    return 0

if __name__ == '__main__':
    exit(main())
