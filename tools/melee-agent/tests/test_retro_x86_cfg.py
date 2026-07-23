import hashlib
import json
import struct
import sys
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path

import capstone
import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))
from retro_pe_fixture import (  # noqa: E402
    OPTIONAL_OFFSET,
    SECTION_TABLE_OFFSET,
    write_synthetic_cfg_pe,
    write_synthetic_dispatch_pe,
)
from tools.mwcc_retro import pe  # noqa: E402
from tools.mwcc_retro import x86_cfg as x86_cfg_module
from tools.mwcc_retro.x86_cfg import (  # noqa: E402
    _DECODED_INSTRUCTION_CACHE_LIMIT,
    _MOVZX_PRODUCER_ANALYSIS_SEMANTICS,
    AnalysisLimitError,
    AnalysisLimits,
    AuditAnchor,
    CfgRecoveryError,
    DirectCall,
    JumpTable,
    ProducerCertificateError,
    ProducerCheckpointIncomplete,
    SeedRecord,
    _AbstractObjectIdentity,
    _DirectCfgRecovery,
    _DynamicFieldWrite,
    _GlobalSlotWrite,
    _materialize_function_entries,
    _MovzxProducerQuery,
    _ObjectByteGuard,
    _producer_certificate_digest,
    _ProducerCertificateSession,
    build_seed_inventory,
    canonical_jsonl_bytes,
    parse_cw_exception_metadata,
    recover_cfg,
    write_jsonl_atomic,
)


@pytest.fixture
def synthetic_cfg_image(tmp_path):
    return load_cfg_image(tmp_path)


def load_cfg_image(tmp_path, mutation=None):
    path = write_synthetic_cfg_pe(tmp_path, mutation=mutation)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(
        path,
        expected_sha256=digest,
        require_pe32_i386=True,
    )


def load_cfg_program(tmp_path, program_hex):
    path = write_synthetic_cfg_pe(tmp_path)
    data = bytearray(path.read_bytes())
    program = bytes.fromhex(program_hex)
    assert len(program) <= 0x16
    data[0x20A:0x220] = b"\x90" * 0x16
    data[0x20A : 0x20A + len(program)] = program
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def load_large_cfg_program(tmp_path, program):
    path = write_synthetic_cfg_pe(tmp_path)
    data = bytearray(path.read_bytes())
    program = bytearray(program)
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x180)
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x180)
    data[0x240:0x251] = b"\xc3" + b"\x90" * 0x10
    data[0x280:0x380] = b"\x90" * 0x100
    data[0x280 : 0x280 + len(program)] = program
    struct.pack_into("<I", data, 0x430, 0x1080)
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def global_stack_callback_image(
    tmp_path,
    *,
    unknown_field_write=False,
    alternate_global_writer=False,
    unknown_caller=False,
):
    """Closed stack context published through a loader-zero global slot."""
    base = 0x00401080
    global_slot = 0x00402300
    program = bytearray(b"\x90" * 0xE0)
    callback_relocations = []

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        program[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        program[offset] = 0xE8
        displacement = (base + target_offset) - (base + offset + 5)
        program[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # Authoritative export root.  One closed caller supplies the callback;
    # hostile variants add either an unbounded global writer or caller.
    cursor = 0
    if alternate_global_writer:
        cursor = emit(cursor, "89 15 00 23 40 00")
    callback_relocations.append(base + cursor + 1)
    cursor = emit(cursor, "68 50 11 40 00")
    cursor = emit_call(cursor, 0x20)
    cursor = emit(cursor, "59")
    if unknown_caller:
        cursor = emit(cursor, "52")
        cursor = emit_call(cursor, 0x20)
        cursor = emit(cursor, "59")
    emit(cursor, "c3")

    # producer(callback): zero a stack context, save the old nested context,
    # initialize +0x10, publish it, invoke a consumer, then restore the old
    # context.  The save/restore is part of the proof, not an ignored writer.
    cursor = 0x20
    cursor = emit(cursor, "83 ec 20")
    cursor = emit(cursor, "a1 00 23 40 00")
    cursor = emit(cursor, "89 44 24 1c")
    cursor = emit(cursor, "8d 04 24")
    cursor = emit(cursor, "6a 18")
    cursor = emit(cursor, "50")
    cursor = emit_call(cursor, 0xC0)
    cursor = emit(cursor, "59 59")
    cursor = emit(cursor, "8b 4c 24 24")
    cursor = emit(
        cursor,
        "89 54 24 10" if unknown_field_write else "89 4c 24 10",
    )
    cursor = emit(cursor, "8d 04 24")
    cursor = emit(cursor, "a3 00 23 40 00")
    cursor = emit_call(cursor, 0x80)
    cursor = emit(cursor, "8b 44 24 1c")
    cursor = emit(cursor, "a3 00 23 40 00")
    cursor = emit(cursor, "83 c4 20 c3")
    assert cursor < 0x80

    # consumer(): the nonzero guard removes the loader-zero/nested-zero
    # context while retaining every proved callback producer.
    cursor = 0x80
    cursor = emit(cursor, "a1 00 23 40 00")
    cursor = emit(cursor, "8b 48 10")
    cursor = emit(cursor, "85 c9 74 02 ff d1 c3")
    indirect_call = base + cursor - 3

    # Strict two-argument byte zero-fill helper: (destination, size).
    emit(0xC0, "31 c0 57 8b 4c 24 0c 8b 7c 24 08 f3 aa 5f c3")
    emit(0xD0, "c3")

    path = write_synthetic_cfg_pe(tmp_path)
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 8, 0x180)
    struct.pack_into("<I", data, SECTION_TABLE_OFFSET + 16, 0x180)
    data[0x240:0x251] = b"\xc3" + b"\x90" * 0x10
    data[0x280:0x380] = b"\x90" * 0x100
    data[0x280 : 0x280 + len(program)] = program
    struct.pack_into("<I", data, 0x430, 0x1080)
    relocation_words = [0x3000 | (address - 0x00401000) for address in callback_relocations]
    block_size = 8 + len(relocation_words) * 2
    if block_size % 4:
        relocation_words.append(0)
        block_size += 2
    struct.pack_into("<I", data, OPTIONAL_OFFSET + 96 + 5 * 8 + 4, block_size)
    struct.pack_into("<II", data, 0x800, 0x1000, block_size)
    struct.pack_into(f"<{len(relocation_words)}H", data, 0x808, *relocation_words)
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    image = pe.load(path, expected_sha256=digest, require_pe32_i386=True)
    assert image.read(global_slot, 4) == b"\0" * 4
    return image, indirect_call


def nested_global_stack_callback_image(
    *,
    field_offset,
    mutation=None,
):
    """Two LIFO stack contexts with distinct return-arm restorations."""
    assert field_offset in {0x10, 0x18, 0x20, 0x24}
    assert mutation in {
        None,
        "missing-restore-arm",
        "out-of-order-restore",
        "overwritten-save-slot",
        "unknown-overlapping-write",
        "post-restore-overlapping-write",
        "alternate-global-writer",
        "alternate-unknown-caller",
    }
    text_va = 0x00401000
    publisher = 0x00401050
    consumer = 0x00401180
    zero_fill = 0x004011A0
    callback = 0x004011C0
    alternate_writer = 0x004011E0
    global_slot = 0x00402300
    text = bytearray(b"\x90" * 0x200)
    relocations = []

    def emit(address, encoded):
        encoded = bytes.fromhex(encoded)
        offset = address - text_va
        text[offset : offset + len(encoded)] = encoded
        return address + len(encoded)

    def emit_call(address, target):
        displacement = target - (address + 5)
        return emit(
            address,
            "e8" + displacement.to_bytes(4, "little", signed=True).hex(),
        )

    def emit_absolute(address, prefix, target):
        prefix_bytes = bytes.fromhex(prefix)
        relocations.append(pe.Relocation(address + len(prefix_bytes), 3))
        return emit(address, prefix + target.to_bytes(4, "little").hex())

    # root(callback): the relocated callback is the complete caller domain.
    cursor = text_va
    cursor = emit_absolute(cursor, "68", callback)
    if mutation == "alternate-global-writer":
        cursor = emit_call(cursor, alternate_writer)
    cursor = emit_call(cursor, publisher)
    cursor = emit(cursor, "59")
    if mutation == "alternate-unknown-caller":
        cursor = emit(cursor, "52")
        cursor = emit_call(cursor, publisher)
        cursor = emit(cursor, "59")
    emit(cursor, "c3")

    cursor = publisher
    cursor = emit(cursor, "83ec70")

    def emit_zero_and_fields(cursor, base):
        cursor = emit(cursor, "8d0424" if base == 0 else "8d442430")
        cursor = emit(cursor, "6a2850")
        cursor = emit_call(cursor, zero_fill)
        cursor = emit(cursor, "83c408")
        cursor = emit(cursor, "8b442474")
        for displacement in (0x10, 0x18, 0x20, 0x24):
            cursor = emit(
                cursor,
                f"894424{base + displacement:02x}",
            )
        if mutation == "unknown-overlapping-write" and base == 0:
            cursor = emit(cursor, f"895424{field_offset:02x}")
        return cursor

    # Publish context 1 after saving the loader-zero/prior nested context.
    cursor = emit_zero_and_fields(cursor, 0)
    cursor = emit_absolute(cursor, "8b0d", global_slot)
    cursor = emit(cursor, "894c2468")
    cursor = emit(cursor, "8d0424")
    publication_one = cursor
    cursor = emit_absolute(cursor, "a3", global_slot)

    # Publish context 2 after saving context 1, forming a true LIFO nest.
    cursor = emit_zero_and_fields(cursor, 0x30)
    cursor = emit_absolute(cursor, "8b15", global_slot)
    nested_save_offset = 0x68 if mutation == "overwritten-save-slot" else 0x6C
    cursor = emit(cursor, f"895424{nested_save_offset:02x}")
    cursor = emit(cursor, "8d442430")
    publication_two = cursor
    cursor = emit_absolute(cursor, "a3", global_slot)
    cursor = emit_call(cursor, consumer)
    cursor = emit(cursor, "837c247400")
    branch = cursor
    cursor = emit(cursor, "7400")

    def emit_restore(cursor, saved_offset):
        cursor = emit(cursor, f"8b4424{saved_offset:02x}")
        return emit_absolute(cursor, "a3", global_slot)

    # Normal return arm: context 2 -> context 1 -> loader-zero/prior.
    cursor = emit_restore(cursor, nested_save_offset)
    cursor = emit_call(cursor, consumer)
    cursor = emit_restore(cursor, 0x68)
    if mutation == "post-restore-overlapping-write":
        cursor = emit(cursor, f"895424{field_offset:02x}")
    cursor = emit(cursor, "83c470c3")

    early = cursor
    delta = early - (branch + 2)
    assert -0x80 <= delta <= 0x7F
    text[branch - text_va + 1] = delta & 0xFF
    if mutation == "missing-restore-arm":
        cursor = emit(cursor, "83c470c3")
    elif mutation == "out-of-order-restore":
        cursor = emit_restore(cursor, 0x68)
        cursor = emit_restore(cursor, 0x6C)
        cursor = emit(cursor, "83c470c3")
    else:
        cursor = emit_restore(cursor, nested_save_offset)
        cursor = emit_restore(cursor, 0x68)
        if mutation == "post-restore-overlapping-write":
            cursor = emit(cursor, f"895424{field_offset:02x}")
        cursor = emit(cursor, "83c470c3")
    assert cursor <= consumer

    cursor = consumer
    cursor = emit_absolute(cursor, "a1", global_slot)
    cursor = emit(cursor, f"8b48{field_offset:02x}")
    cursor = emit(cursor, "85c97402")
    indirect_call = cursor
    cursor = emit(cursor, "ffd1c3")
    assert cursor <= zero_fill

    emit(zero_fill, "31c0578b4c240c8b7c2408f3aa5fc3")
    emit(callback, "c3")
    if mutation == "alternate-global-writer":
        cursor = emit_absolute(alternate_writer, "8915", global_slot)
        emit(cursor, "c3")

    data = bytes(text) + b"\0" * 0x400
    image = pe.Image(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(
                ".text",
                text_va,
                0,
                len(text),
                len(text),
                0x60000020,
            ),
            pe.Section(
                ".data",
                0x00402000,
                len(text),
                0x400,
                0x400,
                0xC0000040,
            ),
        ),
        imports=(),
        exports=(),
        relocations=tuple(relocations),
        executable_ranges=((text_va, text_va + len(text)),),
    )
    assert image.read(global_slot, 4) == b"\0" * 4
    return (
        image,
        indirect_call,
        publisher,
        zero_fill,
        (publication_one, publication_two),
    )


def test_semantic_references_include_global_writes(tmp_path):
    image = load_cfg_image(tmp_path)
    cfg = recover_cfg(
        image,
        (image.entrypoint,),
        AnalysisLimits.for_image(image),
    )
    references = {(row.record_kind, row.address, row.target) for row in cfg.semantic_references}
    assert ("data-reference", 0x00401011, 0x00402090) in references
    assert ("data-reference", 0x00401020, 0x00402094) in references


def test_semantic_references_retain_jump_table_base_after_rescan(tmp_path):
    path = write_synthetic_dispatch_pe(tmp_path)
    image = pe.load(path)
    cfg = recover_cfg(
        image,
        (image.entrypoint,),
        AnalysisLimits.for_image(image),
    )
    table = cfg.jump_tables[0]
    assert any(
        row.record_kind == "data-reference" and row.address == table.address and row.target == table.base
        for row in cfg.semantic_references
    )


def load_memmove_program(tmp_path, *, corrupt_backward_step=False):
    program = bytearray.fromhex(
        "8b54240456578b4424148b74241089d731c939f7772b3d100000007c1e"
        "29f981e103000000740429c8f3a489c12503000000c1e902f3a585c074"
        "4689c1f3a4eb40fd8d7406ff8d7c07ff3d100000007c2b8d4ffd81e103"
        "000000740429c8f3a483ee0383ef0389c12503000000c1e902f3a585c0"
        "740a83c60383c70389c1f3a4fc89d05f5ec3"
    )
    if corrupt_backward_step:
        step = program.index(bytes.fromhex("83ef03"))
        program[step + 2] = 4
    return load_large_cfg_program(tmp_path, program)


def load_memcpy_program(tmp_path):
    return load_large_cfg_program(
        tmp_path,
        bytes.fromhex(
            "8b54240456578b4424148b74241089d731c93d100000007c1e29f981e1"
            "03000000740429c8f3a489c12503000000c1e902f3a585c0740489c1f3"
            "a489d05f5ec3"
        ),
    )


def decode_one(encoded):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    return decoder, next(decoder.disasm(bytes.fromhex(encoded), 0x00401000, count=1))


def audit_anchor(image, address=0x00401070):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoded = next(decoder.disasm(image.read(address, 15), address, count=1))
    return AuditAnchor(
        name="synthetic-audit-anchor",
        address=address,
        instruction_bytes=bytes(decoded.bytes),
        evidence="synthetic-fixture",
    )


def inventory(image):
    return build_seed_inventory(image, (audit_anchor(image),))


def generous_limits(image):
    defaults = AnalysisLimits.for_image(image)
    return replace(
        defaults,
        max_instructions=512,
        max_blocks=512,
        max_edges=4096,
        max_functions=512,
        max_finite_targets=512,
        max_finite_values=512,
    )


def registered_static_command_image(*, mutation=None):
    """Closed registered descriptor graph with type-13/15 callbacks."""
    assert mutation in {None, "unrelocated-node-link", "hidden-setter-caller"}
    text_va = 0x00401000
    data_va = 0x00402000
    root = text_va
    dispatcher = text_va + 0x40
    noop_handler = text_va + 0x80
    type_13_handler = text_va + 0x90
    recursive_handler = text_va + 0xA0
    type_15_handler = text_va + 0xC0
    walker = text_va + 0xD0
    consumer = text_va + 0x100
    lookup = text_va + 0x130
    producer = text_va + 0x160
    wrapper = text_va + 0x190
    fixed_registry = text_va + 0x1B0
    append = text_va + 0x1C0
    group_registrar = text_va + 0x1E0
    initializer = text_va + 0x220
    setter = text_va + 0x250
    callback_13 = text_va + 0x270
    callback_15 = text_va + 0x280

    dispatch_table = data_va
    compiler_descriptor = data_va + 0x100
    groups = data_va + 0x140
    container = data_va + 0x160
    descriptor_array = data_va + 0x180
    descriptor = data_va + 0x1A0
    node_13 = data_va + 0x1C0
    node_15 = data_va + 0x1E0
    compiler_slot = data_va + 0x300
    registry_root = data_va + 0x400
    registry_array_slot = registry_root + 8

    text = bytearray(b"\xcc" * 0x300)
    relocations = []

    def emit(address, encoded):
        encoded = bytes.fromhex(encoded)
        offset = address - text_va
        text[offset : offset + len(encoded)] = encoded
        return address + len(encoded)

    def emit_call(address, target):
        displacement = target - (address + 5)
        return emit(
            address,
            "e8" + displacement.to_bytes(4, "little", signed=True).hex(),
        )

    def emit_absolute(address, prefix, target):
        prefix_bytes = bytes.fromhex(prefix)
        relocations.append(pe.Relocation(address + len(prefix_bytes), 3))
        return emit(address, prefix + target.to_bytes(4, "little").hex())

    def patch_short_branch(address, target):
        delta = target - (address + 2)
        assert -0x80 <= delta <= 0x7F
        text[address - text_va + 1] = delta & 0xFF

    cursor = root
    cursor = emit_absolute(cursor, "68", compiler_descriptor)
    cursor = emit_call(cursor, setter)
    cursor = emit(cursor, "83c404")
    cursor = emit_call(cursor, initializer)
    cursor = emit_call(cursor, fixed_registry)
    cursor = emit(cursor, "50")
    cursor = emit_call(cursor, wrapper)
    cursor = emit(cursor, "83c404c3")
    assert cursor <= dispatcher

    cursor = dispatcher
    cursor = emit(cursor, "538b5c2408803b00")
    lower_branch = cursor
    cursor = emit(cursor, "7c00")
    cursor = emit(cursor, "803b10")
    upper_branch = cursor
    cursor = emit(cursor, "7d00")
    cursor = emit(cursor, "530fbe0389c3")
    indirect_dispatch = cursor
    cursor = emit_absolute(cursor, "ff149d", dispatch_table)
    cursor = emit(cursor, "83c4045bc3")
    overflow = cursor
    cursor = emit(cursor, "31c05bc3")
    patch_short_branch(lower_branch, overflow)
    patch_short_branch(upper_branch, overflow)
    assert cursor <= noop_handler

    emit(noop_handler, "c3")
    cursor = emit(type_13_handler, "568b742408")
    type_13_call = cursor
    emit(cursor, "ff560a5ec3")

    cursor = emit(recursive_handler, "568b742408ff760a")
    cursor = emit_call(cursor, dispatcher)
    cursor = emit(cursor, "83c404ff7612")
    cursor = emit_call(cursor, dispatcher)
    emit(cursor, "83c4045ec3")

    cursor = emit(type_15_handler, "568b742408")
    type_15_call = cursor
    emit(cursor, "ff560a5ec3")

    cursor = emit(walker, "538b5c240885db")
    walker_done_branch = cursor
    cursor = emit(cursor, "7400")
    cursor = emit(cursor, "53")
    cursor = emit_call(cursor, dispatcher)
    cursor = emit(cursor, "83c4048b5b06")
    loop_branch = cursor
    cursor = emit(cursor, "eb00")
    walker_done = cursor
    emit(cursor, "5bc3")
    patch_short_branch(walker_done_branch, walker_done)
    patch_short_branch(loop_branch, walker + 5)

    cursor = emit(consumer, "568b742408ff7608")
    cursor = emit_call(cursor, walker)
    cursor = emit(cursor, "83c404ff760c")
    cursor = emit_call(cursor, wrapper)
    emit(cursor, "83c4045ec3")

    cursor = emit(lookup, "8b5424048b4a08833900")
    lookup_zero_branch = cursor
    cursor = emit(cursor, "7400")
    cursor = emit(cursor, "8b0185c0")
    lookup_done_branch = cursor
    cursor = emit(cursor, "7500")
    cursor = emit(cursor, "83c104")
    loop_back = cursor
    cursor = emit(cursor, "eb00")
    lookup_done = cursor
    cursor = emit(cursor, "c3")
    lookup_zero = cursor
    emit(cursor, "31c0c3")
    patch_short_branch(lookup_zero_branch, lookup_zero)
    patch_short_branch(lookup_done_branch, lookup_done)
    patch_short_branch(loop_back, lookup + 7)

    cursor = emit(producer, "568b74240856")
    cursor = emit_call(cursor, lookup)
    cursor = emit(cursor, "83c40485c0")
    producer_done_branch = cursor
    cursor = emit(cursor, "7400")
    cursor = emit(cursor, "50")
    cursor = emit_call(cursor, consumer)
    cursor = emit(cursor, "83c404")
    producer_done = cursor
    emit(cursor, "5ec3")
    patch_short_branch(producer_done_branch, producer_done)

    cursor = emit(wrapper, "8b44240450")
    cursor = emit_call(cursor, producer)
    emit(cursor, "83c404c3")

    cursor = emit_absolute(fixed_registry, "b8", registry_root)
    emit(cursor, "c3")

    cursor = emit(append, "8b542404")
    cursor = emit_absolute(cursor, "a1", registry_array_slot)
    emit(cursor, "31c9891488c3")

    cursor = emit(group_registrar, "568b4424088b7008833e00")
    group_done_branch = cursor
    cursor = emit(cursor, "7400ff36")
    cursor = emit_call(cursor, append)
    cursor = emit(cursor, "83c40483c604")
    group_loop_branch = cursor
    cursor = emit(cursor, "eb00")
    group_done = cursor
    emit(cursor, "5ec3")
    patch_short_branch(group_done_branch, group_done)
    patch_short_branch(group_loop_branch, group_registrar + 8)

    cursor = emit(initializer, "31d2")
    cursor = emit_absolute(cursor, "a1", compiler_slot)
    cursor = emit(cursor, "8b482085c9")
    initializer_done_branch = cursor
    cursor = emit(cursor, "7400")
    cursor = emit(cursor, "8b4024ff3490")
    cursor = emit_call(cursor, group_registrar)
    cursor = emit(cursor, "83c404")
    initializer_done = cursor
    emit(cursor, "c3")
    patch_short_branch(initializer_done_branch, initializer_done)

    cursor = emit(setter, "8b442404")
    cursor = emit_absolute(cursor, "a3", compiler_slot)
    emit(cursor, "c3")
    emit(callback_13, "c3")
    emit(callback_15, "c3")
    if mutation == "hidden-setter-caller":
        emit(text_va + 0x2A0, "e8")
        displacement = setter - (text_va + 0x2A0 + 5)
        text[0x2A1:0x2A5] = displacement.to_bytes(4, "little", signed=True)

    image_data = bytearray(text)
    image_data.extend(b"\0" * 0x1000)

    def data_offset(address):
        return len(text) + address - data_va

    def pack_pointer(address, target, *, relocated=True):
        struct.pack_into("<I", image_data, data_offset(address), target)
        if relocated:
            relocations.append(pe.Relocation(address, 3))

    for index in range(16):
        target = noop_handler
        if index == 13:
            target = type_13_handler
        elif index == 14:
            target = recursive_handler
        elif index == 15:
            target = type_15_handler
        pack_pointer(dispatch_table + 4 * index, target)

    struct.pack_into("<I", image_data, data_offset(compiler_descriptor), 0x436F6D70)
    struct.pack_into("<I", image_data, data_offset(compiler_descriptor + 0x20), 1)
    pack_pointer(compiler_descriptor + 0x24, groups)
    pack_pointer(groups, container)
    pack_pointer(container + 8, descriptor_array)
    pack_pointer(descriptor_array, descriptor)
    pack_pointer(descriptor + 8, node_13)
    struct.pack_into("<B", image_data, data_offset(node_13), 13)
    pack_pointer(
        node_13 + 6,
        node_15,
        relocated=mutation != "unrelocated-node-link",
    )
    pack_pointer(node_13 + 0xA, callback_13)
    struct.pack_into("<B", image_data, data_offset(node_15), 15)
    pack_pointer(node_15 + 0xA, callback_15)

    image_bytes = bytes(image_data)
    image = pe.Image(
        data=image_bytes,
        sha256=hashlib.sha256(image_bytes).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=root,
        directories=(),
        sections=(
            pe.Section(
                ".text",
                text_va,
                0,
                len(text),
                len(text),
                0x60000020,
            ),
            pe.Section(
                ".data",
                data_va,
                len(text),
                0x1000,
                0x1000,
                0xC0000040,
            ),
        ),
        imports=(),
        exports=(),
        relocations=tuple(sorted(relocations, key=lambda row: row.va)),
        executable_ranges=((text_va, text_va + len(text)),),
    )
    assert image.read(compiler_slot, 4) == b"\0" * 4
    assert image.read(registry_array_slot, 4) == b"\0" * 4
    return image, (type_13_call, type_15_call), (callback_13, callback_15)


def test_registered_static_command_callbacks_are_closed():
    image, call_sites, callbacks = registered_static_command_image()
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    edges = {(row.source, row.target, row.kind) for row in cfg.edges}
    for call_site, callback in zip(call_sites, callbacks, strict=True):
        assert (
            call_site,
            callback,
            "indirect-call-registered-static-command",
        ) in edges
    seeds = {
        row.address: row for row in cfg.seed_inventory.records if row.category == "registered-static-command-callback"
    }
    assert set(seeds) == set(callbacks)
    assert all("compiler-descriptor=0x402100" in row.detail for row in seeds.values())
    assert all("groups=1;containers=1;descriptors=1;nodes=2" in row.detail for row in seeds.values())


def test_registered_static_command_rejects_unrelocated_graph_link():
    image, call_sites, callbacks = registered_static_command_image(mutation="unrelocated-node-link")
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    edges = {(row.source, row.target, row.kind) for row in cfg.edges}
    assert not any(
        (call_site, callback, "indirect-call-registered-static-command") in edges
        for call_site, callback in zip(call_sites, callbacks, strict=True)
    )
    assert any(
        row.kind == "computed-flow-blocker" and "unrelocated registered-command pointer" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_registered_static_command_rejects_hidden_setter_caller():
    image, call_sites, callbacks = registered_static_command_image(mutation="hidden-setter-caller")
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    edges = {(row.source, row.target, row.kind) for row in cfg.edges}
    assert not any(
        (call_site, callback, "indirect-call-registered-static-command") in edges
        for call_site, callback in zip(call_sites, callbacks, strict=True)
    )
    assert any(
        row.kind == "computed-flow-blocker" and "compiler descriptor setter domain is incomplete" in row.detail
        for row in cfg.ownership_diagnostics
    )


def registered_linked_callback_image(*, mutation=None):
    """Loader-zero heads populated with one 8-byte callback node."""
    assert mutation in {
        None,
        "negative-index",
        "out-of-range-index",
        "unknown-index-writer",
        "hidden-index-caller",
        "alternate-head-writer",
        "cursor-callback-writer",
        "cursor-next-writer",
    }
    text_va = 0x00401000
    data_va = 0x00402000
    root = text_va
    initializer = text_va + 0x80
    allocator = text_va + 0x120
    consumer = text_va + 0x160
    callback = text_va + 0x1D0
    hidden_caller = text_va + 0x200
    alternate_writer = text_va + 0x220
    unrelated_field_writer = text_va + 0x240
    cursor_mutator = text_va + 0x250
    heads = data_va
    node = data_va + 0x100
    text = bytearray(b"\xcc" * 0x280)
    relocations = []

    def emit(address, encoded):
        encoded = bytes.fromhex(encoded)
        offset = address - text_va
        text[offset : offset + len(encoded)] = encoded
        return address + len(encoded)

    def emit_call(address, target):
        displacement = target - (address + 5)
        return emit(
            address,
            "e8" + displacement.to_bytes(4, "little", signed=True).hex(),
        )

    def emit_absolute(address, prefix, target):
        prefix_bytes = bytes.fromhex(prefix)
        relocations.append(pe.Relocation(address + len(prefix_bytes), 3))
        return emit(address, prefix + target.to_bytes(4, "little").hex())

    def patch_short_branch(address, target):
        delta = target - (address + 2)
        assert -0x80 <= delta <= 0x7F
        text[address - text_va + 1] = delta & 0xFF

    cursor = emit(root, "83ec20")
    if mutation == "unknown-index-writer":
        cursor = emit(cursor, "6689542414")
    else:
        index = {
            "negative-index": 0xFFFF,
            "out-of-range-index": 16,
        }.get(mutation, 1)
        cursor = emit(cursor, "66c7442414" + index.to_bytes(2, "little").hex())
    cursor = emit_call(cursor, initializer)
    cursor = emit(cursor, "8d042450")
    cursor = emit_call(cursor, consumer)
    emit(cursor, "83c40483c420c3")

    cursor = emit(initializer, "31c9")
    zero_loop = cursor
    cursor = emit_absolute(cursor, "c7048d", heads)
    cursor = emit(cursor, "00000000")
    cursor = emit(cursor, "4183f910")
    loop_branch = cursor
    cursor = emit(cursor, "7c00")
    cursor = emit(cursor, "6a08")
    cursor = emit_call(cursor, allocator)
    cursor = emit_absolute(cursor, "c74004", callback)
    cursor = emit_absolute(cursor, "8b15", heads + 4)
    cursor = emit(cursor, "8910")
    cursor = emit_absolute(cursor, "a3", heads + 4)
    emit(cursor, "c3")
    patch_short_branch(loop_branch, zero_loop)

    cursor = emit_absolute(allocator, "b8", node)
    emit(cursor, "c3")

    cursor = emit(consumer, "56538b5c240c0fbf4314")
    cursor = emit_absolute(cursor, "8b3485", heads)
    cursor = emit(cursor, "85f6")
    done_branch = cursor
    cursor = emit(cursor, "7400")
    callback_loop = cursor
    if mutation in {"cursor-callback-writer", "cursor-next-writer"}:
        cursor = emit(cursor, "56")
        cursor = emit_call(cursor, cursor_mutator)
        cursor = emit(cursor, "83c404")
    cursor = emit(cursor, "53")
    callback_call = cursor
    cursor = emit(cursor, "ff5604")
    cursor = emit(cursor, "83c4048b3685f6")
    loop_again = cursor
    cursor = emit(cursor, "7500")
    done = cursor
    emit(cursor, "5b5ec3")
    patch_short_branch(done_branch, done)
    patch_short_branch(loop_again, callback_loop)
    emit(callback, "c3")

    # Keep the generic finite-field resolver honest: an unrelated open +4
    # writer means only the linked-registry escape proof can close this call.
    emit(unrelated_field_writer, "894a04c3")
    if mutation == "cursor-callback-writer":
        emit(cursor_mutator, "8b442404895004c3")
    elif mutation == "cursor-next-writer":
        emit(cursor_mutator, "8b4424048910c3")
    extra_seeds = [unrelated_field_writer]
    if mutation == "hidden-index-caller":
        cursor = emit(hidden_caller, "52")
        cursor = emit_call(cursor, consumer)
        emit(cursor, "59c3")
        extra_seeds.append(hidden_caller)
    if mutation == "alternate-head-writer":
        cursor = emit_absolute(alternate_writer, "8915", heads + 4)
        emit(cursor, "c3")
        extra_seeds.append(alternate_writer)

    image_data = bytearray(text)
    image_data.extend(b"\0" * 0x300)
    image_bytes = bytes(image_data)
    image = pe.Image(
        data=image_bytes,
        sha256=hashlib.sha256(image_bytes).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=root,
        directories=(),
        sections=(
            pe.Section(
                ".text",
                text_va,
                0,
                len(text),
                len(text),
                0x60000020,
            ),
            pe.Section(
                ".data",
                data_va,
                len(text),
                0x300,
                0x300,
                0xC0000040,
            ),
        ),
        imports=(),
        exports=(),
        relocations=tuple(sorted(relocations, key=lambda row: row.va)),
        executable_ranges=((text_va, text_va + len(text)),),
    )
    assert image.read(heads, 64) == b"\0" * 64
    return image, callback_call, callback, tuple(extra_seeds)


def test_registered_linked_callback_is_closed():
    image, call_site, callback, extra_seeds = registered_linked_callback_image()
    cfg = recover_cfg(
        image,
        (image.entrypoint, *extra_seeds),
        generous_limits(image),
    )

    assert any(
        row.source == call_site and row.target == callback and row.kind == "indirect-call-registered-linked-callback"
        for row in cfg.edges
    )
    record = next(row for row in cfg.seed_inventory.records if row.category == "registered-linked-callback")
    assert record.address == callback
    assert "head-base=0x402000;heads=16" in record.detail
    assert "signed-indices=1" in record.detail


@pytest.mark.parametrize(
    "mutation",
    (
        "negative-index",
        "out-of-range-index",
        "unknown-index-writer",
        "hidden-index-caller",
        "alternate-head-writer",
        "cursor-callback-writer",
        "cursor-next-writer",
    ),
)
def test_registered_linked_callback_rejects_open_provenance(mutation):
    image, call_site, callback, extra_seeds = registered_linked_callback_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        (image.entrypoint, *extra_seeds),
        generous_limits(image),
    )

    assert not any(
        row.source == call_site and row.target == callback and row.kind == "indirect-call-registered-linked-callback"
        for row in cfg.edges
    )
    assert any(
        row.address == call_site
        and row.kind == "computed-flow-blocker"
        and "registered linked callback provenance is open" in row.detail
        for row in cfg.ownership_diagnostics
    )


def finite_incoming_edge_image():
    """Finite calls where a later edge expands an earlier caller domain."""
    text_va = 0x00401000
    text = bytearray(b"\x90" * 0xE0)
    consumer = text_va + 0x40
    source = text_va + 0x80
    first_target = text_va + 0xC0
    second_target = text_va + 0xD0

    # root(): consumer(first_target)
    text[0:13] = bytes.fromhex("68 c0 10 40 00 e8 36 00 00 00 83 c4 04")
    text[13] = 0xC3

    # consumer(callback): callback()
    text[0x40:0x47] = bytes.fromhex("8b 44 24 04 ff d0 c3")

    # source(): consumer(second_target), initially through a finite call edge.
    text[0x80:0x8F] = bytes.fromhex("68 d0 10 40 00 b8 40 10 40 00 ff d0 83 c4 04")
    text[0x8F] = 0xC3
    text[0xC0] = 0xC3
    text[0xD0] = 0xC3

    image = pe.Image(
        data=bytes(text),
        sha256=hashlib.sha256(text).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(
                ".text",
                text_va,
                0,
                len(text),
                len(text),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(
            pe.Relocation(text_va + 1, 3),
            pe.Relocation(source + 1, 3),
        ),
        executable_ranges=((text_va, text_va + len(text)),),
    )
    return image, consumer, source, first_target, second_target


def finite_new_code_image():
    """Two finite calls, with only the first target initially undecoded."""
    text_va = 0x00401000
    second_source = text_va + 0x40
    new_target = text_va + 0x80
    decoded_target = text_va + 0x90
    text = bytearray(b"\x90" * 0xA0)
    text[0:8] = bytes.fromhex("b8 80 10 40 00 ff d0 c3")
    text[0x40:0x48] = bytes.fromhex("b8 90 10 40 00 ff d0 c3")
    text[0x80] = 0xC3
    text[0x90] = 0xC3
    image = pe.Image(
        data=bytes(text),
        sha256=hashlib.sha256(text).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(
                ".text",
                text_va,
                0,
                len(text),
                len(text),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(
            pe.Relocation(text_va + 1, 3),
            pe.Relocation(second_source + 1, 3),
        ),
        executable_ranges=((text_va, text_va + len(text)),),
    )
    return image, second_source, new_target, decoded_target


def test_function_entry_provenance_materialization_is_single_pass():
    class SinglePassRecords:
        def __init__(self, records):
            self.records = records
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations != 1:
                raise AssertionError("seed provenance was rescanned")
            yield from self.records

    records = SinglePassRecords(
        (
            SeedRecord(0x20, "zeta", 0x10, "90", "z", True),
            SeedRecord(0x20, "alpha", 0x10, "90", "a", True),
            SeedRecord(0x20, "ignored", 0x10, "90", "n", False),
        )
    )
    entries = _materialize_function_entries((0x30, 0x20), records)
    assert records.iterations == 1
    assert tuple(row.address for row in entries) == (0x20, 0x30)
    assert entries[0].provenance == ("alpha", "zeta")
    assert entries[1].provenance == ("derived-function-target",)


def test_cfg_seed_initialization_groups_records_in_one_pass(
    synthetic_cfg_image,
):
    class SinglePassRecords:
        def __init__(self, records):
            self.records = records
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations != 1:
                raise AssertionError("seed records were rescanned by address")
            yield from self.records

    class Inventory:
        def __init__(self, records):
            self.records = records

        @property
        def addresses(self):
            return tuple(sorted({row.address for row in self.records.records}))

    records = SinglePassRecords(
        (
            SeedRecord(0x00401000, "entrypoint", 0, "90", "entry", True),
            SeedRecord(0x00401070, "audit-anchor", 0, "c3", "anchor", True),
        )
    )

    _DirectCfgRecovery(
        synthetic_cfg_image,
        Inventory(records),
        generous_limits(synthetic_cfg_image),
    )

    assert records.iterations == 1


def cw_exception_image(*, mutation=None):
    data = bytearray(0x500)
    text_va = 0x00401000
    rdata_va = 0x00402000
    exc_va = 0x00403000
    data[0x00:0x1C] = bytes.fromhex(
        "8b 44 24 04 8b 48 06 8b 44 24 08 8b 18 8b 70 04 8b 78 08 8b 68 0c db e3 90 9b ff e1"
    )
    data[0x50] = data[0x60] = data[0x70] = 0xC3

    # One packed complex function record.  Its intentionally unaligned u32
    # fields mirror the retail CodeWarrior layout.
    data[0x100] = 0
    data[0x101:0x105] = (rdata_va + 0x20).to_bytes(4, "little")
    data[0x105:0x107] = (3).to_bytes(2, "little")
    data[0x107:0x10F] = (text_va + 7).to_bytes(4, "little") + (rdata_va + 0x20).to_bytes(4, "little")
    data[0x10F:0x117] = (text_va + 0x10).to_bytes(4, "little") + (rdata_va + 0x2A).to_bytes(4, "little")
    data[0x117:0x11F] = (text_va + 0x18).to_bytes(4, "little") + (rdata_va + 0x34).to_bytes(4, "little")

    # Kinds 1 and 10 are both ten-byte records with a relocated callback at
    # +6.  The high bit terminates each action chain.
    data[0x120:0x12A] = bytes.fromhex("01 80 00 00 00 00 50 10 40 00")
    data[0x12A:0x134] = bytes.fromhex("0a 80 00 00 00 00 60 10 40 00")
    data[0x134:0x142] = bytes.fromhex("10 80 00 00 00 00 70 10 40 00 00 00 00 00")

    data[0x300:0x30C] = (
        text_va.to_bytes(4, "little") + rdata_va.to_bytes(4, "little") + (0xFFFF_FFFF).to_bytes(4, "little")
    )
    relocations = {
        exc_va,
        exc_va + 4,
        rdata_va + 1,
        rdata_va + 7,
        rdata_va + 11,
        rdata_va + 15,
        rdata_va + 19,
        rdata_va + 23,
        rdata_va + 27,
        rdata_va + 0x26,
        rdata_va + 0x30,
        rdata_va + 0x3A,
    }
    if mutation == "missing-sentinel":
        data[0x308:0x30C] = b"\0" * 4
    elif mutation == "unaligned-action":
        data[0x101:0x105] = (rdata_va + 0x21).to_bytes(4, "little")
    elif mutation == "missing-packed-relocation":
        relocations.remove(rdata_va + 7)
    elif mutation == "incomplete-context-restore":
        data[0x10:0x13] = b"\x90" * 3
    elif mutation is not None:
        raise ValueError(mutation)

    return pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(".text", text_va, 0, 0x100, 0x100, 0x60000020),
            pe.Section(".rdata", rdata_va, 0x100, 0x100, 0x100, 0x40000040),
            pe.Section(".exc", exc_va, 0x300, 0x0C, 0x0C, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe.Relocation(address, 3) for address in sorted(relocations)),
        executable_ranges=((text_va, text_va + 0x100),),
    )


def cw_k17_image(
    *,
    clobbered_guard_alias=False,
    clobbered_cleanup_frame=False,
    decoy_builder=False,
    poison_generic_field=False,
    registered_cleanup_with_zero=False,
    unknown_constructor=False,
):
    text_va = 0x00401000
    rdata_va = 0x00402000
    exc_va = 0x00403000
    data = bytearray(0x700)
    text = memoryview(data)[:0x400]

    # Runtime action-kind dispatch: low byte of the packed u16 tag, minus one.
    text[0x000:0x020] = bytes.fromhex(
        "66 8b 11 0f b7 c2 89 d7 25 ff 00 00 00 2d 01 00 00 00 3d 12 00 00 00 77 07 ff 24 85 00 21 40 00"
    )
    text[0x020] = 0xC3
    text[0x030] = 0xC3
    text[0x040:0x05A] = bytes.fromhex("83 78 08 00 89 c1 74 11 8b 01 85 c0 75 02 eb 09 89 c8 8b 08 ff 50 08 c3 90 c3")
    if clobbered_guard_alias:
        text[0x045] = 0xD1

    # Builder copies wrapper argument 2 from context+0x1c into cleanup node+8.
    text[0x100:0x108] = bytes.fromhex("8b 58 1c 89 5a 08 c3 90")
    text[0x120:0x12E] = bytes.fromhex("55 89 e5 83 ec 24 8b 45 10 89 44 24 1c 54")
    struct.pack_into("<Bi", text, 0x12E, 0xE8, 0x00401100 - 0x00401133)
    text[0x133] = 0xC3

    # Closed constructor caller supplies one exact destructor.
    text[0x160:0x165] = b"\x68" + (text_va + 0x1A0).to_bytes(4, "little")
    text[0x165:0x169] = bytes.fromhex("6a 00 6a 00")
    struct.pack_into("<Bi", text, 0x169, 0xE8, 0x00401120 - 0x0040116E)
    text[0x16E:0x172] = bytes.fromhex("83 c4 0c c3")
    text[0x1A0] = 0xC3

    seed_addresses = [text_va, text_va + 0x160]
    if unknown_constructor:
        text[0x1C0:0x1C5] = bytes.fromhex("50 6a 00 6a 00")
        struct.pack_into("<Bi", text, 0x1C5, 0xE8, 0x00401120 - 0x004011CA)
        text[0x1CA:0x1CE] = bytes.fromhex("83 c4 0c c3")
        seed_addresses.append(text_va + 0x1C0)
    if decoy_builder:
        text[0x200:0x207] = bytes.fromhex("8b 40 1c 89 42 08 c3")
        seed_addresses.append(text_va + 0x200)
    if poison_generic_field:
        text[0x220:0x224] = bytes.fromhex("89 4a 08 c3")
        seed_addresses.append(text_va + 0x220)
    if registered_cleanup_with_zero:
        text[0x240:0x24C] = bytes.fromhex("55 89 e5 83 ec 04 6a 00 6a 00 6a 00")
        struct.pack_into("<Bi", text, 0x24C, 0xE8, 0x00401120 - 0x00401251)
        text[0x251:0x25D] = (
            bytes.fromhex("83 c4 0c 68") + (text_va + 0x1A0).to_bytes(4, "little") + bytes.fromhex("6a 00 6a 00")
        )
        struct.pack_into("<Bi", text, 0x25D, 0xE8, 0x00401120 - 0x00401262)
        text[0x262:0x273] = bytes.fromhex("83 c4 0c 89 45 fc 83 7d fc 00 74 03 ff 55 fc c9 c3")
        text[0x271:0x276] = bytes.fromhex("8b 65 f8 c9 c3")
        if clobbered_cleanup_frame:
            text[0x26C:0x278] = bytes.fromhex("74 05 89 c5 ff 55 fc 8b 65 f8 c9 c3")
        seed_addresses.append(text_va + 0x240)

    # One complex function map referring to a terminal kind-17 action.
    data[0x400] = 0
    data[0x401:0x405] = (rdata_va + 0x40).to_bytes(4, "little")
    data[0x405:0x407] = (1).to_bytes(2, "little")
    data[0x407:0x40F] = (text_va + 0x20).to_bytes(4, "little") + (rdata_va + 0x40).to_bytes(4, "little")
    data[0x440:0x446] = bytes.fromhex("11 80 e8 ff ff ff")
    for index in range(19):
        target = text_va + 0x40 if index == 16 else text_va + 0x30
        struct.pack_into("<I", data, 0x500 + index * 4, target)
    data[0x600:0x60C] = (
        text_va.to_bytes(4, "little") + rdata_va.to_bytes(4, "little") + (0xFFFF_FFFF).to_bytes(4, "little")
    )
    relocation_addresses = [
        pe.Relocation(text_va + 0x161, 3),
        pe.Relocation(rdata_va + 1, 3),
        pe.Relocation(rdata_va + 7, 3),
        pe.Relocation(rdata_va + 11, 3),
        pe.Relocation(exc_va, 3),
        pe.Relocation(exc_va + 4, 3),
    ]
    if registered_cleanup_with_zero:
        relocation_addresses.append(pe.Relocation(text_va + 0x255, 3))
    image = pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(".text", text_va, 0, 0x400, 0x400, 0x60000020),
            pe.Section(".rdata", rdata_va, 0x400, 0x200, 0x200, 0x40000040),
            pe.Section(".exc", exc_va, 0x600, 0x0C, 0x0C, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(relocation_addresses),
        executable_ranges=((text_va, text_va + 0x400),),
    )
    return image, tuple(seed_addresses)


def test_strict_cw_exception_parser_accepts_packed_unaligned_fields():
    image = cw_exception_image()
    metadata = parse_cw_exception_metadata(image, generous_limits(image))
    assert metadata is not None
    assert metadata.range_table == ((0x00401000, 0x00402000),)
    assert metadata.landing_sites == (
        0x00401007,
        0x00401010,
        0x00401018,
    )
    assert metadata.action_kinds == (1, 10, 16)
    assert metadata.direct_callbacks == (0x00401050, 0x00401060)
    assert metadata.continuation_targets == ((16, 0x00401070),)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-sentinel", "sentinel"),
        ("unaligned-action", "action.*aligned"),
        ("missing-packed-relocation", "relocation"),
    ],
)
def test_strict_cw_exception_parser_rejects_malformed_metadata(mutation, message):
    image = cw_exception_image(mutation=mutation)
    with pytest.raises(CfgRecoveryError, match=message):
        parse_cw_exception_metadata(image, generous_limits(image))


@pytest.mark.parametrize(
    "limit_name",
    [
        "max_exception_entries",
        "max_exception_actions",
        "max_exception_landing_sites",
    ],
)
def test_strict_cw_exception_parser_obeys_structural_caps(limit_name):
    image = cw_exception_image()
    limits = replace(generous_limits(image), **{limit_name: 1})
    with pytest.raises(AnalysisLimitError, match=limit_name):
        parse_cw_exception_metadata(image, limits)


def test_cw_packed_continuation_jump_uses_only_registered_kind_targets():
    image = cw_exception_image()
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    assert cfg.cw_exception_metadata == parse_cw_exception_metadata(image, generous_limits(image))
    assert b'"record_kind":"cw-exception-metadata"' in canonical_jsonl_bytes(cfg)
    edges = {
        (row.source, row.target, row.flow_kind)
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040101A
    }
    assert edges == {
        (
            0x0040101A,
            0x00401070,
            "indirect-jump-cw-exception-continuation",
        )
    }
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x0040101A]


def test_cw_continuation_without_complete_context_restore_stays_blocking():
    image = cw_exception_image(mutation="incomplete-context-restore")
    cfg = recover_cfg(image, (image.entrypoint,), generous_limits(image))
    unresolved = [row for row in cfg.control_targets.unresolved if row.address == 0x0040101A]
    assert len(unresolved) == 1
    assert "unresolved indirect jump" in unresolved[0].detail


def test_cw_k17_destructor_domain_is_derived_from_constructor_store():
    image, seeds = cw_k17_image()
    cfg = recover_cfg(image, seeds, generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401054 and row.flow_kind == "indirect-call-cw-exception-k17"
    )
    assert edge.target == 0x004011A0
    assert "cw-k17-builder=0x401100" in edge.provenance
    assert "wrapper=0x401120" in edge.provenance


def test_cw_k17_ignores_unlinked_builder_shaped_decoy():
    image, seeds = cw_k17_image(decoy_builder=True)
    cfg = recover_cfg(image, seeds, generous_limits(image))
    edges = [
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401054 and row.flow_kind == "indirect-call-cw-exception-k17"
    ]
    assert {row.target for row in edges} == {0x004011A0}


def test_cw_k17_clobbered_prebranch_alias_keeps_callback_blocking():
    image, seeds = cw_k17_image(
        clobbered_guard_alias=True,
        poison_generic_field=True,
    )
    cfg = recover_cfg(image, seeds, generous_limits(image))
    unresolved = [row for row in cfg.control_targets.unresolved if row.address == 0x00401054]
    assert len(unresolved) == 1


def test_cw_k17_unknown_constructor_caller_keeps_callback_blocking():
    image, seeds = cw_k17_image(unknown_constructor=True)
    cfg = recover_cfg(image, seeds, generous_limits(image))
    unresolved = [row for row in cfg.control_targets.unresolved if row.address == 0x00401054]
    assert len(unresolved) == 1
    assert "unresolved indirect call" in unresolved[0].detail


def test_cw_registered_cleanup_ignores_proven_zero_registration():
    image, seeds = cw_k17_image(registered_cleanup_with_zero=True)
    cfg = recover_cfg(image, seeds, generous_limits(image))
    edges = [
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040126E and row.flow_kind == "indirect-call-cw-registered-destructor"
    ]
    assert {row.target for row in edges} == {0x004011A0}


def test_cw_registered_cleanup_rejects_clobbered_frame_base():
    image, seeds = cw_k17_image(
        clobbered_cleanup_frame=True,
        registered_cleanup_with_zero=True,
    )
    cfg = recover_cfg(image, seeds, generous_limits(image))
    unresolved = [row for row in cfg.control_targets.unresolved if row.address == 0x00401270]
    assert len(unresolved) == 1


def test_cw_k17_domain_cache_tracks_incoming_edge_revision(monkeypatch):
    image, seeds = cw_k17_image()
    recovery = _DirectCfgRecovery(
        image,
        x86_cfg_module._explicit_seed_inventory(image, seeds),
        generous_limits(image),
    )
    recovery.recover()
    recovery.cw_k17_domain_cache.clear()
    recovery.cw_k17_wrapper_cache.clear()
    initial_revision = recovery.control_flow_revision
    evaluations = 0

    def changing_builder_domain(_recovery, builder):
        nonlocal evaluations
        assert builder == 0x00401100
        evaluations += 1
        callbacks = {0x004011A0}
        if _recovery.control_flow_revision != initial_revision:
            callbacks.add(0x00401030)
        return 0x00401120, frozenset(callbacks), "test-k17-domain"

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_cw_k17_builder_domain",
        changing_builder_domain,
    )

    first = recovery._cw_k17_destructor_domain()
    recovery._add_edge(
        0x00401000,
        0x00401030,
        "indirect-call-test-late-incoming",
    )
    second = recovery._cw_k17_destructor_domain()

    assert first is not None and first[0] == frozenset({0x004011A0})
    assert second is not None and second[0] == frozenset({0x00401030, 0x004011A0})
    assert evaluations == 2


def load_dispatch_image(tmp_path, *, entry_count=2, mode="absolute-jump"):
    path = write_synthetic_dispatch_pe(tmp_path, entry_count=entry_count, mode=mode)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(path, expected_sha256=digest, require_pe32_i386=True)


def dispatch_cfg(tmp_path, *, entry_count=2, mode="absolute-jump"):
    image = load_dispatch_image(tmp_path, entry_count=entry_count, mode=mode)
    return recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))


def test_guarded_absolute_jump_table_records_complete_provenance(tmp_path):
    cfg = dispatch_cfg(tmp_path)
    table = cfg.jump_table_at(0x0040100B)
    assert isinstance(table, JumpTable)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.base,
        table.entry_width,
        table.index_min,
        table.index_max,
    ) == (0x00401000, "ja", 1, 0x00402200, 4, 0, 1)
    assert table.raw_entries == (0x00401020, 0x00401060)
    assert table.targets == (0x00401020, 0x00401060)
    assert {row.category for row in cfg.seed_inventory.records} >= {"jump-table-entry"}
    assert not [
        row for row in cfg.ownership_diagnostics if row.address == table.address and row.kind == "indirect-flow"
    ]


def test_guarded_base_plus_index_jump_table_is_recovered(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="base-index-jump")
    table = cfg.jump_table_at(0x00401010)
    assert table.base == 0x00402200
    assert table.targets == (0x00401020, 0x00401060)


def test_guard_search_skips_non_flag_non_index_register_moves(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="nonadjacent-guard")
    table = cfg.jump_table_at(0x0040100D)
    assert table.guard_address == 0x00401000
    assert (table.index_min, table.index_max) == (0, 1)


def movzx_dispatch_image(
    *,
    unrelocated_indices=(),
    non_executable_indices=(),
    caller_saved_index=False,
    intervening_call=False,
    closed_producer_bound=None,
    unknown_producer_write=False,
    producer_proof_after_ordinary_round=False,
    duplicate_consumer_transfer=False,
):
    """Synthetic PE with ``movzx ebx, byte ptr [eax]; call [ebx*4+TABLE]``."""
    import struct

    from tools.mwcc_retro import pe as pe_mod

    TEXT_VA = 0x00401000
    RDATA_VA = 0x00402000
    # Reserve space for 256 table entries (1024 bytes) + text
    data = bytearray(0x600)

    # Entry: movzx index, byte ptr [eax] ; optional call ;
    # call [index*4 + TABLE] ; ret
    text = memoryview(data)[:0x100]
    if closed_producer_bound is None:
        text[0x00:0x03] = bytes.fromhex("0f b6 10" if caller_saved_index else "0f b6 18")
        transfer_offset = 3
        if intervening_call:
            text[0x03:0x08] = bytes.fromhex("e8 28 00 00 00")
            text[0x30] = 0xC3
            transfer_offset = 8
        sib = "95" if caller_saved_index else "9d"
        text[transfer_offset : transfer_offset + 7] = bytes.fromhex(f"ff 14 {sib} 00 20 40 00")
        text[transfer_offset + 7] = 0xC3
        entry_count = 256
        target_offset = 0x20
    else:
        # The entrypoint has two closed construction sites for the same stack
        # object type.  Their immediate tags prove the producer domain's
        # endpoints without deriving anything from the relocation run.
        # The optional unbounded write must poison that closed producer domain.
        assert 0 <= closed_producer_bound <= 0x7F
        text[0x00:0x0B] = bytes.fromhex("83 ec 04 c6 04 24 00 8d 04 24 50")
        cursor = 0x0B
        for producer_index in range(2):
            next_address = TEXT_VA + cursor + 5
            text[cursor] = 0xE8
            text[cursor + 1 : cursor + 5] = (TEXT_VA + 0x40 - next_address).to_bytes(4, "little", signed=True)
            cursor += 5
            text[cursor : cursor + 3] = bytes.fromhex("83 c4 04")
            cursor += 3
            if producer_index == 0:
                text[cursor : cursor + 4] = bytes.fromhex(f"c6 04 24 {closed_producer_bound:02x}")
                cursor += 4
                if unknown_producer_write:
                    text[cursor : cursor + 3] = bytes.fromhex("88 14 24")
                    cursor += 3
                text[cursor : cursor + 4] = bytes.fromhex("8d 04 24 50")
                cursor += 4
        if producer_proof_after_ordinary_round:
            # An ordinary guarded table must expand and decode its target
            # closure before the more expensive producer-domain pass runs.
            text[cursor : cursor + 18] = bytes.fromhex("83 c4 04 31 c0 83 f8 00 77 07 ff 24 85 30 21 40 00 c3")
            struct.pack_into("<I", data, 0x230, TEXT_VA + 0x90)
            text[0x90:0x96] = bytes.fromhex("e8 0b 00 00 00 c3")
            text[0xA0] = 0xC3
        else:
            text[cursor : cursor + 4] = bytes.fromhex("83 c4 04 c3")

        # consumer(object): movzx tag, byte ptr [object]; call table[tag]
        # The optional second call has the identical producer slice so the
        # memoization proof can distinguish query count from evaluation count.
        consumer = bytes.fromhex("8b 44 24 04 0f b6 18 ff 14 9d 00 20 40 00 ")
        if duplicate_consumer_transfer:
            consumer += bytes.fromhex("ff 14 9d 00 20 40 00")
        consumer += b"\xc3"
        text[0x40 : 0x40 + len(consumer)] = consumer
        transfer_offset = 0x47
        entry_count = 75
        target_offset = 0x70

    # Fill all 256 dispatch table entries with RVA 0x1020 (type-3 relocation
    # adds image_base to make 0x401020 at load time).
    unrelocated_indices = frozenset(unrelocated_indices)
    non_executable_indices = frozenset(non_executable_indices)
    for i in range(entry_count):
        if i in unrelocated_indices:
            value = 0x41414141
        elif i in non_executable_indices:
            value = RDATA_VA
        else:
            value = 0x1000 + target_offset
        struct.pack_into("<I", data, 0x100 + i * 4, value)
    if producer_proof_after_ordinary_round:
        text[target_offset : target_offset + 6] = bytes.fromhex("e8 0b 00 00 00 c3")
        text[target_offset + 0x10] = 0xC3
    else:
        text[target_offset] = 0xC3  # target function

    # Add type-3 relocations for each table entry
    relocations = tuple(
        pe_mod.Relocation(RDATA_VA + i * 4, 3) for i in range(entry_count) if i not in unrelocated_indices
    )

    return pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=TEXT_VA,
        directories=(),
        sections=(
            pe_mod.Section(".text", TEXT_VA, 0, 0x100, 0x100, 0x60000020),
            pe_mod.Section(".rdata", RDATA_VA, 0x100, 0x400, 0x400, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=relocations,
        executable_ranges=((TEXT_VA, TEXT_VA + 0x100),),
    )


def cyclic_relocated_movzx_dispatch_image(
    *,
    producer_high=2,
    entry_count=75,
    missing_relocation_index=None,
    non_executable_index=None,
    instruction_interior_index=None,
    tentative_target_overlap=False,
    executable_table=False,
    raw_only_transfer=False,
    bottom_producer=False,
):
    """Relocated callback run whose callers close the movzx producer.

    Only the consumer is initially seeded.  Its raw direct callers live in
    callbacks referenced by the otherwise unresolved dispatch table, so the
    producer domain cannot close until a trial decodes those callbacks.
    """
    from tools.mwcc_retro import pe as pe_mod

    assert 1 <= producer_high < entry_count
    text_va = 0x00401000
    rdata_va = 0x00402000
    consumer = text_va
    callback_low = text_va + 0x40
    callback_high = text_va + 0x60
    in_domain_filler = text_va + 0x80
    unused_callback = text_va + 0xA0
    raw_entrypoint = text_va + 0xE0
    table_base = text_va + 0x100 if executable_table else rdata_va
    table_raw_offset = 0x100 if executable_table else 0x300
    rdata_raw_size = max(0x400, (entry_count + 1) * 4)
    data = bytearray(b"\0" * (0x300 + rdata_raw_size))
    text = memoryview(data)[:0x300]

    def emit(address, encoded):
        encoded = bytes.fromhex(encoded)
        offset = address - text_va
        text[offset : offset + len(encoded)] = encoded
        return address + len(encoded)

    def emit_call(address, target):
        displacement = target - (address + 5)
        return emit(
            address,
            "e8" + displacement.to_bytes(4, "little", signed=True).hex(),
        )

    # consumer(object): the owned transfer identifies TABLE, but its byte
    # producer is initially bottom because both raw callers are unreachable.
    cursor = consumer
    cursor = emit(cursor, "8b442404")
    movzx_address = cursor
    cursor = emit(cursor, "0fb618")
    transfer_address = cursor
    cursor = emit(
        cursor,
        "ff149d" + table_base.to_bytes(4, "little").hex(),
    )
    emit(cursor, "c3")

    def emit_producer_callback(address, value):
        cursor = emit(address, "83ec04")
        cursor = emit(cursor, f"c60424{value:02x}")
        cursor = emit(cursor, "8d042450")
        if bottom_producer:
            return emit(cursor, "83c408c3")
        cursor = emit_call(cursor, consumer)
        return emit(cursor, "83c408c3")

    emit_producer_callback(callback_low, 0)
    emit_producer_callback(callback_high, producer_high)
    emit(in_domain_filler, "c3")
    emit(unused_callback, "c3")
    emit(raw_entrypoint, "c3")

    relocations = []
    for index in range(entry_count):
        if index == 0:
            target = callback_low
        elif index == producer_high:
            target = callback_high
        elif index < producer_high:
            target = in_domain_filler
        else:
            target = unused_callback
        if index == non_executable_index:
            target = rdata_va
        if index == instruction_interior_index:
            target = movzx_address + 1
        if tentative_target_overlap and index == 0:
            target = callback_low + 1
        elif tentative_target_overlap and index == 1:
            target = callback_low
        struct.pack_into("<I", data, table_raw_offset + index * 4, target)
        if index != missing_relocation_index:
            relocations.append(pe_mod.Relocation(table_base + index * 4, 3))
    struct.pack_into("<I", data, table_raw_offset + entry_count * 4, 0)

    return (
        pe_mod.Image(
            data=bytes(data),
            sha256=hashlib.sha256(data).hexdigest(),
            machine=0x14C,
            optional_magic=0x10B,
            image_base=0x00400000,
            size_of_headers=0,
            entrypoint=raw_entrypoint if raw_only_transfer else consumer,
            directories=(),
            sections=(
                pe_mod.Section(".text", text_va, 0, 0x300, 0x300, 0x60000020),
                pe_mod.Section(
                    ".rdata",
                    rdata_va,
                    0x300,
                    rdata_raw_size,
                    rdata_raw_size,
                    0x40000040,
                ),
            ),
            imports=(),
            exports=(),
            relocations=tuple(relocations),
            executable_ranges=((text_va, text_va + 0x300),),
        ),
        transfer_address,
        (
            callback_low,
            in_domain_filler,
            callback_high,
            unused_callback,
        ),
    )


def unrooted_mutual_recursion_image():
    """Two syntactic raw functions with no independent control root."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    entrypoint = text_va
    left = text_va + 0x40
    right = text_va + 0x60
    data = bytearray(b"\x90" * 0x100)
    data[0] = 0xC3
    data[left - text_va] = 0xE8
    data[left - text_va + 1 : left - text_va + 5] = (right - (left + 5)).to_bytes(4, "little", signed=True)
    data[left - text_va + 5] = 0xC3
    data[right - text_va] = 0xE8
    data[right - text_va + 1 : right - text_va + 5] = (left - (right + 5)).to_bytes(4, "little", signed=True)
    data[right - text_va + 5] = 0xC3
    return pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=entrypoint,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )


def forwarded_movzx_dispatch_image(
    *,
    unknown_producer_write=False,
    alternate_unknown_caller=False,
    unowned_raw_caller=False,
    helper_clobbers_byte=False,
    duplicate_consumer_dispatch=False,
    callback_clobbers_byte=False,
    consumer_bypass_unknown_callback=False,
    consumer_bypass_rejoins=False,
    consumer_bypass_mutates_before_rejoin=False,
    consumer_stack_spill=None,
    conditional_helper_return=None,
    unrelated_helper_caller=False,
):
    """Real-shape byte-tag dispatch through a returned/forwarded field.

    The entrypoint constructs one stack-backed node and a container whose
    ``+0xa`` field points at that node.  A wrapper obtains the container from
    an identity return, forwards the node field through a preserving helper,
    and calls a consumer.  The consumer pushes the node before loading byte
    zero and dispatching through the 75-entry table, matching the retail
    ordering that requires preservation only up to the MOVZX.
    """
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    rdata_va = 0x00402000
    data = bytearray(0x600)
    text = memoryview(data)[:0x200]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # entry(): construct node byte zero values 0 and 74, and pass a
    # container holding the node pointer through the complete caller domain.
    cursor = 0
    cursor = emit(cursor, "83 ec 20")
    cursor = emit(cursor, "c6 04 24 00")
    if conditional_helper_return:
        cursor = emit(cursor, "c6 44 24 04 00")
    cursor = emit(cursor, "8d 04 24")
    cursor = emit(cursor, "89 44 24 12")
    if conditional_helper_return:
        cursor = emit(cursor, "8d 54 24 04")
        cursor = emit(cursor, "89 54 24 16")
    cursor = emit(cursor, "8d 4c 24 08 51")
    cursor = emit_call(cursor, 0x50)
    cursor = emit(cursor, "83 c4 04")
    cursor = emit(cursor, "c6 04 24 4a")
    if conditional_helper_return:
        cursor = emit(cursor, "c6 44 24 04 4a")
    if unknown_producer_write:
        cursor = emit(cursor, "88 14 24")
    cursor = emit(cursor, "8d 4c 24 08 51")
    cursor = emit_call(cursor, 0x50)
    cursor = emit(cursor, "83 c4 04")
    if unrelated_helper_caller:
        cursor = emit(cursor, "ff 74 24 24")
        cursor = emit_call(cursor, 0xC0)
        cursor = emit(cursor, "83 c4 04")
    if alternate_unknown_caller:
        cursor = emit(cursor, "8b 54 24 24 52")
        cursor = emit_call(cursor, 0x50)
        cursor = emit(cursor, "83 c4 04")
    emit(cursor, "83 c4 20 c3")
    assert cursor < 0x50

    # wrapper(container): the container itself comes from a direct call
    # return; its +0xa node field is forwarded through a helper before use.
    cursor = 0x50
    cursor = emit(cursor, "56")
    cursor = emit(cursor, "8b 44 24 08 50")
    if conditional_helper_return:
        cursor = emit(cursor, "8b 70 0a")
        cursor = emit(cursor, "8b 78 0e")
        cursor = emit(cursor, "57 56")
        cursor = emit_call(cursor, 0xC0)
        cursor = emit(cursor, "83 c4 0c 50")
        cursor = emit_call(cursor, 0x80)
        cursor = emit(cursor, "59 5e c3")
    else:
        cursor = emit_call(cursor, 0xC0)
        cursor = emit(cursor, "59")
        cursor = emit(cursor, "8b 70 0a")
        cursor = emit(cursor, "56")
        cursor = emit_call(cursor, 0xD0)
        cursor = emit(cursor, "59 56")
        cursor = emit_call(cursor, 0x80)
        cursor = emit(cursor, "59 5e c3")
    assert cursor < 0x80

    # consumer(node): retail pushes the object before MOVZX and then passes
    # it to the computed callback.  Writes after MOVZX cannot affect its
    # already-loaded index and therefore must not poison the producer proof.
    assert not (consumer_bypass_unknown_callback and consumer_bypass_mutates_before_rejoin)
    assert not (consumer_bypass_mutates_before_rejoin and not consumer_bypass_rejoins)
    assert consumer_stack_spill in {
        None,
        "clean",
        "conflicting-store",
        "unrelated-ebp-write",
        "unknown-stack-delta",
        "overlap-write",
        "missing-dominating-store",
        "superseded-unknown-store",
    }
    assert not (consumer_stack_spill and (consumer_bypass_unknown_callback or consumer_bypass_mutates_before_rejoin))
    cursor = 0x80
    if consumer_stack_spill:
        cursor = emit(cursor, "83 ec 08")
        cursor = emit(cursor, "8b 44 24 0c")
        missing_store_branch = None
        if consumer_stack_spill == "missing-dominating-store":
            cursor = emit(cursor, "85 c9")
            missing_store_branch = cursor
            cursor = emit(cursor, "74 00")
        if consumer_stack_spill == "superseded-unknown-store":
            cursor = emit(cursor, "89 14 24")
        cursor = emit(cursor, "89 04 24")
        if missing_store_branch is not None:
            text[missing_store_branch + 1] = cursor - (missing_store_branch + 2)
        if consumer_stack_spill == "conflicting-store":
            cursor = emit(cursor, "85 c9 74 03 89 14 24")
        elif consumer_stack_spill == "unrelated-ebp-write":
            cursor = emit(cursor, "89 c5 c7 45 06 78 56 34 12")
        elif consumer_stack_spill == "overlap-write":
            cursor = emit(cursor, "88 54 24 01")
        cursor = emit_call(cursor, 0x110)
        if consumer_stack_spill == "unknown-stack-delta":
            cursor = emit(cursor, "01 cc")
        cursor = emit(cursor, "8d 4c 24 04 51")
        cursor = emit(cursor, "8b 44 24 04")
    else:
        cursor = emit(cursor, "8b 44 24 04")
    if consumer_bypass_unknown_callback or consumer_bypass_mutates_before_rejoin:
        cursor = emit(cursor, "80 78 05 00")
        observation_branch = cursor
        cursor = emit(cursor, "75 00")
        if consumer_bypass_unknown_callback:
            cursor = emit(cursor, "50 ff d2 59")
        else:
            cursor = emit(cursor, "c6 00 4b")
        bypass_jump = None
        if consumer_bypass_rejoins:
            bypass_jump = cursor
            cursor = emit(cursor, "eb 00")
        else:
            cursor = emit(cursor, "c3")
        observation_offset = cursor
        text[observation_branch + 1] = observation_offset - (observation_branch + 2)
        if bypass_jump is not None:
            text[bypass_jump + 1] = observation_offset - (bypass_jump + 2)
    cursor = emit(cursor, "50")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 18")
    transfer_offset = cursor
    cursor = emit(cursor, "ff 14 9d 00 20 40 00")
    cursor = emit(cursor, "83 c4 04")
    if consumer_stack_spill:
        cursor = emit(cursor, "83 c4 08")
    if duplicate_consumer_dispatch:
        cursor = emit(cursor, "8b 44 24 04 50")
        cursor = emit(cursor, "0f b6 18")
        cursor = emit(cursor, "ff 14 9d 00 20 40 00")
        cursor = emit(cursor, "83 c4 04")
    emit(cursor, "c3")

    # identity(container) and preserving/clobbering helper(node).
    assert conditional_helper_return in {
        None,
        "clean",
        "corrupt-and-use",
        "unknown-helper-return",
    }
    if conditional_helper_return:
        cursor = 0xC0
        cursor = emit(cursor, "53")
        cursor = emit(cursor, "8b 5c 24 08")
        cursor = emit(cursor, "85 c9")
        direct_return_branch = cursor
        cursor = emit(cursor, "74 00")
        cursor = emit(cursor, "ff 74 24 0c 53")
        cursor = emit_call(cursor, 0x120)
        cursor = emit(cursor, "59 59 89 c3")
        text[direct_return_branch + 1] = cursor - (direct_return_branch + 2)
        cursor = emit(cursor, "89 d8 5b c3")
    else:
        emit(0xC0, "8b 44 24 04 c3")
    if not conditional_helper_return:
        if helper_clobbers_byte:
            emit(0xD0, "8b 44 24 04 88 10 c3")
        else:
            emit(0xD0, "8b 44 24 04 8b 50 06 31 c0 c3")
    if callback_clobbers_byte:
        emit(0xF0, "8b 44 24 04 c6 00 ff c3")
    else:
        emit(0xF0, "c3")
    emit(0x110, "c3")
    if conditional_helper_return:
        cursor = 0x120
        cursor = emit(cursor, "53")
        cursor = emit(cursor, "8b 5c 24 08")
        cursor = emit(cursor, "30 db")
        if conditional_helper_return == "corrupt-and-use":
            cursor = emit(cursor, "8b 03 89 c3 89 d8 5b c3")
        else:
            cursor = emit(cursor, "ff 74 24 0c")
            if conditional_helper_return == "unknown-helper-return":
                cursor = emit(cursor, "ff d2")
            else:
                cursor = emit_call(cursor, 0x150)
            cursor = emit(cursor, "59 89 c3 89 d8 5b c3")
        emit(0x150, "8b 44 24 04 c3")

    if unowned_raw_caller:
        emit_call(0x1E0, 0x50)
        text[0x1E5] = 0xC3

    for index in range(75):
        struct.pack_into("<I", data, 0x200 + index * 4, 0x1000 + 0xF0)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x200, 0x400, 0x400, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, text_va + movzx_offset, text_va + transfer_offset


def recursive_nested_movzx_dispatch_image():
    """Self-recursive consumer whose argument field path grows per call."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    rdata_va = 0x00402000
    consumer = 0x80
    entry = 0xC0
    callback = 0xF0
    data = bytearray(0x600)
    text = memoryview(data)[:0x200]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # entry(): container+0xa points at one stack node with byte tag zero.
    cursor = emit(entry, "83 ec 20 c6 04 24 00 8d 04 24")
    cursor = emit(cursor, "89 44 24 12 8d 44 24 08 50")
    cursor = emit_call(cursor, consumer)
    emit(cursor, "83 c4 04 83 c4 20 c3")

    # consumer(arg0): dispatch on byte zero of arg0->+0xa, then recurse with
    # that nested pointer.  A finite proof must conservatively stop at the
    # recursive caller instead of growing (0xa, 0xa, ...) without bound.
    cursor = emit(consumer, "56 8b 74 24 08 8b 46 0a")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 18")
    cursor = emit(cursor, "8b 46 0a 50")
    cursor = emit_call(cursor, consumer)
    cursor = emit(cursor, "83 c4 04")
    transfer_offset = cursor
    cursor = emit(cursor, "ff 14 9d 00 20 40 00")
    emit(cursor, "5e c3")
    emit(callback, "c3")

    for index in range(75):
        struct.pack_into("<I", data, 0x200 + index * 4, text_va + callback)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va + entry,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x200, 0x400, 0x400, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, text_va + transfer_offset


def guarded_call_return_object_origins_image(
    *,
    affine_root_guard=True,
    disjoint_mutator=False,
    mutator_pointer_before_tag=False,
    disjoint_empty_child=False,
    guard_root_tag=True,
    guard_bypasses_load=False,
    unknown_matching_child=False,
):
    """Select a nested field only from call returns matching a root tag."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x200)
    text = memoryview(data)

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # entry(): root A has tag 4 and points at a child with tag 0x29.  Root B
    # has tag 5 and an intentionally unknown +0xa association.  The factory
    # may return either root, so only the consumer's exact tag-4 arm can
    # exclude root B before following +0xa.
    cursor = emit(0, "83 ec 40 c6 04 24 04")
    if not unknown_matching_child:
        cursor = emit(cursor, "c6 44 24 10 29")
    cursor = emit(cursor, "8d 44 24 10 89 44 24 0a")
    cursor = emit(cursor, "c6 44 24 20 05")
    if disjoint_empty_child:
        cursor = emit(cursor, "c7 44 24 2a 00 00 00 00")
    cursor = emit(cursor, "8d 04 24 8d 54 24 20 52 50")
    factory_call = text_va + cursor
    cursor = emit_call(cursor, 0x80)
    cursor = emit(cursor, "83 c4 08 50")
    consumer_call = text_va + cursor
    cursor = emit_call(cursor, 0xC0)
    emit(cursor, "83 c4 04 83 c4 40 c3")

    # factory(arg0, arg1): return either exact argument at a distinct RET.
    cursor = emit(0x80, "85 c9 74 05 8b 44 24 04 c3")
    emit(cursor, "8b 44 24 08 c3")

    # consumer(arg0): the fallthrough is dominated by arg0->tag == 4.
    cursor = emit(0xC0, "8b 44 24 04")
    if disjoint_mutator:
        cursor = emit(cursor, "50")
        cursor = emit_call(cursor, 0x100)
        cursor = emit(cursor, "83 c4 04")
    guard_branches = []
    if guard_root_tag:
        if affine_root_guard:
            cursor = emit(cursor, "0f b6 08 83 e9 30 74 00")
            guard_branches.append(cursor - 2)
            cursor = emit(cursor, "81 e9 d4 ff ff ff 75 00")
            guard_branches.append(cursor - 2)
        else:
            cursor = emit(cursor, "0f b6 08 83 e9 04 75 00")
            guard_branches.append(cursor - 2)
        cursor = emit(cursor, "85 d2 74 02 90 90")
    child_load = cursor
    cursor = emit(cursor, "8b 40 0a")
    observation = text_va + cursor
    cursor = emit(cursor, "0f b6 08 c3")
    if guard_branches:
        failure = cursor
        emit(cursor, "c3")
        for guard_branch in guard_branches[:-1]:
            text[guard_branch + 1] = failure - (guard_branch + 2)
        final_target = child_load if guard_bypasses_load else failure
        final_branch = guard_branches[-1]
        text[final_branch + 1] = final_target - (final_branch + 2)

    if disjoint_mutator:
        # mutator(root): one path preserves root.  The other publishes an
        # unknown child association and changes the root tag to 5.  Only the
        # tag-before-pointer ordering proves the open association irrelevant
        # to a downstream tag-4 observation.
        cursor = emit(0x100, "8b 44 24 04 85 d2 74 00")
        preserve_branch = cursor - 2
        if mutator_pointer_before_tag:
            cursor = emit(cursor, "c7 40 0a 00 30 40 00 c6 00 05")
        else:
            cursor = emit(cursor, "c6 00 05 c7 40 0a 00 30 40 00")
        preserved_return = cursor
        emit(cursor, "c3")
        text[preserve_branch + 1] = preserved_return - (preserve_branch + 2)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    return image, factory_call, consumer_call, observation


def guarded_recursive_call_return_object_image(
    *,
    terminal_tag=4,
    child_tag=0x29,
):
    """Return a selected terminal object through a recursive child walk."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x180)
    text = memoryview(data)

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # entry(): wrapper(tag 0x30) -> terminal(tag 4) -> child(tag 0x29).
    cursor = emit(0, "83 ec 40")
    if child_tag is not None:
        cursor = emit(cursor, f"c6 04 24 {child_tag:02x}")
    cursor = emit(cursor, f"c6 44 24 10 {terminal_tag:02x}")
    cursor = emit(cursor, "8d 04 24 89 44 24 1a")
    cursor = emit(cursor, "c6 44 24 28 30 8d 44 24 10")
    cursor = emit(cursor, "89 44 24 32 8d 44 24 28 50")
    selector_call = text_va + cursor
    cursor = emit_call(cursor, 0x80)
    emit(cursor, "59 83 c4 40 c3")

    # selector(arg0): return arg0 for tag 4, recurse through +0xa for tag
    # 0x30, and loop forever for every other tag.  A terminating return
    # therefore has the least equation result = terminal U result.
    cursor = emit(0x80, "8b 44 24 04 80 38 04 74 00")
    terminal_branch = cursor - 2
    cursor = emit(cursor, "80 38 30 75 00")
    reject_branch = cursor - 2
    cursor = emit(cursor, "8b 40 0a 50")
    recursive_call = text_va + cursor
    cursor = emit_call(cursor, 0x80)
    cursor = emit(cursor, "59 c3")
    terminal_return = cursor
    cursor = emit(cursor, "c3")
    reject_loop = cursor
    emit(cursor, "eb fe")
    text[terminal_branch + 1] = terminal_return - (terminal_branch + 2)
    text[reject_branch + 1] = reject_loop - (reject_branch + 2)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    return image, selector_call, recursive_call, text_va + terminal_return


def affine_byte_range_merge_image(*, overwrite_after_load=False):
    """Route one loaded object tag through merged affine range arms."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x80)
    text = memoryview(data)

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    cursor = emit(0, "55 8b 6c 24 08 0f b6 45 00")
    if overwrite_after_load:
        cursor = emit(cursor, "c6 45 00 77")
    cursor = emit(cursor, "83 e8 02 83 f8 01 76 00")
    first_range_branch = cursor - 2
    cursor = emit(cursor, "83 e8 1c 83 f8 0b 76 00")
    second_range_branch = cursor - 2
    default_move = cursor
    cursor = emit(cursor, "89 e8 c3")
    merged_move = cursor
    cursor = emit(cursor, "89 e8 c3")
    for branch in (first_range_branch, second_range_branch):
        text[branch + 1] = merged_move - (branch + 2)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    return image, text_va + default_move + 2, text_va + merged_move + 2


def guarded_outparam_object_origins_image(*, guard_bypasses_load=False, unknown_matching_child=False):
    """Select a nested field from one of two exact outparam object writes."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x200)
    text = memoryview(data)

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = emit(0, "83 ec 40 c6 04 24 04")
    if not unknown_matching_child:
        cursor = emit(cursor, "c6 44 24 10 29")
    cursor = emit(cursor, "8d 44 24 10 89 44 24 0a")
    cursor = emit(cursor, "c6 44 24 20 05")
    cursor = emit(cursor, "8d 4c 24 30 8d 04 24 8d 54 24 20")
    cursor = emit(cursor, "52 50 51")
    outparam_call = text_va + cursor
    cursor = emit_call(cursor, 0x80)
    cursor = emit(cursor, "83 c4 0c 84 c0 74 00")
    failure_branch = cursor - 2
    cursor = emit(cursor, "8b 44 24 30 50")
    consumer_call = text_va + cursor
    cursor = emit_call(cursor, 0xC0)
    cursor = emit(cursor, "83 c4 04 83 c4 40 c3")
    failure = cursor
    emit(cursor, "31 c0 83 c4 40 c3")
    text[failure_branch + 1] = failure - (failure_branch + 2)

    # producer(outparam, root_a, root_b): publish either exact root and
    # report success.  Distinct writes exercise the exact-origin fallback.
    cursor = emit(0x80, "8b 44 24 04 85 c9 74 09")
    cursor = emit(cursor, "8b 54 24 08 89 10 b0 01 c3")
    emit(cursor, "8b 54 24 0c 89 10 b0 01 c3")

    cursor = emit(0xC0, "8b 44 24 04 0f b6 08 83 e9 04 75 00")
    guard_branch = cursor - 2
    cursor = emit(cursor, "85 d2 74 02 90 90")
    child_load = cursor
    cursor = emit(cursor, "8b 40 0a")
    observation = text_va + cursor
    cursor = emit(cursor, "0f b6 08 c3")
    failure = cursor
    emit(cursor, "c3")
    target = child_load if guard_bypasses_load else failure
    text[guard_branch + 1] = target - (guard_branch + 2)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    return image, outparam_call, consumer_call, observation


def callee_stack_object_writer_image(*, mutation=None, callee_published_outer=False):
    """Nested stack byte initialized only through owned direct callees."""
    from tools.mwcc_retro import pe as pe_mod

    assert mutation in {
        None,
        "unowned-callee",
        "indirect-callee",
        "ambiguous-alias",
        "pointer-escape",
        "conditional-missing-write",
        "partial-overlap",
        "conflicting-path-values",
        "post-call-clobber",
        "outer-unowned-callee",
        "outer-indirect-callee",
        "outer-ambiguous-alias",
        "outer-pointer-escape",
        "outer-strict-zero-before-publish",
        "outer-strict-zero-after-publish",
        "outer-strict-zero-only",
        "outer-pointee-use",
        "outer-conditional-missing-write",
        "outer-partial-overlap",
        "outer-partial-pointee-register",
        "outer-conflicting-pointees",
        "outer-multiple-writers",
        "outer-unknown-pointee",
        "outer-clobber",
        "outer-null-pointee",
        "outer-recursive-callee",
        "outer-recursive-pointee",
    }
    text_va = 0x00401000
    rdata_va = 0x00402000
    data = bytearray(0x800)
    text = memoryview(data)[:0x300]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # entry(): node lives at [esp], root.node at [esp+8].  No instruction in
    # entry writes node.byte directly: the zero helper and both mutators do.
    cursor = emit(0, "83 ec 20")
    cursor = emit(cursor, "8d 04 24")
    cursor = emit(cursor, "6a 04 50")
    cursor = emit_call(cursor, 0x140)
    cursor = emit(cursor, "83 c4 08")
    cursor = emit(cursor, "8d 04 24 50")
    cursor = emit_call(cursor, 0x160)
    cursor = emit(cursor, "83 c4 04")
    if callee_published_outer:
        cursor = emit(cursor, "8d 44 24 08")
        if mutation == "outer-ambiguous-alias":
            cursor = emit(cursor, "50 50")
            cursor = emit_call(cursor, 0x260)
            cursor = emit(cursor, "83 c4 08")
        else:
            cursor = emit(cursor, "50")
            if mutation == "outer-indirect-callee":
                cursor = emit(cursor, "ff d2")
            elif mutation == "outer-unowned-callee":
                cursor = emit(cursor, "ff 15 80 22 40 00")
            else:
                cursor = emit_call(cursor, 0x260)
            cursor = emit(cursor, "83 c4 04")
    else:
        cursor = emit(cursor, "8d 04 24 89 44 24 08")
    cursor = emit(cursor, "8d 4c 24 08 51")
    cursor = emit_call(cursor, 0x100)
    cursor = emit(cursor, "83 c4 04")

    cursor = emit(cursor, "8d 04 24 50")
    second_mutator_call = cursor
    if mutation == "indirect-callee":
        cursor = emit(cursor, "ff d2")
    elif mutation == "unowned-callee":
        # Imported callees are typed but deliberately outside the owned
        # function domain.
        cursor = emit(cursor, "ff 15 80 22 40 00")
    else:
        cursor = emit_call(cursor, 0x180)
    cursor = emit(cursor, "83 c4 04")
    if mutation == "post-call-clobber":
        cursor = emit(cursor, "8d 04 24 50")
        cursor = emit_call(cursor, 0x1C0)
        cursor = emit(cursor, "83 c4 04")
    cursor = emit(cursor, "8d 4c 24 08 51")
    cursor = emit_call(cursor, 0x100)
    cursor = emit(cursor, "83 c4 04 83 c4 20 c3")
    assert cursor < 0x100

    # consumer(root): root.node->byte selects a relocated 75-entry table.
    cursor = emit(0x100, "8b 44 24 04 8b 00")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 18")
    transfer_offset = cursor
    cursor = emit(cursor, "ff 14 9d 00 20 40 00 c3")

    # zero_bytes(destination, size), in the exact strict helper shape already
    # recognized by the CFG implementation.
    emit(
        0x140,
        "31 c0 57 8b 4c 24 0c 8b 7c 24 08 f3 aa 5f c3",
    )

    # mutator_zero(node): an unrelated +4 write must not poison node.byte.
    emit(0x160, "8b 4c 24 04 89 51 04 c6 01 00 c3")

    # mutator_74(node) delegates to a second owned helper.  Mutations below
    # exercise fail-closed alias/path behavior in this wrapper or its leaf.
    if mutation == "ambiguous-alias":
        cursor = emit(0x180, "8b 4c 24 04 85 d2 74 03 83 c1 01")
        cursor = emit(cursor, "51")
        cursor = emit_call(cursor, 0x200)
        emit(cursor, "59 c3")
    elif mutation == "pointer-escape":
        cursor = emit(0x180, "8b 4c 24 04 89 0d 20 22 40 00 51")
        cursor = emit_call(cursor, 0x200)
        emit(cursor, "59 c3")
    else:
        cursor = emit(0x180, "8b 4c 24 04 51")
        cursor = emit_call(cursor, 0x200)
        emit(cursor, "59 c3")

    # Unknown post-call byte clobber.
    emit(0x1C0, "8b 4c 24 04 88 11 c3")

    if mutation == "conditional-missing-write":
        emit(0x200, "83 7c 24 08 00 74 07 8b 4c 24 04 c6 01 4a c3")
    elif mutation == "partial-overlap":
        emit(0x200, "8b 4c 24 04 66 89 11 c3")
    elif mutation == "conflicting-path-values":
        emit(
            0x200,
            "8b 4c 24 04 85 d2 74 04 c6 01 00 c3 c6 01 4a c3",
        )
    else:
        emit(0x200, "8b 4c 24 04 c6 01 4a c3")
    emit(0x240, "c3")

    # publish_outer(root): establish root.node solely through an owned direct
    # callee.  The exact node lives eight bytes before root in the caller's
    # stack frame.  Hostile variants exercise fail-closed association proofs.
    if mutation == "outer-strict-zero-before-publish":
        cursor = emit(0x260, "8b 4c 24 04 6a 04 51")
        cursor = emit_call(cursor, 0x140)
        emit(cursor, "83 c4 08 8b 4c 24 04 8d 41 f8 89 01 c3")
    elif mutation == "outer-strict-zero-after-publish":
        cursor = emit(0x260, "8b 4c 24 04 8d 41 f8 89 01 6a 04 51")
        cursor = emit_call(cursor, 0x140)
        emit(cursor, "83 c4 08 c3")
    elif mutation == "outer-strict-zero-only":
        cursor = emit(0x260, "8b 4c 24 04 6a 04 51")
        cursor = emit_call(cursor, 0x140)
        emit(cursor, "83 c4 08 c3")
    elif mutation == "outer-pointer-escape":
        emit(0x260, "8b 4c 24 04 89 0d 20 22 40 00 8d 41 f8 89 01 c3")
    elif mutation == "outer-pointee-use":
        emit(0x260, "8b 4c 24 04 8d 41 f8 89 01 8b 01 c6 00 4a c3")
    elif mutation == "outer-conditional-missing-write":
        emit(0x260, "8b 4c 24 04 85 d2 74 05 8d 41 f8 89 01 c3")
    elif mutation == "outer-partial-overlap":
        emit(0x260, "8b 4c 24 04 66 89 01 c3")
    elif mutation == "outer-partial-pointee-register":
        emit(0x260, "8b 4c 24 04 8d 41 f8 88 d0 89 01 c3")
    elif mutation == "outer-conflicting-pointees":
        emit(
            0x260,
            "8b 4c 24 04 85 d2 74 06 8d 41 f8 89 01 c3 8d 41 f0 89 01 c3",
        )
    elif mutation == "outer-multiple-writers":
        emit(0x260, "8b 4c 24 04 8d 41 f8 89 01 89 01 c3")
    elif mutation == "outer-unknown-pointee":
        emit(0x260, "8b 4c 24 04 c7 01 00 21 40 00 c3")
    elif mutation == "outer-clobber":
        emit(0x260, "8b 4c 24 04 8d 41 f8 89 01 89 11 c3")
    elif mutation == "outer-null-pointee":
        emit(0x260, "8b 4c 24 04 c7 01 00 00 00 00 c3")
    elif mutation == "outer-recursive-callee":
        cursor = emit(0x260, "8b 4c 24 04 83 e9 08 51")
        cursor = emit_call(cursor, 0x260)
        emit(cursor, "59 c3")
    elif mutation == "outer-recursive-pointee":
        emit(0x260, "8b 4c 24 04 89 09 c3")
    else:
        cursor = emit(0x260, "8b 4c 24 04 51")
        cursor = emit_call(cursor, 0x2A0)
        emit(cursor, "59 c3")
        emit(0x2A0, "8b 4c 24 04 8d 41 f8 89 01 c3")

    for index in range(75):
        struct.pack_into("<I", data, 0x300 + index * 4, text_va + 0x240)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x300, 0x300, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x300, 0x500, 0x500, 0x40000040),
        ),
        imports=(
            (
                pe_mod.Import(
                    dll="KERNEL32.dll",
                    name="CloseHandle",
                    ordinal=None,
                    hint=28,
                    iat_va=0x00402280,
                ),
            )
            if mutation in {"unowned-callee", "outer-unowned-callee"}
            else ()
        ),
        exports=(),
        relocations=tuple(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
        executable_ranges=((text_va, text_va + 0x300),),
    )
    return (
        image,
        text_va + movzx_offset,
        text_va + transfer_offset,
        text_va + second_mutator_call,
    )


def allocation_backed_stack_pointee_image(*, mutation=None):
    """Retail-shaped stack outer whose head is one fresh heap list node."""
    from tools.mwcc_retro import pe as pe_mod

    assert mutation in {
        None,
        "unowned-allocator",
        "allocator-result-escape",
        "outer-pointer-escape",
        "variable-size",
        "zero-size",
        "unchecked-null",
        "conditional-missing-publish",
        "second-allocation",
        "partial-outer-store",
        "alternate-outer-store",
        "node-escape-before-init",
        "unknown-node-overlap",
        "interior-clobber",
        "generation-reuse",
        "wrapper-strict-zero-before-allocation",
        "wrapper-strict-zero-after-publication",
    }
    text_va = 0x00401000
    rdata_va = 0x00402000
    data_va = 0x00403000
    data = bytearray(0xA00)
    text = memoryview(data)[:0x600]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    # Root closes the consumer's producer domain over tag values 0 and 74.
    cursor = emit_call(0, 0x40)
    cursor = emit_call(cursor, 0xC0)
    emit(cursor, "c3")

    def emit_producer(offset, tag):
        cursor = emit(offset, "83 ec 30")
        cursor = emit(cursor, "8d 44 24 08 6a 1a 50")
        cursor = emit_call(cursor, 0x480)
        cursor = emit(cursor, "83 c4 08")
        cursor = emit(cursor, "8d 44 24 08")
        cursor = emit(cursor, f"6a {tag:02x} 50")
        cursor = emit_call(cursor, 0x1C0)
        cursor = emit(cursor, "83 c4 08")
        # One base consumer and one +4 interior consumer are read-only and
        # must preserve the selected outer[0] association.
        cursor = emit(cursor, "8d 44 24 08 50")
        cursor = emit_call(cursor, 0x4A0)
        cursor = emit(cursor, "83 c4 04")
        cursor = emit(cursor, "8d 44 24 0c 50")
        cursor = emit_call(cursor, 0x4B0)
        cursor = emit(cursor, "83 c4 04")
        cursor = emit(cursor, "8d 44 24 08 50")
        cursor = emit_call(cursor, 0x140)
        return emit(cursor, "83 c4 04 83 c4 30 c3")

    assert emit_producer(0x40, 0) < 0xC0
    assert emit_producer(0xC0, 74) < 0x140

    # consumer(outer): outer->head->tag dispatches through 75 entries.
    cursor = emit(0x140, "8b 44 24 04 8b 00")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 58 04")
    transfer_offset = cursor
    emit(cursor, "ff 14 9d 00 20 40 00 c3")

    # wrapper(outer, tag): keep one transitive layer above the list push.
    cursor = emit(0x1C0, "8b 4c 24 04")
    if mutation == "wrapper-strict-zero-before-allocation":
        cursor = emit(cursor, "6a 04 51")
        cursor = emit_call(cursor, 0x480)
        cursor = emit(cursor, "83 c4 08 8b 4c 24 04")
    if mutation == "outer-pointer-escape":
        cursor = emit(cursor, "89 0d 10 30 40 00")
    cursor = emit(cursor, "8b 54 24 08 52 51")
    cursor = emit_call(cursor, 0x200)
    cursor = emit(cursor, "83 c4 08")
    if mutation == "wrapper-strict-zero-after-publication":
        cursor = emit(cursor, "8b 4c 24 04 6a 04 51")
        cursor = emit_call(cursor, 0x480)
        cursor = emit(cursor, "83 c4 08")
    emit(cursor, "c3")

    # list_push(outer, tag): allocate one 0x1a-byte generation, link the old
    # outer[0], publish the new head, then initialize its finite tag byte.
    size_push = "52" if mutation == "variable-size" else "6a 00" if mutation == "zero-size" else "6a 1a"
    cursor = emit(0x200, f"53 8b 5c 24 08 {size_push}")
    cursor = emit_call(
        cursor,
        0x500 if mutation == "unowned-allocator" else 0x400,
    )
    cursor = emit(cursor, "59")
    if mutation == "second-allocation":
        cursor = emit(cursor, "6a 1a")
        cursor = emit_call(cursor, 0x400)
        cursor = emit(cursor, "59")
    guard = None
    if mutation != "unchecked-null":
        guard = cursor
        cursor = emit(cursor, "85 c0 74 00")
    cursor = emit(cursor, "8b 0b 89 08")
    if mutation == "conditional-missing-publish":
        cursor = emit(cursor, "85 c9 74 02 89 03")
    elif mutation == "partial-outer-store":
        cursor = emit(cursor, "66 89 03")
    else:
        cursor = emit(cursor, "89 03")
    if mutation == "alternate-outer-store":
        cursor = emit(cursor, "89 13")
    if mutation == "node-escape-before-init":
        cursor = emit(cursor, "a3 0c 30 40 00")
    cursor = emit(cursor, "8a 54 24 0c 88 50 04 c6 40 06 00")
    if mutation == "unknown-node-overlap":
        cursor = emit(cursor, "88 48 04")
    cursor = emit(cursor, "5b c3")
    failure = cursor
    emit(cursor, "eb fe")
    if guard is not None:
        delta = failure - (guard + 4)
        assert 0 <= delta <= 0x7F
        text[guard + 3] = delta

    # Exact owned bump allocator shape used by retail 0x441fa0: round the
    # fixed positive size, grow the arena if needed, return the old cursor,
    # and advance it by the same amount.  The caller's closed guard handles
    # null while the monotonic cursor prevents generation reuse.
    cursor = emit(0x400, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 00 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 08 30 40 00")
    cursor = emit_call(cursor, 0x460)
    cursor = emit(cursor, "59 59 29 1d 00 30 40 00")
    cursor = emit(cursor, "a1 04 30 40 00")
    if mutation == "allocator-result-escape":
        cursor = emit(cursor, "a3 0c 30 40 00")
    cursor = emit(cursor, "01 1d 04 30 40 00")
    if mutation == "generation-reuse":
        cursor = emit(cursor, "29 1d 04 30 40 00")
    cursor = emit(cursor, "5b c3")
    assert cursor < 0x460

    emit(0x460, "c3")
    # Strict zero helper (destination, size).
    emit(0x480, "31 c0 57 8b 4c 24 0c 8b 7c 24 08 f3 aa 5f c3")
    # Read-only base and +4 interior consumers.
    emit(
        0x4B0,
        "8b 44 24 04 89 50 fc c3" if mutation == "interior-clobber" else "8b 44 24 04 83 38 00 c3",
    )
    emit(0x4A0, "8b 44 24 04 83 78 08 00 c3")
    emit(0x4C0, "c3")
    if mutation == "unowned-allocator":
        emit(0x500, "c3")

    for index in range(75):
        struct.pack_into("<I", data, 0x600 + index * 4, text_va + 0x4C0)
    struct.pack_into("<I", data, 0x900, 0x1000)
    struct.pack_into("<I", data, 0x904, data_va + 0x100)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x600, 0x600, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x600, 0x300, 0x300, 0x40000040),
            pe_mod.Section(".data", data_va, 0x900, 0x100, 0x100, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
        executable_ranges=((text_va, text_va + 0x600),),
    )
    return image, text_va + movzx_offset, text_va + transfer_offset


def late_initialized_stack_slot_allocation_image(*, clobber_slot=False, bulk_copy=False, nested_bulk_copy=False):
    """Publish a fresh pointer locally before initializing its tag byte."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    rdata_va = 0x00402000
    data_va = 0x00403000
    data = bytearray(0x800)
    data[:0x300] = b"\xc3" * 0x300
    text = memoryview(data)[:0x300]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = emit(
        0,
        "83 ec 60" if nested_bulk_copy else "83 ec 40" if bulk_copy else "83 ec 10",
    )
    if nested_bulk_copy:
        cursor = emit(cursor, "c6 44 24 20 04 c6 44 24 40 29")
        cursor = emit(cursor, "8d 44 24 40 89 44 24 2a")
    elif bulk_copy:
        cursor = emit(cursor, "c6 44 24 20 29")
    cursor = emit(cursor, "6a 1a")
    cursor = emit_call(cursor, 0x100)
    cursor = emit(cursor, "59 85 c0 74 00")
    null_branch = cursor - 2
    cursor = emit(cursor, "89 04 24")
    if nested_bulk_copy:
        cursor = emit(cursor, "8b 3c 24 8d 74 24 20 a5 a5 a5 a5")
    elif bulk_copy:
        cursor = emit(cursor, "8b 3c 24 8d 74 24 20 a5")
    else:
        cursor = emit(cursor, "c6 00 29")
    if clobber_slot:
        cursor = emit(cursor, "85 d2 74 03 89 0c 24")
    cursor = emit(cursor, "8b 04 24")
    if nested_bulk_copy:
        cursor = emit(cursor, "8b 40 0a")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 08")
    transfer_offset = cursor
    emit(cursor, "ff 14 8d 00 20 40 00")
    failure = 0x70
    emit(failure, "eb fe")
    text[null_branch + 1] = failure - (null_branch + 2)
    emit(0x80, "c3")

    # Exact owned bump allocator shape used by the allocation proofs.
    cursor = emit(0x100, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 00 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 08 30 40 00")
    cursor = emit_call(cursor, 0x160)
    cursor = emit(cursor, "59 59 29 1d 00 30 40 00")
    cursor = emit(cursor, "a1 04 30 40 00 01 1d 04 30 40 00 5b c3")
    assert cursor < 0x160
    emit(0x160, "c3")

    for index in range(75):
        struct.pack_into("<I", data, 0x300 + index * 4, text_va + 0x80)
    struct.pack_into("<I", data, 0x700, 0x1000)
    struct.pack_into("<I", data, 0x704, data_va + 0x100)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x300, 0x300, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x300, 0x400, 0x400, 0x40000040),
            pe_mod.Section(".data", data_va, 0x700, 0x100, 0x100, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
        executable_ranges=((text_va, text_va + 0x300),),
    )
    return image, text_va + movzx_offset, text_va + transfer_offset


def lifecycle_optional_allocation_pointee_image(*, mutation=None):
    """Checked arena session with optional finite list pushes and empty tail."""
    from tools.mwcc_retro import pe as pe_mod

    retail_grow_mutations = {
        "retail-multi-attempt",
        "retail-missing-recovery",
        "retail-ambiguous-retry",
        "retail-success-bypass-finalizer",
        "retail-conditional-finalizer",
        "retail-missing-finalizer",
        "retail-extra-call-escape",
        "retail-result-escape",
        "retail-returning-callback",
    }
    assert mutation in {
        None,
        "unchecked-init",
        "one-arena-null-path",
        "returning-callback",
        "callback-overwritten",
        "reset-reachable",
        "alternate-backend-entry",
        "allocation-before-init",
        "unknown-initial-head",
        "deref-before-null",
        "partial-outer-store",
        "outer-pointer-escape",
        "link-mutation",
        "tag-mutation",
        "terminal-nonzero-success",
        "naked-context-save",
        "cleanup-between-test-and-branch",
        *retail_grow_mutations,
    }
    retail_grow = mutation in retail_grow_mutations
    init_offset = 0x4C0 if retail_grow else 0x4A0
    text_va = 0x00401000
    rdata_va = 0x00402000
    data_va = 0x00403000
    data = bytearray(0xC00)
    text = memoryview(data)[:0x700]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    def patch_short_branch(branch_offset, target_offset):
        displacement = target_offset - (branch_offset + 2)
        assert -0x80 <= displacement <= 0x7F
        text[branch_offset + 1] = displacement & 0xFF

    # session(callback): checked init and setjmp establish the only backend
    # entry.  Its failure path may reset arenas but cannot reach the backend.
    cursor = 0
    if mutation == "allocation-before-init":
        cursor = emit_call(cursor, 0x400)
    alternate_branch = None
    if mutation == "alternate-backend-entry":
        cursor = emit(cursor, "83 3d b0 30 40 00 00 75 00")
        alternate_branch = cursor - 2
    callback_push = cursor
    cursor = emit(cursor, "68 60 15 40 00")
    cursor = emit_call(cursor, init_offset)
    cursor = emit(
        cursor,
        "85 c0 59" if mutation == "cleanup-between-test-and-branch" else "59 85 c0",
    )
    init_failure_branch = None
    if mutation != "unchecked-init":
        init_failure_branch = cursor
        cursor = emit(cursor, "75 00")
    cursor = emit(cursor, "68 a0 30 40 00")
    cursor = emit_call(cursor, 0x520)
    cursor = emit(
        cursor,
        "85 c0 59" if mutation == "cleanup-between-test-and-branch" else "59 85 c0",
    )
    setjmp_failure_branch = cursor
    cursor = emit(cursor, "75 00")
    cursor = emit_call(cursor, 0x400)
    cursor = emit(cursor, "c3")
    failure_offset = cursor
    cursor = emit_call(cursor, 0x580)
    cursor = emit(cursor, "c3")
    alternate_offset = cursor
    if alternate_branch is not None:
        cursor = emit_call(cursor, 0x400)
        cursor = emit(cursor, "c3")
        patch_short_branch(alternate_branch, alternate_offset)
    if init_failure_branch is not None:
        patch_short_branch(init_failure_branch, failure_offset)
    patch_short_branch(setjmp_failure_branch, failure_offset)
    assert cursor < 0x80

    def emit_producer(offset, tag):
        cursor = emit(offset, "83 ec 30")
        cursor = emit(cursor, "8d 44 24 08 6a 1a 50")
        cursor = emit_call(cursor, 0x5C0)
        cursor = emit(cursor, "83 c4 08")
        if mutation == "unknown-initial-head":
            cursor = emit(cursor, "c7 44 24 08 34 12 00 00")
        cursor = emit(cursor, "c6 44 24 0c 01")
        cursor = emit(cursor, "8d 44 24 08")
        cursor = emit(cursor, f"6a {tag:02x} 50")
        cursor = emit_call(cursor, 0x240)
        cursor = emit(cursor, "83 c4 08")
        cursor = emit(cursor, "8d 44 24 08 50")
        cursor = emit_call(cursor, 0x200)
        return emit(cursor, "83 c4 04 83 c4 30 c3")

    assert emit_producer(0x80, 0) < 0x140
    assert emit_producer(0x140, 74) < 0x200

    # consumer(node): observe the base sentinel tag, then traverse optional
    # allocation-backed nodes.  A null next pointer contributes no byte.
    cursor = emit(0x200, "53 56 8b 74 24 0c")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 5e 04")
    transfer_offset = cursor
    cursor = emit(cursor, "ff 14 9d 00 20 40 00")
    cursor = emit(cursor, "8b 36")
    if mutation == "deref-before-null":
        cursor = emit(cursor, "0f b6 46 04")
    cursor = emit(cursor, "85 f6")
    branch_offset = cursor
    cursor = emit(cursor, "75 00 5e 5b c3")
    patch_short_branch(branch_offset, movzx_offset)

    # wrapper(outer, tag): either preserve the strict-zero empty association,
    # or publish one and then optionally four more finite-tag nodes.
    cursor = emit(0x240, "a1 b0 30 40 00 85 c0")
    no_push_branch = cursor
    cursor = emit(cursor, "74 00")
    if mutation == "outer-pointer-escape":
        cursor = emit(cursor, "8b 4c 24 04 89 0d c4 30 40 00")
    cursor = emit(cursor, "8b 4c 24 04 8b 54 24 08 52 51")
    cursor = emit_call(cursor, 0x300)
    cursor = emit(cursor, "83 c4 08 a1 b4 30 40 00 85 c0")
    one_push_branch = cursor
    cursor = emit(cursor, "74 00")
    for tag in (2, 3, 4, 8):
        cursor = emit(cursor, "8b 4c 24 04")
        cursor = emit(cursor, f"6a {tag:02x} 51")
        cursor = emit_call(cursor, 0x300)
        cursor = emit(cursor, "83 c4 08")
    wrapper_return = cursor
    emit(cursor, "c3")
    patch_short_branch(no_push_branch, wrapper_return)
    patch_short_branch(one_push_branch, wrapper_return)
    assert wrapper_return < 0x300

    # list_push(outer, tag): no local null guard.  Its allocation is total
    # only under the checked session/OOM nonreturn certificate above.
    cursor = emit(0x300, "53 8b 5c 24 08 6a 1a")
    cursor = emit_call(cursor, 0x380)
    cursor = emit(cursor, "59 8b 0b 89 08")
    if mutation == "link-mutation":
        cursor = emit(cursor, "c7 00 34 12 00 00")
    cursor = emit(
        cursor,
        "66 89 03" if mutation == "partial-outer-store" else "89 03",
    )
    cursor = emit(cursor, "8a 54 24 0c 88 50 04")
    if mutation == "tag-mutation":
        cursor = emit(cursor, "c6 40 04 07")
    cursor = emit(cursor, "c6 40 06 00 5b c3")
    assert cursor < 0x380

    # Fixed owned bump allocator for descriptor A.
    cursor = emit(0x380, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 10 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 00 30 40 00")
    cursor = emit_call(cursor, 0x440)
    cursor = emit(cursor, "59 59 29 1d 10 30 40 00")
    cursor = emit(cursor, "a1 0c 30 40 00 01 1d 0c 30 40 00 5b c3")
    assert cursor < 0x400

    # The backend call closure contains all allocation and observations.
    cursor = 0x400
    if mutation == "reset-reachable":
        cursor = emit_call(cursor, 0x580)
    if mutation == "callback-overwritten":
        cursor = emit_call(cursor, 0x620)
    cursor = emit_call(cursor, 0x80)
    cursor = emit_call(cursor, 0x140)
    emit(cursor, "c3")

    # grow(desc, size): system allocation failure invokes the installed OOM
    # callback; success initializes the descriptor's current arena extent.
    if not retail_grow:
        cursor = emit(0x440, "53 8b 5c 24 08")
        cursor = emit_call(cursor, 0x5A0)
        cursor = emit(cursor, "85 c0")
        success_branch = cursor
        cursor = emit(cursor, "75 00 83 3d 80 30 40 00 00")
        no_callback_branch = cursor
        cursor = emit(cursor, "74 00 ff 15 80 30 40 00")
        no_callback_offset = cursor
        cursor = emit(cursor, "5b c3")
        success_offset = cursor
        cursor = emit(
            cursor,
            "89 43 08 83 c0 10 89 43 0c c7 43 10 00 10 00 00 5b c3",
        )
        patch_short_branch(success_branch, success_offset)
        patch_short_branch(no_callback_branch, no_callback_offset)
        assert cursor < init_offset
    else:
        # Retail-style grow: an enabled primary allocator gets one retry,
        # then a distinct fallback. Every non-null result converges through
        # one finalizer before the descriptor state is published.
        cursor = emit(0x440, "53 56 57 8b 74 24 10 8b 5c 24 14")
        if mutation == "retail-missing-recovery":
            cursor = emit(cursor, "53")
            cursor = emit_call(cursor, 0x5A0)
            cursor = emit(cursor, "89 c7 59 85 ff")
            returning_failure_branch = cursor
            cursor = emit(cursor, "74 00")
            success_branches = []
            fallback_branch = None
            final_failure_branch = None
        else:
            cursor = emit(cursor, "83 3d b8 30 40 00 00")
            fallback_branch = cursor
            cursor = emit(cursor, "74 00 53")
            cursor = emit_call(cursor, 0x5A0)
            cursor = emit(cursor, "89 c7 59 85 ff")
            success_branches = [cursor]
            cursor = emit(cursor, "75 00 53")
            cursor = emit_call(
                cursor,
                0x680 if mutation == "retail-ambiguous-retry" else 0x5A0,
            )
            cursor = emit(cursor, "89 c7 59 85 ff")
            success_branches.append(cursor)
            cursor = emit(cursor, "75 00")
            fallback_offset = cursor
            cursor = emit(cursor, "53")
            cursor = emit_call(cursor, 0x640)
            cursor = emit(cursor, "89 c7 59 85 ff")
            final_failure_branch = cursor
            cursor = emit(cursor, "74 00")

        success_offset = cursor
        conditional_finalizer_branch = None
        if mutation == "retail-conditional-finalizer":
            cursor = emit(cursor, "83 3d bc 30 40 00 00")
            conditional_finalizer_branch = cursor
            cursor = emit(cursor, "74 00")
        if mutation == "retail-extra-call-escape":
            cursor = emit(cursor, "57")
            cursor = emit_call(cursor, 0x680)
            cursor = emit(cursor, "59")
        if mutation == "retail-result-escape":
            cursor = emit(cursor, "89 3d d0 30 40 00")
        if mutation != "retail-missing-finalizer":
            cursor = emit(cursor, "57")
            cursor = emit_call(cursor, 0x660)
            cursor = emit(cursor, "59")
        descriptor_offset = cursor
        cursor = emit(cursor, "89 7e 08 89 7e 0c 89 5e 10")
        epilogue_offset = cursor
        cursor = emit(cursor, "5f 5e 5b c3")

        failure_offset = cursor
        if mutation != "retail-missing-recovery":
            cursor = emit(cursor, "83 3d 80 30 40 00 00")
            no_callback_branch = cursor
            cursor = emit(cursor, "74 00 ff 15 80 30 40 00")
            cursor = emit(cursor, "eb 00")
            patch_short_branch(no_callback_branch, epilogue_offset)
            patch_short_branch(cursor - 2, epilogue_offset)
        else:
            patch_short_branch(returning_failure_branch, epilogue_offset)

        if fallback_branch is not None:
            patch_short_branch(fallback_branch, fallback_offset)
            for branch in success_branches:
                patch_short_branch(
                    branch,
                    descriptor_offset
                    if mutation == "retail-success-bypass-finalizer" and branch == success_branches[0]
                    else success_offset,
                )
            patch_short_branch(final_failure_branch, failure_offset)
        if conditional_finalizer_branch is not None:
            patch_short_branch(conditional_finalizer_branch, descriptor_offset)
        assert cursor < init_offset

    # init(callback): callback disabled during both initial grows; callback
    # installed only after every descriptor is initialized and checked.
    cursor = emit(init_offset, "c7 05 80 30 40 00 00 00 00 00")
    for descriptor in (0x00403000, 0x00403020):
        cursor = emit(cursor, "6a 00")
        cursor = emit(cursor, f"68 {descriptor & 0xFF:02x} 30 40 00")
        cursor = emit_call(cursor, 0x440)
        cursor = emit(cursor, "83 c4 08")
    cursor = emit(cursor, "8b 44 24 04 a3 80 30 40 00")
    check_a = cursor
    cursor = emit(cursor, "83 3d 08 30 40 00 00 74 00")
    check_a_branch = cursor - 2
    check_b_branch = None
    terminal_success_branch = None
    if mutation != "one-arena-null-path":
        cursor = emit(cursor, "83 3d 28 30 40 00 00")
        if mutation == "terminal-nonzero-success":
            terminal_success_branch = cursor
            cursor = emit(cursor, "75 00")
        else:
            check_b_branch = cursor
            cursor = emit(cursor, "74 00")
    if terminal_success_branch is None:
        cursor = emit(cursor, "31 c0 c3")
        init_failure = cursor
        emit(cursor, "b8 ff ff ff ff c3")
    else:
        init_failure = cursor
        cursor = emit(cursor, "b8 ff ff ff ff c3")
        init_success = cursor
        emit(cursor, "31 c0 90 c3")
        patch_short_branch(terminal_success_branch, init_success)
    patch_short_branch(check_a_branch, init_failure)
    if check_b_branch is not None:
        patch_short_branch(check_b_branch, init_failure)
    assert check_a < init_failure < 0x520

    # setjmp-like save and longjmp-like restore of the same context.
    if mutation == "naked-context-save":
        emit(
            0x520,
            "59 58 89 18 89 70 04 89 78 08 89 60 0c 89 68 10 89 48 14 31 c0 50 51 c3",
        )
        emit(
            0x540,
            "59 5a 58 8b 1a 8b 72 04 8b 7a 08 8b 62 0c 8b 6a 10 09 c0 0f 85 01 00 00 00 40 50 ff 72 14 c3",
        )
    else:
        emit(0x520, "8b 4c 24 04 89 21 8b 04 24 89 41 04 31 c0 c3")
        emit(0x540, "8b 4c 24 04 8b 21 b8 01 00 00 00 c3")
    if mutation in {"returning-callback", "retail-returning-callback"}:
        emit(0x560, "c3")
    else:
        cursor = emit(0x560, "68 a0 30 40 00")
        cursor = emit_call(cursor, 0x540)
        emit(cursor, "59 c3")
    # reset(desc A) and a deterministic system allocator stub.
    emit(0x580, "c7 05 0c 30 40 00 00 00 00 00 c7 05 10 30 40 00 00 00 00 00 c3")
    emit(0x5A0, "a1 c0 30 40 00 83 05 c0 30 40 00 40 c3")
    emit(0x5C0, "31 c0 57 8b 4c 24 0c 8b 7c 24 08 f3 aa 5f c3")
    emit(0x600, "c3")
    if mutation == "callback-overwritten":
        emit(0x620, "c7 05 80 30 40 00 00 00 00 00 c3")
    emit(0x640, "a1 c8 30 40 00 83 05 c8 30 40 00 40 c3")
    emit(0x660, "8b 44 24 04 c7 00 34 12 00 00 c3")
    emit(0x680, "8b 44 24 04 a3 d0 30 40 00 c3")

    for index in range(75):
        struct.pack_into("<I", data, 0x700 + index * 4, text_va + 0x600)
    struct.pack_into("<I", data, 0xAC0, data_va + 0x100)
    # Both runtime choices are intentionally unknown to the static proof.
    struct.pack_into("<I", data, 0xAB0, 1)
    struct.pack_into("<I", data, 0xAB4, 1)
    struct.pack_into("<I", data, 0xAB8, 1)
    struct.pack_into("<I", data, 0xABC, 1)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x700, 0x700, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x700, 0x300, 0x300, 0x40000040),
            pe_mod.Section(".data", data_va, 0xA00, 0x200, 0x200, 0xC0000040),
        ),
        imports=(),
        exports=tuple(
            [
                pe_mod.Export("oom_callback", 1, text_va + 0x560, None),
                pe_mod.Export("arena_reset", 2, text_va + 0x580, None),
                *(
                    [pe_mod.Export("callback_writer", 3, text_va + 0x620, None)]
                    if mutation == "callback-overwritten"
                    else []
                ),
            ]
        ),
        relocations=tuple(
            [
                pe_mod.Relocation(text_va + callback_push + 1, 3),
                *(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
            ]
        ),
        executable_ranges=((text_va, text_va + 0x700),),
    )
    return image, text_va + movzx_offset, text_va + transfer_offset


def indexed_global_callback_image(*, unknown_registrar_caller=False):
    """Synthetic indexed callback registry with one reachable slot."""
    text_va = 0x00401000
    rdata_va = 0x00402000
    data = bytearray(0x300)
    text = memoryview(data)[:0x200]

    def emit_call(offset, target):
        next_address = text_va + offset + 5
        text[offset] = 0xE8
        text[offset + 1 : offset + 5] = (target - next_address).to_bytes(4, "little", signed=True)

    # The entrypoint registers callback 0x401090 in slot 1, then invokes
    # the consumer for slot 1.  The optional second registrar call forwards
    # the entrypoint's unknown first argument and must poison the proof.
    cursor = 0
    text[cursor : cursor + 5] = bytes.fromhex("68 90 10 40 00")
    cursor += 5
    text[cursor : cursor + 2] = bytes.fromhex("6a 01")
    cursor += 2
    emit_call(cursor, text_va + 0x30)
    cursor += 5
    text[cursor : cursor + 3] = bytes.fromhex("83 c4 08")
    cursor += 3
    if unknown_registrar_caller:
        text[cursor : cursor + 4] = bytes.fromhex("ff 74 24 04")
        cursor += 4
        text[cursor : cursor + 2] = bytes.fromhex("6a 01")
        cursor += 2
        emit_call(cursor, text_va + 0x30)
        cursor += 5
        text[cursor : cursor + 3] = bytes.fromhex("83 c4 08")
        cursor += 3
    text[cursor : cursor + 2] = bytes.fromhex("6a 01")
    cursor += 2
    emit_call(cursor, text_va + 0x60)
    cursor += 5
    text[cursor : cursor + 3] = bytes.fromhex("83 c4 04")
    cursor += 3
    text[cursor] = 0xC3

    # registrar(index, callback): slots[index] = callback
    text[0x30:0x40] = bytes.fromhex("8b 4c 24 04 8b 44 24 08 89 04 8d 00 20 40 00 c3")
    # consumer(index): callback = slots[index]; if (callback) callback()
    text[0x60:0x72] = bytes.fromhex("8b 4c 24 04 8b 04 8d 00 20 40 00 85 c0 74 02 ff d0 c3")
    text[0x90] = 0xC3

    relocations = (
        pe.Relocation(text_va + 1, 3),
        pe.Relocation(text_va + 0x3B, 3),
        pe.Relocation(text_va + 0x67, 3),
    )
    return pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe.Section(".rdata", rdata_va, 0x200, 0x100, 0x100, 0x40000040),
        ),
        imports=(),
        exports=(),
        relocations=relocations,
        executable_ranges=((text_va, text_va + 0x200),),
    )


def test_finite_indexed_global_callback_registry_is_recovered():
    image = indexed_global_callback_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040106F and row.flow_kind == "indirect-call-indexed-global-slot"
    )
    assert edge.target == 0x00401090
    assert "base=0x402000" in edge.provenance
    assert "indices=0x1" in edge.provenance
    assert not any(row.address == 0x0040106F for row in cfg.control_targets.unresolved)


def test_indexed_global_callback_registry_rejects_unknown_writer():
    image = indexed_global_callback_image(unknown_registrar_caller=True)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert any(row.address == 0x0040106F and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)
    assert not any(
        row.source == 0x0040106F and row.flow_kind == "indirect-call-indexed-global-slot"
        for row in cfg.control_targets.finite_internal_edges
    )


def zero_origin_callback_list_image(*, unknown_writer=False):
    """Synthetic zero-initialized, self-draining callback list."""
    text_va = 0x00401000
    bss_va = 0x00402000
    data = bytearray(0x300)
    text = memoryview(data)[:0x200]
    text[0x00:0x26] = bytes.fromhex(
        "8b 0d 00 20 40 00 "
        "85 c9 "
        "89 d2 "
        "74 19 "
        "8b 01 "
        "a3 00 20 40 00 "
        "89 c8 "
        "8b 48 08 "
        "ff 50 04 "
        "8b 0d 00 20 40 00 "
        "85 c9 "
        "75 e7 "
        "c3"
    )
    relocations = [
        pe.Relocation(text_va + 0x02, 3),
        pe.Relocation(text_va + 0x0F, 3),
        pe.Relocation(text_va + 0x1D, 3),
    ]
    if unknown_writer:
        text[0x40:0x4A] = bytes.fromhex("8b 44 24 04 a3 00 20 40 00 c3")
        relocations.append(pe.Relocation(text_va + 0x45, 3))
    return pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe.Section(".bss", bss_va, 0x200, 0, 0x100, 0xC0000080),
        ),
        imports=(),
        exports=(),
        relocations=tuple(relocations),
        executable_ranges=((text_va, text_va + 0x200),),
    )


def test_zero_origin_guarded_callback_list_is_unreachable():
    image = zero_origin_callback_list_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert not any(row.address == 0x00401018 for row in cfg.control_targets.unresolved)
    assert any(
        row.address == 0x00401018
        and row.kind == "proven-unreachable-control"
        and "zero-origin-guarded-global" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_origin_callback_list_rejects_unguarded_unknown_writer():
    image = zero_origin_callback_list_image(unknown_writer=True)
    cfg = recover_cfg(
        image,
        (image.entrypoint, 0x00401040),
        generous_limits(image),
    )

    assert any(row.address == 0x00401018 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_movzx_guard_resolves_indexed_call_table():
    image = movzx_dispatch_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    # Debug: check what happened
    diagnostics_at_call = [d for d in cfg.ownership_diagnostics if d.address == 0x00401003]
    assert not diagnostics_at_call, "unexpected diagnostics at 0x401003: " + "; ".join(
        f"{d.kind}:{d.detail}" for d in diagnostics_at_call
    )
    table = cfg.jump_table_at(0x00401003)
    assert table.guard_operator == "movzx"
    assert table.guard_bound == 0xFF
    assert (table.index_min, table.index_max) == (0, 0xFF)
    assert set(table.targets) == {0x00401020}
    assert not [
        row
        for row in cfg.ownership_diagnostics
        if row.address == 0x00401003 and row.kind in {"computed-flow-blocker", "indirect-flow"}
    ]


def test_movzx_bound_table_with_in_domain_data_entry_remains_blocking():
    image = movzx_dispatch_image(unrelocated_indices={17})
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401003)
    assert any(
        row.address == 0x00401003 and row.kind == "computed-flow-blocker" and "type-3 relocation" in row.detail
        for row in cfg.control_targets.unresolved
    )


def test_movzx_bound_table_with_relocated_noncode_entry_remains_blocking():
    image = movzx_dispatch_image(non_executable_indices={29})
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401003)
    assert any(
        row.address == 0x00401003 and row.kind == "computed-flow-blocker" and "target is not executable" in row.detail
        for row in cfg.control_targets.unresolved
    )


def test_movzx_bound_survives_call_for_callee_saved_index():
    image = movzx_dispatch_image(intervening_call=True)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(0x00401008).targets == (0x00401020,) * 256


def test_movzx_bound_does_not_cross_call_for_caller_saved_index():
    image = movzx_dispatch_image(
        caller_saved_index=True,
        intervening_call=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401008)
    assert any(
        row.address == 0x00401008 and row.kind == "computed-flow-blocker" and "no finite dominating guard" in row.detail
        for row in cfg.control_targets.unresolved
    )


def test_closed_byte_producer_domain_bounds_movzx_table():
    image = movzx_dispatch_image(closed_producer_bound=74)
    assert tuple(row.va for row in image.relocations) == tuple(0x00402000 + index * 4 for index in range(75))
    assert {row.type for row in image.relocations} == {3}
    assert image.read(0x0040212C, 4) == b"\0" * 4
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(0x00401047)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x00401070,) * 75


def test_relocated_dispatch_bootstrap_refines_to_used_slot_subset(
    monkeypatch,
):
    image, transfer_address, callbacks = cyclic_relocated_movzx_dispatch_image()
    recoveries = []
    original = _DirectCfgRecovery.recover

    def record_recovery(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        return cfg

    monkeypatch.setattr(_DirectCfgRecovery, "recover", record_recovery)

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert len(recoveries) == 3
    assert cfg is recoveries[-1][1]
    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert (table.index_min, table.index_max) == (0, 2)
    assert table.targets == callbacks[:3]
    bootstrap = tuple(row for row in cfg.seed_inventory.records if row.category == "relocated-dispatch-bootstrap-entry")
    assert tuple(sorted(row.provenance_address for row in bootstrap)) == (
        0x00402000,
        0x00402004,
        0x00402008,
    )
    assert callbacks[3] not in {row.address for row in cfg.instructions}
    assert not any(
        row.source == transfer_address and "bootstrap" in row.flow_kind
        for row in cfg.control_targets.finite_internal_edges
    )
    assert not any(row.address == transfer_address for row in cfg.control_targets.unresolved)


def test_relocated_dispatch_bootstrap_reuses_all_slots_union_trial(
    monkeypatch,
):
    image, transfer_address, _callbacks = cyclic_relocated_movzx_dispatch_image(producer_high=74)
    recoveries = []
    original = _DirectCfgRecovery.recover

    def record_recovery(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        return cfg

    monkeypatch.setattr(_DirectCfgRecovery, "recover", record_recovery)

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert len(recoveries) == 2
    assert cfg is recoveries[-1][1]
    assert cfg.jump_table_at(transfer_address).index_max == 74
    assert (
        len(
            {
                row.provenance_address
                for row in cfg.seed_inventory.records
                if row.category == "relocated-dispatch-bootstrap-entry"
            }
        )
        == 75
    )


@pytest.mark.parametrize(
    "fixture_kwargs",
    (
        {"missing_relocation_index": 0},
        {"non_executable_index": 0},
        {"instruction_interior_index": 0},
        {"tentative_target_overlap": True},
        {"executable_table": True},
        {"raw_only_transfer": True},
        {"bottom_producer": True},
    ),
)
def test_relocated_dispatch_bootstrap_hostile_inputs_remain_unresolved(
    fixture_kwargs,
):
    image, transfer_address, _callbacks = cyclic_relocated_movzx_dispatch_image(**fixture_kwargs)

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)
    assert not any(row.category == "relocated-dispatch-bootstrap-entry" for row in cfg.seed_inventory.records)
    assert not any(
        row.source == transfer_address and "bootstrap" in row.flow_kind
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize(
    "mutation",
    ["conditional-missing-write", "conflicting-path-values"],
)
def test_callee_stack_object_writers_accept_closed_finite_path_values(
    mutation,
):
    image, _movzx_address, transfer_address, _mutator_call = callee_stack_object_writer_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)


def test_unrooted_mutual_recursion_does_not_bootstrap_code():
    image = unrooted_mutual_recursion_image()

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert {row.address for row in cfg.instructions} == {image.entrypoint}
    assert not any("bootstrap" in row.category for row in cfg.seed_inventory.records)


def test_relocated_dispatch_bootstrap_invalidation_rebuilds_clean(
    monkeypatch,
):
    class FirstIterationOnly:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            rows = self.rows
            self.rows = ()
            return iter(rows)

    image, transfer_address, _callbacks = cyclic_relocated_movzx_dispatch_image(producer_high=74)
    recoveries = []
    original = _DirectCfgRecovery.recover

    def invalidate_after_reproduction(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        if len(recoveries) == 2:
            recovery.validated_relocated_dispatch_slot_hypotheses = FirstIterationOnly(
                tuple(recovery.validated_relocated_dispatch_slot_hypotheses)
            )
        return cfg

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "recover",
        invalidate_after_reproduction,
    )

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert len(recoveries) == 3
    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)
    assert not any(row.category == "relocated-dispatch-bootstrap-entry" for row in cfg.seed_inventory.records)


def test_relocated_dispatch_bootstrap_hypotheses_honor_global_entry_cap():
    image, _transfer_address, _callbacks = cyclic_relocated_movzx_dispatch_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    existing = next(iter(recovery.relocated_dispatch_slot_hypotheses))
    recovery.relocated_dispatch_slot_hypotheses = {replace(existing, transfer_address=existing.transfer_address + 1)}
    recovery.limits = replace(
        recovery.limits,
        max_jump_table_entries=76,
    )

    with pytest.raises(AnalysisLimitError) as raised:
        recovery._record_relocated_dispatch_bootstrap_slots()

    assert raised.value.limit_name == "max_jump_table_entries"
    assert raised.value.observed == 76


def test_relocated_dispatch_bootstrap_probes_terminator_after_full_domain():
    image, transfer_address, _callbacks = cyclic_relocated_movzx_dispatch_image(entry_count=256)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    assert recovery.jump_tables[transfer_address].index_max == 255

    recovery.jump_tables.clear()
    recovery.relocated_dispatch_slot_hypotheses.clear()
    recovery._record_relocated_dispatch_bootstrap_slots()

    assert len(recovery.relocated_dispatch_slot_hypotheses) == 256


def global_append_tail_pointee_image(*, mutation=None):
    """A zeroed stack root published as an append-only global list tail."""
    from tools.mwcc_retro import pe as pe_mod

    assert mutation in {
        None,
        "foreign-global-write",
        "out-of-scope-global-write",
        "missing-root-zero",
        "missing-link",
        "finite-payload-overwrite",
        "unselected-unknown-payload",
        "unknown-payload-overwrite",
        "unknown-payload",
        "unselected-clone",
        "selected-clone",
    }
    text_va = 0x00401000
    rdata_va = 0x00402000
    data_va = 0x00403000
    data = bytearray(0xC00)
    text = memoryview(data)[:0x400]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = emit_call(0, 0x40)
    cursor = emit_call(cursor, 0xC0)
    if mutation == "out-of-scope-global-write":
        cursor = emit_call(cursor, 0x3E0)
    emit(cursor, "c3")

    def emit_producer(offset, tag):
        cursor = emit(offset, "83 ec 30 8d 44 24 08 50")
        cursor = emit_call(cursor, 0x1C0)
        cursor = emit(cursor, f"83 c4 04 c6 04 24 {tag:02x}")
        cursor = emit(cursor, "8d 04 24 50")
        append_target = 0x260 if mutation in {"unselected-clone", "selected-clone"} and tag == 74 else 0x200
        cursor = emit_call(cursor, append_target)
        cursor = emit(cursor, "83 c4 04")
        if mutation == "unselected-unknown-payload" and tag == 0:
            cursor = emit(cursor, "52")
            cursor = emit_call(cursor, 0x260)
            cursor = emit(cursor, "59")
        if mutation == "foreign-global-write" and tag == 0:
            cursor = emit_call(cursor, 0x3E0)
        cursor = emit(cursor, "8d 44 24 08 50")
        cursor = emit_call(cursor, 0x140)
        return emit(cursor, "83 c4 04 83 c4 30 c3")

    assert emit_producer(0x40, 0) < 0xC0
    assert emit_producer(0xC0, 74) < 0x140

    # consumer(root): walk root[0], select tag-five nodes, then dispatch on
    # byte zero of the payload stored at node+0xa.
    cursor = emit(0x140, "53 56 8b 74 24 0c 8b 36 85 f6")
    empty_branch = cursor
    cursor = emit(cursor, "74 00")
    loop = cursor
    cursor = emit(cursor, "80 7e 04 05")
    next_branch = cursor
    cursor = emit(cursor, "75 00")
    cursor = emit(cursor, "8b 46 0a")
    movzx_offset = cursor
    cursor = emit(cursor, "0f b6 18")
    transfer_offset = cursor
    cursor = emit(cursor, "ff 14 9d 00 20 40 00")
    next_node = cursor
    cursor = emit(cursor, "8b 36 85 f6")
    loop_branch = cursor
    cursor = emit(cursor, "75 00")
    done = cursor
    emit(cursor, "5e 5b c3")
    text[empty_branch + 1] = done - (empty_branch + 2)
    text[next_branch + 1] = next_node - (next_branch + 2)
    text[loop_branch + 1] = (loop - (loop_branch + 2)) & 0xFF

    # publish_root(root): strict-zero root[0], then establish it as the
    # current append tail.  The negative fixture omits the ordered zero.
    cursor = emit(0x1C0, "8b 4c 24 04")
    if mutation != "missing-root-zero":
        cursor = emit(cursor, "6a 04 51")
        cursor = emit_call(cursor, 0x380)
        cursor = emit(cursor, "83 c4 08 8b 4c 24 04")
    emit(cursor, "89 0d 00 30 40 00 c3")

    # append(payload): allocate one 0x1a-byte node, initialize its link and
    # tag, connect the old global tail, advance the tail, and publish payload.
    cursor = emit(0x200, "53 6a 1a")
    cursor = emit_call(cursor, 0x300)
    cursor = emit(cursor, "59 89 c3 85 db")
    failure_branch = cursor
    initial_tag = 6 if mutation in {"unselected-clone", "selected-clone"} else 5
    cursor = emit(
        cursor,
        f"74 00 c7 03 00 00 00 00 c6 43 04 {initial_tag:02x}",
    )
    cursor = emit(cursor, "a1 00 30 40 00")
    if mutation != "missing-link":
        cursor = emit(cursor, "89 18")
    cursor = emit(cursor, "89 1d 00 30 40 00")
    if mutation in {"unknown-payload", "unselected-clone", "selected-clone"}:
        cursor = emit(cursor, "89 53 0a")
    else:
        cursor = emit(cursor, "8b 44 24 08 89 43 0a")
    if mutation == "finite-payload-overwrite":
        cursor = emit(cursor, "85 c0 74 07 8b 44 24 08 89 43 0a")
    elif mutation == "unknown-payload-overwrite":
        cursor = emit(cursor, "85 c0 74 08")
        cursor = emit_call(cursor, 0x3C0)
        cursor = emit(cursor, "89 43 0a")
    clone_failure_branch = None
    if mutation in {"unselected-clone", "selected-clone"}:
        cursor = emit(cursor, "c6 43 04 07 6a 1a")
        cursor = emit_call(cursor, 0x300)
        cursor = emit(cursor, "59 89 c2 85 d2")
        clone_failure_branch = cursor
        cursor = emit(cursor, "74 00 8d 33 8d 3a a5 a5 a5 a5 a5 a5 66 a5")
        cursor = emit(cursor, "89 13")
        clone_tag = 5 if mutation == "selected-clone" else 8
        cursor = emit(cursor, f"c6 42 04 {clone_tag:02x}")
    cursor = emit(cursor, "5b c3")
    failure = cursor
    emit(cursor, "eb fe")
    text[failure_branch + 1] = failure - (failure_branch + 2)
    if clone_failure_branch is not None:
        text[clone_failure_branch + 1] = failure - (clone_failure_branch + 2)

    if mutation in {"unselected-clone", "selected-clone"}:
        cursor = emit(0x260, "53 6a 1a")
        cursor = emit_call(cursor, 0x300)
        cursor = emit(cursor, "59 89 c3 85 db")
        regular_failure_branch = cursor
        cursor = emit(
            cursor,
            "74 00 c7 03 00 00 00 00 c6 43 04 05 a1 00 30 40 00 89 18 89 1d 00 30 40 00 8b 44 24 08 89 43 0a 5b c3",
        )
        regular_failure = cursor
        emit(cursor, "eb fe")
        text[regular_failure_branch + 1] = regular_failure - (regular_failure_branch + 2)
    elif mutation == "unselected-unknown-payload":
        cursor = emit(0x260, "53 6a 1a")
        cursor = emit_call(cursor, 0x300)
        cursor = emit(cursor, "59 89 c3 85 db")
        unselected_failure_branch = cursor
        cursor = emit(
            cursor,
            "74 00 c7 03 00 00 00 00 c6 43 04 06 a1 00 30 40 00 89 18 89 1d 00 30 40 00 89 53 0a 5b c3",
        )
        unselected_failure = cursor
        emit(cursor, "eb fe")
        text[unselected_failure_branch + 1] = unselected_failure - (unselected_failure_branch + 2)

    # Retail-shaped fixed bump allocator with a local non-null guard at the
    # append site, plus its grow helper and the strict zero helper.
    cursor = emit(0x300, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 10 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 18 30 40 00")
    cursor = emit_call(cursor, 0x360)
    cursor = emit(cursor, "59 59 29 1d 10 30 40 00")
    cursor = emit(cursor, "a1 14 30 40 00 01 1d 14 30 40 00 5b c3")
    assert cursor < 0x360
    emit(0x360, "c3")
    emit(0x380, "31 c0 57 8b 4c 24 0c 8b 7c 24 08 f3 aa 5f c3")
    emit(0x3C0, "c3")
    emit(0x3E0, "89 15 00 30 40 00 c3")

    for index in range(75):
        struct.pack_into("<I", data, 0x400 + index * 4, text_va + 0x3C0)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x400, 0x400, 0x60000020),
            pe_mod.Section(".rdata", rdata_va, 0x400, 0x400, 0x400, 0x40000040),
            pe_mod.Section(".data", data_va, 0x800, 0x400, 0x400, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=tuple(pe_mod.Relocation(rdata_va + index * 4, 3) for index in range(75)),
        executable_ranges=((text_va, text_va + 0x400),),
    )
    return image, text_va + movzx_offset, text_va + transfer_offset


def test_global_append_tail_bounds_nested_payload_dispatch():
    image, movzx_address, transfer_address = global_append_tail_pointee_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401155
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)


def test_global_append_tail_filters_unselected_node_payloads():
    image, _movzx_address, transfer_address = global_append_tail_pointee_image(mutation="unselected-unknown-payload")
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_global_append_tail_ignores_writer_outside_closed_lifetime():
    image, _movzx_address, transfer_address = global_append_tail_pointee_image(mutation="out-of-scope-global-write")
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_global_append_tail_accepts_finite_optional_payload_overwrite():
    image, _movzx_address, transfer_address = global_append_tail_pointee_image(mutation="finite-payload-overwrite")
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74


def test_global_append_tail_accepts_unselected_postpublication_clone():
    image, _movzx_address, transfer_address = global_append_tail_pointee_image(mutation="unselected-clone")
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74


def test_global_append_tail_rejects_selected_postpublication_clone():
    image, _movzx_address, transfer_address = global_append_tail_pointee_image(mutation="selected-clone")
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_pushed_call_argument_crosses_long_straight_line_gap():
    """Retail initializers may separate pushes from a call with many stores."""
    text_va = 0x00401000
    target_offset = 0x80
    data = bytearray(b"\x90" * 0x100)
    data[0:5] = b"\x68" + (0x12345678).to_bytes(4, "little")
    data[5:10] = b"\x68" + (0x76543210).to_bytes(4, "little")
    data[10:50] = b"\x90" * 40
    call_offset = 50
    data[call_offset] = 0xE8
    displacement = target_offset - (call_offset + 5)
    data[call_offset + 1 : call_offset + 5] = displacement.to_bytes(4, "little", signed=True)
    data[call_offset + 5 : call_offset + 9] = bytes.fromhex("83 c4 08 c3")
    data[target_offset] = 0xC3
    image = pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe.Section(".text", text_va, 0, 0x100, 0x100, 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x100),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    argument_zero = recovery._pushed_call_argument(text_va + call_offset, 0)
    argument_one = recovery._pushed_call_argument(text_va + call_offset, 1)

    assert argument_zero is not None
    assert argument_zero[1].imm & 0xFFFF_FFFF == 0x76543210
    assert argument_one is not None
    assert argument_one[1].imm & 0xFFFF_FFFF == 0x12345678


def test_pushed_call_argument_crosses_balanced_helper_calls():
    """An older argument can remain live below balanced helper arguments."""
    text_va = 0x00401000
    helper_offset = 0x80
    target_offset = 0xA0
    data = bytearray(b"\x90" * 0xC0)

    def emit_call(offset, target):
        data[offset] = 0xE8
        displacement = target - (offset + 5)
        data[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = 0
    data[cursor : cursor + 2] = bytes.fromhex("6a 30")
    cursor += 2
    data[cursor : cursor + 2] = bytes.fromhex("6a 11")
    cursor = emit_call(cursor + 2, helper_offset)
    data[cursor] = 0x59
    cursor += 1
    data[cursor : cursor + 2] = bytes.fromhex("6a 12")
    cursor = emit_call(cursor + 2, helper_offset)
    data[cursor : cursor + 3] = bytes.fromhex("83 c4 04")
    cursor += 3
    data[cursor] = 0x50
    target_call = cursor + 1
    cursor = emit_call(target_call, target_offset)
    data[cursor : cursor + 4] = bytes.fromhex("83 c4 08 c3")
    data[helper_offset] = 0xC3
    data[target_offset] = 0xC3

    image = pe.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe.Section(".text", text_va, 0, 0xC0, 0xC0, 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0xC0),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    argument_zero = recovery._pushed_call_argument(text_va + target_call, 0)
    argument_one = recovery._pushed_call_argument(text_va + target_call, 1)

    assert argument_zero is not None
    assert argument_zero[0].address == text_va + target_call - 1
    assert argument_one is not None
    assert argument_one[1].imm & 0xFFFF_FFFF == 0x30


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign-global-write",
        "missing-root-zero",
        "missing-link",
        "unknown-payload-overwrite",
        "unknown-payload",
    ],
)
def test_global_append_tail_rejects_open_publication(mutation):
    image, _movzx_address, transfer_address = global_append_tail_pointee_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_closed_forwarded_byte_producer_domain_bounds_movzx_table():
    image, movzx_address, transfer_address = forwarded_movzx_dispatch_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401085
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x004010F0,) * 75


def test_recursive_nested_argument_producer_stops_at_bottom():
    image, transfer_address = recursive_nested_movzx_dispatch_image()

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_object_guard_answers_local_discriminator_before_recursive_origin():
    image, _factory_call, consumer_call, observation = guarded_call_return_object_origins_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    consumer = image.entrypoint + 0xC0
    root_observation = recovery._previous_instruction(observation).address
    context = (consumer, consumer_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            root_observation,
            "eax",
            consumer,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({4})
    assert "dominating-affine-byte-equality" in result[1]


def test_guarded_recursive_call_return_closes_from_terminal_base():
    image, selector_call, _recursive_call, terminal_return = guarded_recursive_call_return_object_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    guard = _ObjectByteGuard(
        image.entrypoint,
        selector_call + 5,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        terminal_return - 9,
        "modeled-downstream-tag-four",
    )
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._finite_object_byte_call_return_values_before(
            selector_call,
            image.entrypoint + 0x80,
            image.entrypoint,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard

    assert result is not None
    assert result[0] == frozenset({0x29})
    assert "recursive-object-domain" in result[1]


@pytest.mark.parametrize(
    ("terminal_tag", "child_tag"),
    [(5, 0x29), (4, None)],
)
def test_guarded_recursive_call_return_rejects_open_terminal(
    terminal_tag,
    child_tag,
):
    image, selector_call, _recursive_call, terminal_return = guarded_recursive_call_return_object_image(
        terminal_tag=terminal_tag,
        child_tag=child_tag,
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    guard = _ObjectByteGuard(
        image.entrypoint,
        selector_call + 5,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        terminal_return - 9,
        "modeled-downstream-tag-four",
    )
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._finite_object_byte_call_return_values_before(
            selector_call,
            image.entrypoint + 0x80,
            image.entrypoint,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard

    assert result is None


def test_register_copy_preserves_guard_disjoint_call_result(monkeypatch):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x21)
    data[0:6] = bytes.fromhex("e8 1b 00 00 00 c3")
    data[0x20] = 0xC3
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    def modeled_call_return(*_args, **_kwargs):
        return (
            frozenset(),
            "call=0x401000;target=0x401020;guard-disjoint;modeled",
        )

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_call_return_values_before",
        modeled_call_return,
    )

    result = recovery._finite_object_byte_register_values_before(
        text_va + 5,
        "eax",
        text_va,
        (10, 0),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset()
    assert recovery._object_result_has_flag(result[1], "guard-disjoint")


def test_overwritten_register_origin_excludes_later_normalizer_path(
    monkeypatch,
):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0xA1)
    data[0:23] = bytes.fromhex("e8 7b 00 00 00 89 c5 85 c9 75 09 50 e8 8f 00 00 00 59 89 c5 89 e8 c3")
    data[0x80] = 0xC3
    data[0xA0] = 0xC3
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    first_definition = text_va + 5
    normalizer_call = text_va + 12
    later_definition = text_va + 18
    fresh_observation = text_va + 20
    observation = text_va + 22
    original_origins = recovery._fresh_allocation_origin_calls_before

    def modeled_origins(address, register_family, function_entry, active=frozenset()):
        if address == first_definition and register_family == "eax":
            return frozenset({text_va})
        return original_origins(address, register_family, function_entry, active)

    def modeled_fresh(
        allocation_call,
        observation_address,
        function_entry,
        field_path,
        visited,
        *,
        excluded_addresses=frozenset(),
        **_kwargs,
    ):
        assert allocation_call == text_va
        assert observation_address == fresh_observation
        if field_path == (0,):
            return frozenset({0x1E}), "modeled-disjoint-root"
        if excluded_addresses == frozenset({later_definition}):
            return frozenset(), "guard-disjoint;modeled-overwritten-origin"
        return None

    def modeled_call_return(
        call_address,
        _call_target,
        _caller_entry,
        field_path,
        _visited,
    ):
        assert call_address == normalizer_call
        return (
            (frozenset({4}), "modeled-normalized-root")
            if field_path == (0,)
            else (frozenset({0x29}), "modeled-normalized-child")
        )

    monkeypatch.setattr(
        recovery,
        "_fresh_allocation_origin_calls_before",
        modeled_origins,
    )
    monkeypatch.setattr(
        recovery,
        "_finite_fresh_allocation_object_byte_values_before",
        modeled_fresh,
    )
    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_call_return_values_before",
        modeled_call_return,
    )
    guard = _ObjectByteGuard(
        text_va,
        observation,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        text_va + 7,
        "modeled-downstream-tag-four",
    )
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "eax",
            text_va,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard

    assert result is not None
    assert result[0] == frozenset({0x29})
    assert "modeled-overwritten-origin" in result[1]


def test_object_guard_recovers_merged_affine_byte_ranges():
    image, default_return, merged_return = affine_byte_range_merge_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    merged = recovery._object_byte_case_guard_before(
        merged_return - 2,
        "ebp",
        image.entrypoint,
        (0,),
    )
    default = recovery._object_byte_case_guard_before(
        default_return - 2,
        "ebp",
        image.entrypoint,
        (0,),
    )

    selected = frozenset({2, 3, *range(0x1E, 0x2A)})
    assert merged is not None
    assert merged.values == selected
    assert "affine-byte-branch-domain" in merged.provenance
    assert default is not None
    assert default.values == frozenset(range(0x100)) - selected


def test_object_guard_rejects_affine_domain_after_tag_overwrite():
    image, _default_return, merged_return = affine_byte_range_merge_image(overwrite_after_load=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._object_byte_case_guard_before(
            merged_return - 2,
            "ebp",
            image.entrypoint,
            (0,),
        )
        is None
    )

    result = recovery._finite_object_byte_register_values_before(
        merged_return,
        "eax",
        image.entrypoint,
        (0,),
        frozenset(),
    )
    assert result is not None
    assert result[0] == frozenset({0x77})
    assert "affine-byte-branch-domain" not in result[1]


def test_object_guard_filters_disjoint_call_return_origins():
    image, _factory_call, consumer_call, observation = guarded_call_return_object_origins_image(
        disjoint_empty_child=True
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    consumer = image.entrypoint + 0xC0
    context = (consumer, consumer_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "eax",
            consumer,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29})
    assert "guard-disjoint" in result[1]
    assert not recovery._object_result_has_flag(result[1], "optional-empty-association")


def test_object_guard_filters_disjoint_normal_callee_effect():
    image, _factory_call, consumer_call, observation = guarded_call_return_object_origins_image(disjoint_mutator=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    consumer = image.entrypoint + 0xC0
    mutator = image.entrypoint + 0x100
    mutator_call = next(
        address for address, target in recovery.direct_call_targets_by_source.items() if target == mutator
    )
    contexts = (
        (consumer, consumer_call, image.entrypoint),
        (mutator, mutator_call, consumer),
    )
    guard = _ObjectByteGuard(
        consumer,
        observation,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        observation,
        "modeled-downstream-tag-four",
    )
    recovery.producer_exact_call_contexts.extend(contexts)
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._callee_argument_byte_effect(
            mutator,
            0,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard
        for context in reversed(contexts):
            assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset()
    assert recovery._callee_effect_has_flag(result[1], "optional-preserve")
    assert "guard-filtered" in result[1]


def test_argument_object_byte_cache_is_guard_context_sensitive(monkeypatch):
    image, _factory_call, _consumer_call, observation = guarded_call_return_object_origins_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    consumer = image.entrypoint + 0xC0
    evaluations = []

    def modeled_argument(
        address,
        function_entry,
        argument_index,
        field_path,
        visited,
        *,
        excluded_addresses=frozenset(),
    ):
        guard = recovery.producer_object_guard_contexts[-1]
        evaluations.append(guard)
        return guard.values, guard.provenance

    monkeypatch.setattr(
        recovery,
        "_finite_argument_object_byte_values_before_uncached",
        modeled_argument,
    )
    results = []
    for value in (4, 5):
        guard = _ObjectByteGuard(
            consumer,
            observation,
            "eax",
            (10, 0),
            0,
            frozenset({value}),
            observation,
            f"modeled-tag-{value}-guard",
        )
        recovery.producer_object_guard_contexts.append(guard)
        try:
            results.append(
                recovery._finite_argument_object_byte_values_before(
                    observation,
                    consumer,
                    0,
                    (10, 0),
                    frozenset(),
                )
            )
        finally:
            assert recovery.producer_object_guard_contexts.pop() == guard

    assert [result[0] for result in results] == [
        frozenset({4}),
        frozenset({5}),
    ]
    assert len(evaluations) == 2


def test_pointer_origin_shift_replaces_the_unshifted_guard(monkeypatch):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytes.fromhex("8b 43 0a c3")
    image = pe_mod.Image(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original_guard = _ObjectByteGuard(
        text_va,
        text_va + 3,
        "eax",
        (0,),
        0,
        frozenset({4}),
        text_va + 3,
        "modeled-unshifted-guard",
    )

    def modeled_parent(address, register_family, function_entry, field_path, visited):
        assert (address, register_family, function_entry, field_path) == (
            text_va,
            "ebx",
            text_va,
            (10, 0),
        )
        assert original_guard not in recovery.producer_object_guard_contexts
        shifted = recovery.producer_object_guard_contexts[-1]
        assert shifted.field_path == (10, 0)
        assert shifted.discriminator_path == (10, 0)
        return frozenset({0x29}), "modeled-shifted-parent"

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_register_values_before",
        modeled_parent,
    )
    recovery.producer_object_guard_contexts.append(original_guard)
    try:
        result = recovery._finite_object_byte_register_values_before_uncached(
            text_va + 3,
            "eax",
            text_va,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == original_guard

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_exact_caller_argument_preserves_guard_disjoint_result(monkeypatch):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x26)
    data[0:8] = bytes.fromhex("50 e8 1a 00 00 00 59 c3")
    data[0x20:0x26] = bytes.fromhex("8b 44 24 04 89 c0 c3")
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    def modeled_operand(*_args, **_kwargs):
        return frozenset(), "guard-disjoint;modeled-exact-caller"

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_operand_values_before",
        modeled_operand,
    )
    callee = text_va + 0x20
    context = (callee, text_va + 1, text_va)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_object_byte_values_before(
            callee + 6,
            callee,
            0,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset()
    assert recovery._object_result_has_flag(result[1], "guard-disjoint")


def test_guarded_definition_rejects_disjoint_exact_argument(monkeypatch):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x60)
    data[0:8] = bytes.fromhex("50 e8 3a 00 00 00 59 c3")
    data[0x40:0x50] = bytes.fromhex("53 8b 5c 24 08 80 3b 2a 75 04 8b 44 24 0c 5b c3")
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    def modeled_operand(*_args, **_kwargs):
        probe = recovery._producer_object_guard_context((0,))
        assert probe is not None
        assert probe.values == frozenset({0x2A})
        return frozenset(), "guard-disjoint;modeled-input-tag=0x43"

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_operand_values_before",
        modeled_operand,
    )
    callee = text_va + 0x40
    context = (callee, text_va + 1, text_va)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._guarded_exact_argument_definition_disjoint(
            callee + 0xA,
            callee,
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert "argument=0" in result
    assert "guard=0x401045" in result
    assert "guard-disjoint" in result


@pytest.mark.parametrize(
    ("input_tag", "is_disjoint"),
    (
        (0x1E, True),
        (4, False),
        (0x30, False),
    ),
)
def test_guarded_argument_traversal_requires_a_reachable_first_link(
    monkeypatch,
    input_tag,
    is_disjoint,
):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x60)
    data[0:8] = bytes.fromhex("50 e8 3a 00 00 00 59 c3")
    data[0x40:0x5E] = bytes.fromhex(
        "55 8b 6c 24 08 80 7d 00 30 74 0e 80 7d 00 04 74 04 31 c0 5d c3 89 e8 5d c3 8b 6d 0a eb e7"
    )
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    def modeled_operand(*_args, **_kwargs):
        probe = recovery._producer_object_guard_context((0,))
        assert probe is not None
        if input_tag in probe.values:
            return frozenset({input_tag}), "modeled-probe-hit"
        return frozenset(), "guard-disjoint;modeled-probe-miss"

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_operand_values_before",
        modeled_operand,
    )
    callee = text_va + 0x40
    terminal_return = text_va + 0x58
    context = (callee, text_va + 1, text_va)
    guard = _ObjectByteGuard(
        text_va,
        text_va + 6,
        "eax",
        (0,),
        0,
        frozenset({4}),
        text_va + 6,
        "modeled-downstream-tag-four",
    )
    recovery.producer_exact_call_contexts.append(context)
    recovery.producer_object_guard_contexts.append(guard)
    traversal_result = None
    try:
        result = recovery._guarded_argument_traversal_return_disjoint(
            terminal_return,
            callee,
            (0,),
            frozenset(),
            guard,
        )
        if input_tag in {0x1E, 0x30}:
            monkeypatch.setattr(
                recovery,
                "_finite_argument_object_byte_values_before",
                lambda *_args, **_kwargs: (
                    frozenset({4}),
                    "modeled-exact-caller-child",
                ),
            )
            traversal_result = recovery._finite_object_byte_register_values_before(
                text_va + 0x53,
                "ebp",
                callee,
                (10, 0),
                frozenset(),
            )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard
        assert recovery.producer_exact_call_contexts.pop() == context

    assert (result is not None) is is_disjoint
    if result is not None:
        assert "unstarted-argument-traversal" in result
    if input_tag in {0x1E, 0x30}:
        assert (traversal_result is not None) is (input_tag == 0x1E)
    if traversal_result is not None:
        assert traversal_result[0] == frozenset({4})
        assert "unstarted-argument-traversal" in traversal_result[1]


def test_object_guard_rejects_normal_effect_before_disjoint_tag_write():
    image, _factory_call, consumer_call, observation = guarded_call_return_object_origins_image(
        disjoint_mutator=True,
        mutator_pointer_before_tag=True,
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    consumer = image.entrypoint + 0xC0
    mutator = image.entrypoint + 0x100
    mutator_call = next(
        address for address, target in recovery.direct_call_targets_by_source.items() if target == mutator
    )
    contexts = (
        (consumer, consumer_call, image.entrypoint),
        (mutator, mutator_call, consumer),
    )
    guard = _ObjectByteGuard(
        consumer,
        observation,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        observation,
        "modeled-downstream-tag-four",
    )
    recovery.producer_exact_call_contexts.extend(contexts)
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._callee_argument_byte_effect(
            mutator,
            0,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard
        for context in reversed(contexts):
            assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_object_guard_filters_disjoint_optional_empty_return(monkeypatch):
    image, factory_call, _consumer_call, _observation = guarded_call_return_object_origins_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    factory = image.entrypoint + 0x80
    returns = (factory + 8, factory + 13)
    original = recovery._finite_object_byte_register_values_before

    def modeled_returns(address, register_family, function_entry, field_path, visited):
        if function_entry != factory or register_family != "eax":
            return original(address, register_family, function_entry, field_path, visited)
        assert address in returns
        if field_path == (10, 0):
            return (
                (frozenset({0x29}), "modeled-child")
                if address == returns[0]
                else (
                    frozenset(),
                    "optional-empty-association;modeled-empty-child",
                )
            )
        assert field_path == (0,)
        return (
            frozenset({4 if address == returns[0] else 5}),
            "modeled-root-tag",
        )

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_register_values_before",
        modeled_returns,
    )
    guard = _ObjectByteGuard(
        image.entrypoint + 0xC0,
        image.entrypoint + 0xD0,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        image.entrypoint + 0xC4,
        "modeled-tag-four-guard",
    )
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._finite_object_byte_call_return_values_before(
            factory_call,
            factory,
            image.entrypoint,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard

    assert result is not None
    assert result[0] == frozenset({0x29})
    assert "guard-disjoint" in result[1]
    assert not recovery._object_result_has_flag(result[1], "optional-empty-association")


@pytest.mark.parametrize("open_discriminator", [5, 4])
def test_object_guard_filters_disjoint_fresh_allocation_origin(monkeypatch, open_discriminator):
    image, _factory_call, consumer_call, _observation = guarded_call_return_object_origins_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    query_address = consumer_call
    original_origins = recovery._fresh_allocation_origin_calls_before
    original_result = recovery._finite_fresh_allocation_object_byte_values_before

    def modeled_origins(address, register_family, function_entry, active=frozenset()):
        if address == query_address and register_family == "eax":
            return frozenset({0x111, 0x222})
        return original_origins(address, register_family, function_entry, active)

    def modeled_allocation(
        allocation_call,
        observation_address,
        function_entry,
        field_path,
        visited,
        **kwargs,
    ):
        if allocation_call not in {0x111, 0x222}:
            return original_result(
                allocation_call,
                observation_address,
                function_entry,
                field_path,
                visited,
                **kwargs,
            )
        if field_path == (10, 0):
            return (frozenset({0x29}), "modeled-fresh-child") if allocation_call == 0x111 else None
        assert field_path == (0,)
        return (
            frozenset({4 if allocation_call == 0x111 else open_discriminator}),
            "modeled-fresh-discriminator",
        )

    monkeypatch.setattr(
        recovery,
        "_fresh_allocation_origin_calls_before",
        modeled_origins,
    )
    monkeypatch.setattr(
        recovery,
        "_finite_fresh_allocation_object_byte_values_before",
        modeled_allocation,
    )
    guard = _ObjectByteGuard(
        image.entrypoint,
        query_address,
        "eax",
        (10, 0),
        0,
        frozenset({4}),
        query_address,
        "modeled-tag-four-guard",
    )
    recovery.producer_object_guard_contexts.append(guard)
    try:
        result = recovery._finite_object_byte_register_values_before(
            query_address,
            "eax",
            image.entrypoint,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_object_guard_contexts.pop() == guard

    if open_discriminator == 4:
        assert result is None
    else:
        assert result is not None
        assert result[0] == frozenset({0x29})
        assert "guard-disjoint" in result[1]


@pytest.mark.parametrize(
    "mutation",
    ["missing-guard", "guard-bypass", "unknown-matching-child"],
)
def test_object_guard_rejects_open_matching_or_unguarded_origin(mutation):
    image, _factory_call, consumer_call, observation = guarded_call_return_object_origins_image(
        guard_root_tag=mutation != "missing-guard",
        guard_bypasses_load=mutation == "guard-bypass",
        unknown_matching_child=mutation == "unknown-matching-child",
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    consumer = image.entrypoint + 0xC0
    context = (consumer, consumer_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "eax",
            consumer,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_object_guard_filters_disjoint_exact_outparam_origins(monkeypatch):
    image, _outparam_call, consumer_call, observation = guarded_outparam_object_origins_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original = recovery._relative_pointer_states
    producer = image.entrypoint + 0x80

    def open_producer_state(function_entry, **kwargs):
        if function_entry == producer and kwargs.get("argument_index") == 0:
            return None
        return original(function_entry, **kwargs)

    monkeypatch.setattr(recovery, "_relative_pointer_states", open_producer_state)
    consumer = image.entrypoint + 0xC0
    context = (consumer, consumer_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "eax",
            consumer,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29})
    assert "guard-filtered" in result[1]


@pytest.mark.parametrize("mutation", ["guard-bypass", "unknown-matching-child"])
def test_object_guard_rejects_open_exact_outparam_origin(monkeypatch, mutation):
    image, _outparam_call, consumer_call, observation = guarded_outparam_object_origins_image(
        guard_bypasses_load=mutation == "guard-bypass",
        unknown_matching_child=mutation == "unknown-matching-child",
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original = recovery._relative_pointer_states
    producer = image.entrypoint + 0x80

    def open_producer_state(function_entry, **kwargs):
        if function_entry == producer and kwargs.get("argument_index") == 0:
            return None
        return original(function_entry, **kwargs)

    monkeypatch.setattr(recovery, "_relative_pointer_states", open_producer_state)
    consumer = image.entrypoint + 0xC0
    context = (consumer, consumer_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "eax",
            consumer,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_callee_stack_object_writers_bound_nested_movzx_table():
    image, movzx_address, transfer_address, _mutator_call = callee_stack_object_writer_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401106
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x00401240,) * 75


def test_callee_published_stack_pointee_bounds_nested_movzx_table():
    image, movzx_address, transfer_address, _mutator_call = callee_stack_object_writer_image(
        callee_published_outer=True
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401106
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x00401240,) * 75


def test_callee_zero_then_published_stack_pointee_bounds_nested_movzx_table():
    image, movzx_address, transfer_address, _mutator_call = callee_stack_object_writer_image(
        mutation="outer-strict-zero-before-publish",
        callee_published_outer=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401106
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x00401240,) * 75


def test_allocation_backed_stack_pointee_bounds_nested_movzx_table():
    image, movzx_address, transfer_address = allocation_backed_stack_pointee_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401146
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x004014C0,) * 75


def test_stack_slot_fresh_pointer_observes_later_initialization():
    image, movzx_address, transfer_address = late_initialized_stack_slot_allocation_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_address == movzx_address
    assert (table.index_min, table.index_max) == (0x29, 0x29)


def test_stack_slot_fresh_pointer_observes_later_bulk_copy():
    image, movzx_address, transfer_address = late_initialized_stack_slot_allocation_image(bulk_copy=True)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_address == movzx_address
    assert (table.index_min, table.index_max) == (0x29, 0x29)


def test_stack_slot_fresh_pointer_observes_unaligned_nested_bulk_copy():
    image, movzx_address, transfer_address = late_initialized_stack_slot_allocation_image(nested_bulk_copy=True)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_address == movzx_address
    assert (table.index_min, table.index_max) == (0x29, 0x29)


def test_stack_slot_fresh_pointer_rejects_alternate_clobber():
    image, _movzx_address, transfer_address = late_initialized_stack_slot_allocation_image(clobber_slot=True)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_zero_then_allocation_backed_stack_pointee_bounds_nested_movzx_table():
    image, movzx_address, transfer_address = allocation_backed_stack_pointee_image(
        mutation="wrapper-strict-zero-before-allocation"
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401146
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x004014C0,) * 75


def test_allocation_backed_stack_pointee_certificate_binds_owned_chain(
    tmp_path,
):
    image, movzx_address, transfer_address = allocation_backed_stack_pointee_image()
    checkpoint_dir = tmp_path / "allocation-producer-checkpoints"
    cfg = _complete_resumable_producer_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
        checkpoint_dir,
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74
    certificates = [json.loads(path.read_bytes()) for path in checkpoint_dir.glob("*.json")]
    certificate = next(row for row in certificates if row["query"]["movzx_address"] == movzx_address)
    dependencies = {row["identifier"] for row in certificate["dependencies"]}
    assert {
        0x00401040,  # caller producing tag 0
        0x004010C0,  # caller producing tag 74
        0x00401140,  # nested-byte consumer
        0x004011C0,  # forwarding wrapper
        0x00401200,  # initializer/list linker
        0x00401400,  # owned bump allocator
        0x00401460,  # allocator grow helper
        0x00401480,  # strict outer zero helper
        0x004014A0,  # read-only base consumer
        0x004014B0,  # read-only +4 consumer
    } <= dependencies


def test_lifecycle_total_allocation_and_optional_empty_tail_bound_table():
    image, movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image()
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401206
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x00401600,) * 75


def test_lifecycle_terminal_nonzero_success_check_bounds_table():
    image, _movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(
        mutation="terminal-nonzero-success"
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_lifecycle_naked_context_save_and_restore_bounds_table():
    image, _movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(mutation="naked-context-save")
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_lifecycle_flag_preserving_cleanup_between_test_and_branch():
    image, _movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(
        mutation="cleanup-between-test-and-branch"
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_allocator_totality_accepts_reset_outside_closed_lifetime():
    image, _movzx_address, _transfer_address = lifecycle_optional_allocation_pointee_image(mutation="reset-reachable")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    lifetime_roots = frozenset({0x00401080, 0x00401140})

    assert recovery._allocator_totality_certificate(0x00401380, 0x00401300) is None
    certificate = recovery._allocator_totality_certificate(
        0x00401380,
        0x00401300,
        lifetime_roots=lifetime_roots,
    )

    assert certificate is not None
    assert certificate.lifetime_roots == lifetime_roots


def test_lifecycle_optional_certificate_binds_session_and_push_chain(tmp_path):
    image, movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image()
    checkpoint_dir = tmp_path / "lifecycle-optional-checkpoints"
    cfg = _complete_resumable_producer_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
        checkpoint_dir,
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74
    certificates = [json.loads(path.read_bytes()) for path in checkpoint_dir.glob("*.json")]
    certificate = next(row for row in certificates if row["query"]["movzx_address"] == movzx_address)
    dependencies = {row["identifier"] for row in certificate["dependencies"]}
    assert {
        0x00401000,  # checked session root
        0x00401080,  # sentinel/tag-0 producer
        0x00401140,  # sentinel/tag-74 producer
        0x00401200,  # null-checked traversal
        0x00401240,  # optional/multiple-push wrapper
        0x00401300,  # allocation-backed list push
        0x00401380,  # fixed bump allocator
        0x00401400,  # backend root
        0x00401440,  # descriptor grow/OOM dispatch
        0x004014A0,  # checked arena initialization
        0x00401520,  # setjmp-like context save
        0x00401540,  # nonreturning longjmp-like restore
        0x00401560,  # installed OOM callback
        0x00401580,  # generation-reset function
        0x004015A0,  # system allocator
        0x004015C0,  # strict sentinel zero helper
    } <= dependencies


def test_retail_multi_attempt_grow_preserves_optional_empty_tail_bound():
    image, movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(
        mutation="retail-multi-attempt"
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert movzx_address == 0x00401206
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74
    assert (table.index_min, table.index_max) == (0, 74)
    assert table.targets == (0x00401600,) * 75


def test_retail_multi_attempt_certificate_binds_complete_grow_chain(tmp_path):
    image, movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(
        mutation="retail-multi-attempt"
    )
    checkpoint_dir = tmp_path / "retail-multi-attempt-checkpoints"
    cfg = _complete_resumable_producer_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
        checkpoint_dir,
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74
    certificates = [json.loads(path.read_bytes()) for path in checkpoint_dir.glob("*.json")]
    certificate = next(row for row in certificates if row["query"]["movzx_address"] == movzx_address)
    dependencies = {(row["kind"], row["identifier"]) for row in certificate["dependencies"]}
    assert {
        ("function", 0x00401000),  # checked session root
        ("function", 0x00401300),  # allocation-backed list push
        ("function", 0x00401380),  # fixed bump allocator
        ("function", 0x00401400),  # backend root
        ("function", 0x00401440),  # descriptor grow/OOM dispatch
        ("function", 0x004014C0),  # checked arena initialization
        ("function", 0x00401520),  # setjmp-like context save
        ("function", 0x00401540),  # nonreturning longjmp-like restore
        ("function", 0x00401560),  # installed OOM callback
        ("function", 0x004015A0),  # primary allocator and retry
        ("function", 0x00401640),  # fallback allocator
        ("function", 0x00401660),  # successful-allocation finalizer
        ("global-slot", 0x00403080),  # installed OOM callback slot
    } <= dependencies


@pytest.mark.parametrize(
    "mutation",
    [
        "retail-missing-recovery",
        "retail-ambiguous-retry",
        "retail-success-bypass-finalizer",
        "retail-conditional-finalizer",
        "retail-missing-finalizer",
        "retail-extra-call-escape",
        "retail-result-escape",
        "retail-returning-callback",
    ],
)
def test_retail_multi_attempt_grow_rejects_open_totality(mutation):
    image, _movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


@pytest.mark.parametrize(
    "mutation",
    [
        "unchecked-init",
        "one-arena-null-path",
        "returning-callback",
        "callback-overwritten",
        "reset-reachable",
        "alternate-backend-entry",
        "allocation-before-init",
        "unknown-initial-head",
        "deref-before-null",
        "partial-outer-store",
        "outer-pointer-escape",
        "link-mutation",
        "tag-mutation",
    ],
)
def test_lifecycle_optional_allocation_rejects_open_session_or_tail(mutation):
    image, _movzx_address, transfer_address = lifecycle_optional_allocation_pointee_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


@pytest.mark.parametrize(
    "mutation",
    [
        "unowned-allocator",
        "allocator-result-escape",
        "outer-pointer-escape",
        "variable-size",
        "zero-size",
        "unchecked-null",
        "conditional-missing-publish",
        "second-allocation",
        "partial-outer-store",
        "alternate-outer-store",
        "node-escape-before-init",
        "unknown-node-overlap",
        "interior-clobber",
        "generation-reuse",
        "wrapper-strict-zero-after-publication",
    ],
)
def test_allocation_backed_stack_pointee_rejects_open_effects(mutation):
    image, _movzx_address, transfer_address = allocation_backed_stack_pointee_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


@pytest.mark.parametrize(
    "mutation",
    [
        "outer-unowned-callee",
        "outer-indirect-callee",
        "outer-ambiguous-alias",
        "outer-pointer-escape",
        "outer-strict-zero-after-publish",
        "outer-strict-zero-only",
        "outer-pointee-use",
        "outer-conditional-missing-write",
        "outer-partial-overlap",
        "outer-partial-pointee-register",
        "outer-conflicting-pointees",
        "outer-multiple-writers",
        "outer-unknown-pointee",
        "outer-clobber",
        "outer-null-pointee",
        "outer-recursive-callee",
        "outer-recursive-pointee",
    ],
)
def test_callee_published_stack_pointee_rejects_open_associations(mutation):
    image, _movzx_address, transfer_address, _mutator_call = callee_stack_object_writer_image(
        mutation=mutation,
        callee_published_outer=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


@pytest.mark.parametrize(
    "mutation",
    [
        "unowned-callee",
        "indirect-callee",
        "ambiguous-alias",
        "pointer-escape",
        "partial-overlap",
        "post-call-clobber",
    ],
)
def test_callee_stack_object_writers_reject_open_effects(mutation):
    image, _movzx_address, transfer_address, _mutator_call = callee_stack_object_writer_image(mutation=mutation)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_forwarded_byte_domain_survives_a_prior_finite_dispatch():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(duplicate_consumer_dispatch=True)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74
    assert cfg.jump_table_at(transfer_address + 0x12).guard_bound == 74


def test_byte_producer_preservation_ignores_bypass_arm_that_cannot_reach_load():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        consumer_bypass_unknown_callback=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


@pytest.mark.parametrize(
    "fixture_kwargs",
    [
        {
            "consumer_bypass_unknown_callback": True,
            "consumer_bypass_rejoins": True,
        },
        {
            "consumer_bypass_mutates_before_rejoin": True,
            "consumer_bypass_rejoins": True,
        },
    ],
)
def test_byte_producer_preservation_keeps_arms_that_reach_load_blocking(
    fixture_kwargs,
):
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(**fixture_kwargs)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_byte_producer_follows_pointer_spilled_to_logical_stack_slot():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        consumer_stack_spill="clean",
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_stack_slot_pointer_ignores_general_ebp_object_writes():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        consumer_stack_spill="unrelated-ebp-write",
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74


def test_stack_slot_pointer_ignores_postdominated_unknown_writer():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        consumer_stack_spill="superseded-unknown-store",
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74


@pytest.mark.parametrize(
    "mutation",
    [
        "conflicting-store",
        "unknown-stack-delta",
        "overlap-write",
        "missing-dominating-store",
    ],
)
def test_byte_producer_rejects_open_stack_slot_pointer_provenance(mutation):
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        consumer_stack_spill=mutation,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_byte_producer_combines_conditional_alias_and_helper_return_objects():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        conditional_helper_return="clean",
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def test_byte_producer_maps_returned_argument_to_exact_call_site():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        conditional_helper_return="clean",
        unrelated_helper_caller=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    table = cfg.jump_table_at(transfer_address)
    assert table.guard_operator == "movzx-producer-domain"
    assert table.guard_bound == 74


def callee_return_argument_byte_effect_image(*, unknown_write=False):
    """Two return arms: one mutates argument byte zero, one preserves it."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    write = "88 08" if unknown_write else "c6 00 30"
    branch = "03" if unknown_write else "04"
    data = bytes.fromhex(f"8b 44 24 04 85 c9 74 {branch} {write} c3 c3")
    return pe_mod.Image(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )


def callee_intermediate_argument_byte_effect_image():
    """One optional finite writer reconverges before a non-RET observation."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytes.fromhex("8b 44 24 04 85 c9 74 03 c6 00 30 90 c3")
    image = pe_mod.Image(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    return image, text_va + 0xB


def test_callee_argument_byte_effect_stops_at_exact_observation():
    image, observation = callee_intermediate_argument_byte_effect_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(
        image.entrypoint,
        0,
        (0,),
        frozenset(),
        end_address=observation,
    )

    assert result is not None
    assert result[0] == frozenset({0x30})
    assert "optional-preserve" in result[1]


def test_callee_argument_byte_effect_scopes_writer_to_exact_return():
    image = callee_return_argument_byte_effect_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(
        image.entrypoint,
        0,
        (0,),
        frozenset(),
        end_address=image.entrypoint + 0xB,
    )

    assert result is not None
    assert result[0] == frozenset({0x30})


def test_callee_argument_byte_effect_rejects_unknown_exact_return_writer():
    image = callee_return_argument_byte_effect_image(unknown_write=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._callee_argument_byte_effect(
            image.entrypoint,
            0,
            (0,),
            frozenset(),
            end_address=image.entrypoint + 0xA,
        )
        is None
    )


def test_callee_argument_byte_effect_records_optional_preservation():
    image = callee_return_argument_byte_effect_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset())

    assert result is not None
    assert result[0] == frozenset({0x30})
    assert "optional-preserve" in result[1]


def partial_scalar_argument_copy_image(*, full_publish=False):
    """Read a scalar through arg0 and store it outside the argument."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data_va = 0x00403000
    store = "a3 00 30 40 00" if full_publish else "66 a3 00 30 40 00"
    data = bytes.fromhex(f"8b 44 24 04 66 8b 40 02 {store} c3")
    return pe_mod.Image(
        data=data + bytes(0x20),
        sha256=hashlib.sha256(data + bytes(0x20)).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),
            pe_mod.Section(
                ".data",
                data_va,
                len(data),
                0x20,
                0x20,
                0xC0000040,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )


def test_callee_argument_effect_allows_partial_scalar_copy():
    image = partial_scalar_argument_copy_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset())

    assert result is not None
    assert result[0] == frozenset()


def test_callee_argument_effect_rejects_full_tainted_publication():
    image = partial_scalar_argument_copy_image(full_publish=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset()) is None


def fresh_string_copy_argument_effect_image(
    *,
    unknown_source_write=False,
    stale_pointer_scalarization=False,
    use_scalarized_pointer=False,
    contained_pointer_publication=False,
    escape_pointer_container=False,
):
    """Copy one initialized byte from a guarded fresh object into arg0."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data_va = 0x00403000
    data = bytearray(0x400)
    text = memoryview(data)[:0x200]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = emit(0, "56 57 8b 7c 24 0c 6a 1a")
    allocation_call = cursor
    cursor = emit_call(cursor, 0x100)
    cursor = emit(cursor, "89 c6 59 85 f6")
    failure_branch = cursor
    cursor = emit(cursor, "74 00")
    cursor = emit(cursor, "88 16" if unknown_source_write else "c6 06 1e")
    if contained_pointer_publication or escape_pointer_container:
        cursor = emit(cursor, "89 7e 04")
    if escape_pointer_container:
        cursor = emit(cursor, "56")
        cursor = emit_call(cursor, 0x180)
        cursor = emit(cursor, "59")
    cursor = emit(cursor, "a5")
    if stale_pointer_scalarization or use_scalarized_pointer:
        cursor = emit(cursor, "83 e7 03")
        cursor = emit(
            cursor,
            "c6 07 7f" if use_scalarized_pointer else "66 89 7e 02",
        )
    cursor = emit(cursor, "31 c0 5f 5e c3")
    failure = cursor
    emit(cursor, "eb fe")
    text[failure_branch + 1] = failure - (failure_branch + 2)
    assert text_va + allocation_call == text_va + 8

    cursor = emit(0x100, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 10 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 18 30 40 00")
    cursor = emit_call(cursor, 0x160)
    cursor = emit(cursor, "59 59 29 1d 10 30 40 00")
    emit(cursor, "a1 14 30 40 00 01 1d 14 30 40 00 5b c3")
    emit(0x160, "c3")
    emit(0x180, "c3")

    return pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe_mod.Section(".data", data_va, 0x200, 0x200, 0x200, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )


def test_callee_argument_byte_effect_follows_fresh_string_copy_source():
    image = fresh_string_copy_argument_effect_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset())

    assert result is not None
    assert result[0] == frozenset({0x1E})


def test_callee_argument_byte_effect_rejects_unknown_string_copy_source():
    image = fresh_string_copy_argument_effect_image(unknown_source_write=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset()) is None


def test_callee_argument_effect_discards_dead_scalarized_pointer_alias():
    image = fresh_string_copy_argument_effect_image(stale_pointer_scalarization=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset())

    assert result is not None
    assert result[0] == frozenset({0x1E})


def test_callee_argument_effect_rejects_used_scalarized_pointer_alias():
    image = fresh_string_copy_argument_effect_image(use_scalarized_pointer=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset()) is None


def test_callee_argument_effect_allows_contained_pointer_publication():
    image = fresh_string_copy_argument_effect_image(contained_pointer_publication=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset())

    assert result is not None
    assert result[0] == frozenset({0x1E})


def test_callee_argument_effect_rejects_escaped_pointer_container():
    image = fresh_string_copy_argument_effect_image(escape_pointer_container=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._callee_argument_byte_effect(image.entrypoint, 0, (0,), frozenset()) is None


def exact_scalar_argument_image():
    """One exact scalar caller plus one unrelated unknown caller."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(b"\x90" * 0x50)

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        data[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        data[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        data[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = emit(0, "6a 29")
    exact_call = text_va + cursor
    cursor = emit_call(cursor, 0x40)
    cursor = emit(cursor, "59")
    cursor = emit_call(cursor, 0x20)
    emit(cursor, "c3")

    cursor = emit(0x20, "52")
    unknown_call = text_va + cursor
    cursor = emit_call(cursor, 0x40)
    emit(cursor, "59 c3")

    emit(0x40, "8b 44 24 04 c3")
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, len(data), len(data), 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    return image, exact_call, unknown_call


def test_scalar_argument_values_use_exact_call_context():
    image, exact_call, _unknown_call = exact_scalar_argument_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    context = (image.entrypoint + 0x40, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_values(image.entrypoint + 0x40, 0, frozenset())
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_scalar_argument_values_reject_unknown_exact_call_context():
    image, _exact_call, unknown_call = exact_scalar_argument_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    context = (
        image.entrypoint + 0x40,
        unknown_call,
        image.entrypoint + 0x20,
    )
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_values(image.entrypoint + 0x40, 0, frozenset())
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def copied_before_initialized_fresh_allocation_image(
    *,
    unknown_fresh_write=False,
    mutate_argument_after_copy=False,
):
    """Join one exact argument with a fresh pointer copied before its write."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data_va = 0x00403000
    data = bytearray(0x400)
    text = memoryview(data)[:0x200]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    def patch_short_branch(branch_offset, target_offset):
        displacement = target_offset - (branch_offset + 2)
        assert -0x80 <= displacement <= 0x7F
        text[branch_offset + 1] = displacement & 0xFF

    cursor = emit(0, "83 ec 08 c6 04 24 29 8d 04 24 50")
    exact_call = text_va + cursor
    cursor = emit_call(cursor, 0x40)
    emit(cursor, "83 c4 0c c3")

    cursor = emit(0x40, "56 85 c9")
    argument_branch = cursor
    cursor = emit(cursor, "74 00 6a 1a")
    cursor = emit_call(cursor, 0x140)
    cursor = emit(cursor, "89 c6 59 85 f6")
    failure_branch = cursor
    cursor = emit(
        cursor,
        "74 00 88 16" if unknown_fresh_write else "74 00 c6 06 35",
    )
    join_branch = cursor
    cursor = emit(cursor, "eb 00")
    argument_arm = cursor
    cursor = emit(cursor, "8b 74 24 08")
    if mutate_argument_after_copy:
        cursor = emit(cursor, "c6 06 2a")
    join_address = text_va + cursor
    cursor = emit(cursor, "89 f0 5e c3")
    failure = cursor
    emit(cursor, "eb fe")
    patch_short_branch(argument_branch, argument_arm)
    patch_short_branch(join_branch, join_address - text_va)
    patch_short_branch(failure_branch, failure)

    cursor = emit(0x140, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 10 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 18 30 40 00")
    cursor = emit_call(cursor, 0x1A0)
    cursor = emit(cursor, "59 59 29 1d 10 30 40 00")
    emit(cursor, "a1 14 30 40 00 01 1d 14 30 40 00 5b c3")
    emit(0x1A0, "c3")

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe_mod.Section(".data", data_va, 0x200, 0x200, 0x200, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, exact_call, join_address


def test_object_value_tracks_fresh_pointer_copied_before_initialization():
    image, exact_call, join_address = copied_before_initialized_fresh_allocation_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29, 0x35})


def test_object_value_rejects_unknown_write_after_fresh_pointer_copy():
    image, exact_call, join_address = copied_before_initialized_fresh_allocation_image(unknown_fresh_write=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_object_value_includes_mutation_after_argument_pointer_copy():
    image, exact_call, join_address = copied_before_initialized_fresh_allocation_image(mutate_argument_after_copy=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x2A, 0x35})


def redefined_argument_pointer_image(
    *,
    unknown_write_before_split=False,
    preserve_argument_arm=False,
    null_replacement_arm=False,
):
    """Join a mutated argument with a fresh replacement pointer."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data_va = 0x00403000
    data = bytearray(0x400)
    text = memoryview(data)[:0x200]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    def patch_short_branch(branch_offset, target_offset):
        displacement = target_offset - (branch_offset + 2)
        assert -0x80 <= displacement <= 0x7F
        text[branch_offset + 1] = displacement & 0xFF

    cursor = emit(0, "83 ec 08 c6 04 24 29 8d 04 24 50")
    exact_call = text_va + cursor
    cursor = emit_call(cursor, 0x40)
    emit(cursor, "83 c4 0c c3")

    cursor = emit(0x40, "56 8b 74 24 08")
    if unknown_write_before_split:
        cursor = emit(cursor, "88 0e")
    cursor = emit(cursor, "85 c9")
    replacement_branch = cursor
    cursor = emit(cursor, "74 00")
    if not preserve_argument_arm:
        cursor = emit(cursor, "c6 06 2a")
    join_branch = cursor
    cursor = emit(cursor, "eb 00")
    replacement_arm = cursor
    if null_replacement_arm:
        cursor = emit(cursor, "31 f6")
    else:
        cursor = emit(cursor, "6a 04 56")
        cursor = emit_call(cursor, 0x100)
        cursor = emit(cursor, "89 c6 59 59")
    join_address = text_va + cursor
    emit(cursor, "89 f0 5e c3")
    patch_short_branch(replacement_branch, replacement_arm)
    patch_short_branch(join_branch, join_address - text_va)

    cursor = emit(0x100, "53 8b 54 24 08 88 0a 6a 1a")
    cursor = emit_call(cursor, 0x140)
    cursor = emit(cursor, "89 c3 59 85 db")
    failure_branch = cursor
    cursor = emit(cursor, "74 00 c6 03 35 89 d8 5b c3")
    failure = cursor
    emit(cursor, "eb fe")
    patch_short_branch(failure_branch, failure)

    cursor = emit(0x140, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 10 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 18 30 40 00")
    cursor = emit_call(cursor, 0x1A0)
    cursor = emit(cursor, "59 59 29 1d 10 30 40 00")
    emit(cursor, "a1 14 30 40 00 01 1d 14 30 40 00 5b c3")
    emit(0x1A0, "c3")

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe_mod.Section(".data", data_va, 0x200, 0x200, 0x200, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, exact_call, join_address


def redefined_argument_loop_image(*, redefine_before_backedge=True):
    """Loop after an unknown write, optionally cutting the old pointer."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x200)
    text = memoryview(data)

    text[0:0x0B] = bytes.fromhex("83 ec 08 c6 04 24 29 8d 04 24 50")
    exact_call = text_va + 0x0B
    text[0x0B] = 0xE8
    text[0x0C:0x10] = (text_va + 0x40 - (text_va + 0x10)).to_bytes(4, "little", signed=True)
    text[0x10:0x14] = bytes.fromhex("83 c4 0c c3")

    cursor = 0x40

    def emit(encoded):
        nonlocal cursor
        encoded = bytes.fromhex(encoded)
        text[cursor : cursor + len(encoded)] = encoded
        cursor += len(encoded)

    emit("56 8b 74 24 08")
    loop_address = cursor
    emit("85 c9 74 00 88 16")
    observation_branch = loop_address + 2
    redefinition_address = None
    if redefine_before_backedge:
        redefinition_address = text_va + cursor
        emit("31 f6")
    backedge = cursor
    emit("eb 00")
    observation_address = text_va + cursor
    emit("89 f0 5e c3")
    text[observation_branch + 1] = cursor - 4 - (observation_branch + 2)
    text[backedge + 1] = (loop_address - (backedge + 2)) & 0xFF

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, exact_call, observation_address, redefinition_address


def exact_immediate_object_argument_image(value):
    """Return one exact immediate pointer argument unchanged."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x100)
    text = memoryview(data)
    text[0:2] = bytes((0x6A, value))
    exact_call = text_va + 2
    text[2] = 0xE8
    text[3:7] = (text_va + 0x40 - (text_va + 7)).to_bytes(4, "little", signed=True)
    text[7:11] = bytes.fromhex("83 c4 04 c3")
    text[0x40:0x45] = bytes.fromhex("8b 44 24 04 c3")
    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, 0x100, 0x100, 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x100),),
    )
    return image, exact_call


def conditional_nested_argument_pointer_image(*, mutation=None):
    """Conditionally replace an argument's nested pointer before return."""
    from tools.mwcc_retro import pe as pe_mod

    assert mutation in {None, "partial", "unknown"}
    text_va = 0x00401000
    data = bytearray(0x200)
    text = memoryview(data)

    cursor = 0

    def emit(encoded):
        nonlocal cursor
        encoded = bytes.fromhex(encoded)
        text[cursor : cursor + len(encoded)] = encoded
        cursor += len(encoded)

    emit("83 ec 20 c6 04 24 29 c6 44 24 04 35")
    emit("8d 04 24 89 44 24 12 8d 54 24 04 52 8d 44 24 0c 50")
    exact_call = text_va + cursor
    text[cursor] = 0xE8
    text[cursor + 1 : cursor + 5] = (text_va + 0x80 - (text_va + cursor + 5)).to_bytes(4, "little", signed=True)
    cursor += 5
    emit("83 c4 08 83 c4 20 c3")

    cursor = 0x80
    emit("56 8b 74 24 08 85 c9 74 00")
    preserve_branch = cursor - 2
    if mutation == "unknown":
        emit("89 d0 89 46 0a")
    elif mutation == "partial":
        emit("8b 44 24 0c 66 89 46 0a")
    else:
        emit("8b 44 24 0c 89 46 0a")
    observation_address = text_va + cursor
    emit("89 f0 5e c3")
    text[preserve_branch + 1] = cursor - 4 - (preserve_branch + 2)

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, exact_call, observation_address


def successful_object_outparam_image(
    *,
    mutation=None,
    nested=False,
    normalize_result=False,
):
    """Write an object pointer only on a caller-guarded success return."""
    from tools.mwcc_retro import pe as pe_mod

    assert mutation in {None, "unknown", "no-guard", "nested-empty"}
    assert not (nested or normalize_result) or mutation is None
    text_va = 0x00401000
    data = bytearray(0x200)
    text = memoryview(data)

    cursor = 0

    def emit(encoded):
        nonlocal cursor
        encoded = bytes.fromhex(encoded)
        text[cursor : cursor + len(encoded)] = encoded
        cursor += len(encoded)

    if nested:
        emit("83 ec 30 c6 44 24 08 29")
        emit("c6 44 24 10 44 8d 54 24 08 8d 4c 24 10")
        emit("89 54 24 1a")
        emit("8d 44 24 04 6a 01 51 50")
    else:
        emit("83 ec 20 c6 44 24 08 29")
        emit("8d 4c 24 08 8d 44 24 04 52 51 50")
    exact_call = text_va + cursor
    text[cursor] = 0xE8
    text[cursor + 1 : cursor + 5] = (text_va + 0x80 - (text_va + cursor + 5)).to_bytes(4, "little", signed=True)
    cursor += 5
    emit("83 c4 0c")
    guard_branch = None
    if mutation != "no-guard":
        emit("84 c0 74 00")
        guard_branch = cursor - 2
    observation_address = text_va + cursor
    emit(f"8b 44 24 04 83 c4 {0x30 if nested else 0x20:02x} c3")
    if mutation != "no-guard":
        failure = cursor
        emit(f"31 c0 83 c4 {0x30 if nested else 0x20:02x} c3")
        assert guard_branch is not None
        text[guard_branch + 1] = failure - (guard_branch + 2)

    cursor = 0x80
    emit("8b 44 24 0c 85 c0 74 00")
    failure_branch = cursor - 2
    emit("8b 4c 24 04")
    if mutation == "nested-empty":
        emit("51")
        text[cursor] = 0xE8
        text[cursor + 1 : cursor + 5] = (text_va + 0xC0 - (text_va + cursor + 5)).to_bytes(4, "little", signed=True)
        cursor += 5
        emit("83 c4 04 8b 4c 24 04")
    if mutation == "unknown":
        emit("89 01")
    else:
        emit("8b 54 24 08 89 11")
    if normalize_result:
        emit("8b 01 50")
        text[cursor] = 0xE8
        text[cursor + 1 : cursor + 5] = (text_va + 0xC0 - (text_va + cursor + 5)).to_bytes(4, "little", signed=True)
        cursor += 5
        emit("59 8b 4c 24 04 89 01")
    emit("b0 01 c3")
    failure = cursor
    emit("31 c0 c3")
    text[failure_branch + 1] = failure - (failure_branch + 2)

    if mutation == "nested-empty":
        cursor = 0xC0
        emit("8b 44 24 04 85 d2 74 06 c7 00 00 00 00 00 c3")
    elif normalize_result:
        cursor = 0xC0
        emit("8b 44 24 04 c3")

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, exact_call, observation_address


def return_byte_epilogue_image(*, branch_bypasses_zero=False):
    """Return through a retail-style partial-AL zero epilogue."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = (
        bytes.fromhex("85 c9 74 09 8b 44 24 04 30 c0 83 c4 10 5b c3")
        if branch_bypasses_zero
        else bytes.fromhex("8b 44 24 04 30 c0 83 c4 10 5b c3")
    )
    return pe_mod.Image(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )


def superseded_outparam_stack_slot_image(*, branch_bypasses_writer=False):
    """Overwrite an unknown outparam slot before its object is observed."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytearray(0x100)
    text = memoryview(data)
    cursor = 0

    def emit(encoded):
        nonlocal cursor
        encoded = bytes.fromhex(encoded)
        text[cursor : cursor + len(encoded)] = encoded
        cursor += len(encoded)

    emit("83 ec 20 8d 44 24 04 50")
    text[cursor] = 0xE8
    text[cursor + 1 : cursor + 5] = (text_va + 0x80 - (text_va + cursor + 5)).to_bytes(4, "little", signed=True)
    cursor += 5
    emit("83 c4 04 c6 44 24 08 29")
    branch = None
    if branch_bypasses_writer:
        emit("85 c9 74 00")
        branch = cursor - 2
    emit("8d 44 24 08 89 44 24 04")
    observation = text_va + cursor
    emit("8b 44 24 04 83 c4 20 c3")
    if branch is not None:
        text[branch + 1] = (observation - text_va) - (branch + 2)

    cursor = 0x80
    emit("8b 44 24 04 89 10 c3")

    return (
        pe_mod.Image(
            data=bytes(data),
            sha256=hashlib.sha256(data).hexdigest(),
            machine=0x14C,
            optional_magic=0x10B,
            image_base=0x00400000,
            size_of_headers=0,
            entrypoint=text_va,
            directories=(),
            sections=(
                pe_mod.Section(
                    ".text",
                    text_va,
                    0,
                    len(data),
                    len(data),
                    0x60000020,
                ),
            ),
            imports=(),
            exports=(),
            relocations=(),
            executable_ranges=((text_va, text_va + len(data)),),
        ),
        observation,
    )


def test_object_value_ignores_argument_effect_on_redefined_pointer_arm():
    image, exact_call, join_address = redefined_argument_pointer_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x2A, 0x35})


def test_object_value_rejects_unknown_effect_before_pointer_redefinition():
    image, exact_call, join_address = redefined_argument_pointer_image(unknown_write_before_split=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_object_value_preserves_argument_on_non_redefined_arm():
    image, exact_call, join_address = redefined_argument_pointer_image(preserve_argument_arm=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29, 0x35})


def test_object_value_treats_null_pointer_definition_as_empty_arm():
    image, exact_call, join_address = redefined_argument_pointer_image(null_replacement_arm=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            join_address,
            "esi",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x2A})
    assert "optional-empty-association" in result[1]


def test_object_value_excludes_a_redefinition_before_a_loop_backedge(monkeypatch):
    image, exact_call, observation, redefinition = redefined_argument_loop_image()
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    original_preservation = recovery._function_argument_preserves_field_before

    def require_redefinition_cut(*args, **kwargs):
        assert kwargs.get("excluded_addresses") == frozenset({redefinition})
        return original_preservation(*args, **kwargs)

    monkeypatch.setattr(
        recovery,
        "_function_argument_preserves_field_before",
        require_redefinition_cut,
    )
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_object_byte_values_before(
            observation,
            callee,
            0,
            (0,),
            frozenset(),
            excluded_addresses=frozenset({redefinition}),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_object_value_rejects_unknown_loop_write_without_redefinition():
    image, exact_call, observation, _redefinition = redefined_argument_loop_image(redefine_before_backedge=False)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_object_byte_values_before(
            observation,
            callee,
            0,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_object_value_treats_exact_null_argument_as_empty_association():
    image, exact_call = exact_immediate_object_argument_image(0)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            callee + 4,
            "eax",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset()
    assert "optional-empty-association" in result[1]


def test_callee_effect_flags_ignore_nested_provenance_flags():
    detail = (
        "callee=0x401080;argument=3;exact-origins;"
        "optional-empty-association;"
        "callee=0x401100;call=0x401040;"
        "callee=0x401100;argument=0;optional-preserve;writer=0x401120"
    )

    assert not _DirectCfgRecovery._callee_effect_has_flag(detail, "optional-preserve")
    assert _DirectCfgRecovery._callee_effect_has_flag(detail, "optional-empty-association")
    assert _DirectCfgRecovery._callee_effect_has_flag(
        detail.replace("exact-origins;", "exact-origins;optional-preserve;"),
        "optional-preserve",
    )
    assert not _DirectCfgRecovery._object_result_has_flag(
        f"callee-return=0x401060;{detail}",
        "optional-preserve",
    )


def test_object_value_rejects_nonnull_immediate_object_argument():
    image, exact_call = exact_immediate_object_argument_image(1)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            callee + 4,
            "eax",
            callee,
            (0,),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_argument_effect_combines_finite_nested_pointer_replacement():
    image, exact_call, observation = conditional_nested_argument_pointer_image()
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    callee = image.entrypoint + 0x80
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "esi",
            callee,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29, 0x35})


@pytest.mark.parametrize("mutation", ["partial", "unknown"])
def test_argument_effect_rejects_open_nested_pointer_replacement(mutation):
    image, exact_call, observation = conditional_nested_argument_pointer_image(mutation=mutation)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    callee = image.entrypoint + 0x80
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_object_byte_register_values_before(
            observation,
            "esi",
            callee,
            (10, 0),
            frozenset(),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def test_guarded_object_outparam_propagates_finite_pointee_byte():
    image, _exact_call, observation = successful_object_outparam_image()
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        observation + 4,
        "eax",
        image.entrypoint,
        (0,),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_guarded_object_outparam_propagates_nested_pointee_through_normalizer():
    image, _exact_call, observation = successful_object_outparam_image(
        nested=True,
        normalize_result=True,
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        observation + 4,
        "eax",
        image.entrypoint,
        (10, 0),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x29})


@pytest.mark.parametrize(
    ("root_optional", "expected_values"),
    [(False, frozenset({0x29})), (True, None)],
)
def test_nested_optional_empty_does_not_make_loaded_root_optional(
    monkeypatch,
    root_optional,
    expected_values,
):
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data = bytes.fromhex("8b 03 c3")
    image = pe_mod.Image(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(
                ".text",
                text_va,
                0,
                len(data),
                len(data),
                0x60000020,
            ),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + len(data)),),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original = recovery._finite_object_byte_register_values_before

    def model_parent_path(
        address,
        register_family,
        function_entry,
        field_path,
        visited,
    ):
        if address == text_va and register_family == "ebx":
            if field_path == (0, 10, 0):
                return (
                    frozenset({0x29}),
                    "optional-empty-association;nested-child",
                )
            if field_path == (0, 0):
                detail = "optional-empty-association;root-object" if root_optional else "finite-root-byte"
                return frozenset({0x44}), detail
        return original(
            address,
            register_family,
            function_entry,
            field_path,
            visited,
        )

    monkeypatch.setattr(
        recovery,
        "_finite_object_byte_register_values_before",
        model_parent_path,
    )

    result = recovery._finite_object_byte_register_values_before_uncached(
        text_va + 2,
        "eax",
        text_va,
        (10, 0),
        frozenset(),
    )

    if expected_values is None:
        assert result is None
    else:
        assert result is not None
        assert result[0] == expected_values
        assert "loaded-root-nonnull" in result[1]


def test_guarded_object_outparam_uses_exact_origins_when_state_is_open(
    monkeypatch,
):
    image, _exact_call, observation = successful_object_outparam_image()
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    original = recovery._relative_pointer_states
    callee = image.entrypoint + 0x80

    def open_callee_state(function_entry, **kwargs):
        if function_entry == callee and kwargs.get("argument_index") == 0:
            return None
        return original(function_entry, **kwargs)

    monkeypatch.setattr(recovery, "_relative_pointer_states", open_callee_state)

    result = recovery._finite_object_byte_register_values_before(
        observation + 4,
        "eax",
        image.entrypoint,
        (0,),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_guarded_object_outparam_ignores_overwritten_optional_empty():
    image, _exact_call, observation = successful_object_outparam_image(mutation="nested-empty")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        observation + 4,
        "eax",
        image.entrypoint,
        (0,),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_return_byte_constant_reads_partial_al_zero_in_same_block():
    image = return_byte_epilogue_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._return_byte_constant(
            image.entrypoint + len(image.data) - 1,
            image.entrypoint,
        )
        == 0
    )


def test_return_byte_constant_rejects_branch_bypassing_partial_al_zero():
    image = return_byte_epilogue_image(branch_bypasses_zero=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._return_byte_constant(
            image.entrypoint + len(image.data) - 1,
            image.entrypoint,
        )
        is None
    )


def test_stack_slot_pointer_ignores_superseded_unknown_outparam():
    image, observation = superseded_outparam_stack_slot_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        observation + 4,
        "eax",
        image.entrypoint,
        (0,),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_stack_slot_pointer_rejects_outparam_bypassing_exact_writer():
    image, observation = superseded_outparam_stack_slot_image(branch_bypasses_writer=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._finite_object_byte_register_values_before(
            observation + 4,
            "eax",
            image.entrypoint,
            (0,),
            frozenset(),
        )
        is None
    )


@pytest.mark.parametrize("mutation", ["unknown", "no-guard"])
def test_object_outparam_rejects_open_success_image(mutation):
    image, _exact_call, observation = successful_object_outparam_image(mutation=mutation)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        observation + 4,
        "eax",
        image.entrypoint,
        (0,),
        frozenset(),
    )

    assert result is None


def test_argument_object_lineage_allows_a_distinct_exact_invocation():
    image, exact_call, _join_address = redefined_argument_pointer_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_object_byte_values_before(
            callee + 5,
            callee,
            0,
            (0,),
            frozenset({(callee, "argument-object-lineage:0")}),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is not None
    assert result[0] == frozenset({0x29})


def test_argument_object_lineage_rejects_the_same_exact_invocation_cycle():
    image, exact_call, _join_address = redefined_argument_pointer_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    callee = image.entrypoint + 0x40
    context = (callee, exact_call, image.entrypoint)
    recovery.producer_exact_call_contexts.append(context)
    try:
        result = recovery._finite_argument_object_byte_values_before(
            callee + 5,
            callee,
            0,
            (0,),
            frozenset(
                {
                    (
                        callee,
                        f"argument-object-lineage:0:call={exact_call:#x}:caller={image.entrypoint:#x}",
                    )
                }
            ),
        )
    finally:
        assert recovery.producer_exact_call_contexts.pop() == context

    assert result is None


def fresh_nested_return_allocation_image(
    *,
    unknown_inner_write=False,
    unrelated_return_pointer_math=False,
    dead_partial_outer_eax=False,
    live_partial_outer_eax=False,
    empty_nested_association=False,
):
    """Return a guarded fresh object pointing to a guarded fresh object."""
    from tools.mwcc_retro import pe as pe_mod

    text_va = 0x00401000
    data_va = 0x00403000
    data = bytearray(0x400)
    text = memoryview(data)[:0x200]

    def emit(offset, encoded):
        encoded = bytes.fromhex(encoded)
        text[offset : offset + len(encoded)] = encoded
        return offset + len(encoded)

    def emit_call(offset, target_offset):
        text[offset] = 0xE8
        displacement = (text_va + target_offset) - (text_va + offset + 5)
        text[offset + 1 : offset + 5] = displacement.to_bytes(4, "little", signed=True)
        return offset + 5

    cursor = emit(0, "53 56 6a 1a")
    cursor = emit_call(cursor, 0x100)
    cursor = emit(cursor, "89 c6 59 85 f6")
    outer_failure_branch = cursor
    cursor = emit(cursor, "74 00")
    inner_failure_branch = None
    if empty_nested_association:
        cursor = emit(cursor, "6a 1a 56")
        cursor = emit_call(cursor, 0x180)
        cursor = emit(cursor, "59 59 89 f0 5e 5b")
        return_address = text_va + cursor
        cursor = emit(cursor, "c3")
    else:
        if dead_partial_outer_eax or live_partial_outer_eax:
            cursor = emit(cursor, "88 c8")
        if live_partial_outer_eax:
            cursor = emit(cursor, "c6 00 7f")
        unrelated_return_branch = None
        if unrelated_return_pointer_math:
            cursor = emit(cursor, "85 c9 75 00")
            unrelated_return_branch = cursor - 2
        cursor = emit(cursor, "6a 1a")
        cursor = emit_call(cursor, 0x100)
        cursor = emit(cursor, "89 c3 59 85 db")
        inner_failure_branch = cursor
        cursor = emit(cursor, "74 00")
        cursor = emit(cursor, "88 13" if unknown_inner_write else "c6 03 32")
        cursor = emit(cursor, "89 5e 0a 89 f0 5e 5b")
        return_address = text_va + cursor
        cursor = emit(cursor, "c3")
        if unrelated_return_branch is not None:
            unrelated_return = cursor
            cursor = emit(cursor, "01 ce 89 f0 5e 5b c3")
            text[unrelated_return_branch + 1] = unrelated_return - (unrelated_return_branch + 2)
    failure = cursor
    emit(cursor, "eb fe")
    text[outer_failure_branch + 1] = failure - (outer_failure_branch + 2)
    if inner_failure_branch is not None:
        text[inner_failure_branch + 1] = failure - (inner_failure_branch + 2)

    # Retail-shaped fixed bump allocator and its grow helper.
    cursor = emit(0x100, "53 8b 5c 24 08 81 e3 f8 ff ff ff 83 c3 08")
    cursor = emit(cursor, "39 1d 10 30 40 00 7d 0d 53")
    cursor = emit(cursor, "68 18 30 40 00")
    cursor = emit_call(cursor, 0x160)
    cursor = emit(cursor, "59 59 29 1d 10 30 40 00")
    emit(cursor, "a1 14 30 40 00 01 1d 14 30 40 00 5b c3")
    emit(0x160, "c3")
    emit(0x180, "31 c0 57 8b 4c 24 0c 8b 7c 24 08 f3 aa 5f c3")

    image = pe_mod.Image(
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        machine=0x14C,
        optional_magic=0x10B,
        image_base=0x00400000,
        size_of_headers=0,
        entrypoint=text_va,
        directories=(),
        sections=(
            pe_mod.Section(".text", text_va, 0, 0x200, 0x200, 0x60000020),
            pe_mod.Section(".data", data_va, 0x200, 0x200, 0x200, 0xC0000040),
        ),
        imports=(),
        exports=(),
        relocations=(),
        executable_ranges=((text_va, text_va + 0x200),),
    )
    return image, return_address


def test_byte_producer_follows_nested_fresh_return_allocations():
    image, return_address = fresh_nested_return_allocation_image()
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        return_address,
        "eax",
        image.entrypoint,
        (10, 0),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x32})


def test_fresh_allocation_reports_zeroed_nested_association_as_empty():
    image, return_address = fresh_nested_return_allocation_image(empty_nested_association=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        return_address,
        "eax",
        image.entrypoint,
        (10, 0),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset()
    assert "optional-empty-association" in result[1]


def test_fresh_allocation_proof_ignores_unrelated_return_arm():
    image, return_address = fresh_nested_return_allocation_image(unrelated_return_pointer_math=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        return_address,
        "eax",
        image.entrypoint,
        (10, 0),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x32})


def test_fresh_allocation_proof_discards_dead_partial_pointer_alias():
    image, return_address = fresh_nested_return_allocation_image(dead_partial_outer_eax=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    result = recovery._finite_object_byte_register_values_before(
        return_address,
        "eax",
        image.entrypoint,
        (10, 0),
        frozenset(),
    )

    assert result is not None
    assert result[0] == frozenset({0x32})


def test_fresh_allocation_proof_rejects_used_partial_pointer_alias():
    image, return_address = fresh_nested_return_allocation_image(live_partial_outer_eax=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._finite_object_byte_register_values_before(
            return_address,
            "eax",
            image.entrypoint,
            (10, 0),
            frozenset(),
        )
        is None
    )


def test_byte_producer_rejects_unknown_nested_fresh_return_writer():
    image, return_address = fresh_nested_return_allocation_image(unknown_inner_write=True)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert (
        recovery._finite_object_byte_register_values_before(
            return_address,
            "eax",
            image.entrypoint,
            (10, 0),
            frozenset(),
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation",
    ["corrupt-and-use", "unknown-helper-return"],
)
def test_byte_producer_rejects_unsafe_conditional_helper_return(mutation):
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        conditional_helper_return=mutation,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)


def test_forwarded_byte_domain_rejects_prior_finite_dispatch_clobber():
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(
        duplicate_consumer_dispatch=True,
        callback_clobbers_byte=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(transfer_address).guard_bound == 74
    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address + 0x12)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_producer_write",
        "alternate_unknown_caller",
        "unowned_raw_caller",
        "helper_clobbers_byte",
    ],
)
def test_forwarded_byte_producer_domain_rejects_open_provenance(mutation):
    image, _movzx_address, transfer_address = forwarded_movzx_dispatch_image(**{mutation: True})
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(transfer_address)
    assert any(
        row.address == transfer_address and row.kind == "computed-flow-blocker"
        for row in cfg.control_targets.unresolved
    )


def test_identical_byte_producer_sites_share_bounded_analysis():
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        duplicate_consumer_transfer=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(0x00401047).guard_bound == 74
    assert cfg.jump_table_at(0x0040104E).guard_bound == 74
    high_water = {row.limit_name: row.observed for row in cfg.high_water_marks}
    assert high_water["max_producer_domain_passes"] >= 1
    assert high_water["max_producer_domain_queries"] >= 2
    assert high_water["max_producer_domain_cache_hits"] >= 1
    assert high_water["max_producer_domain_evaluations"] < high_water["max_producer_domain_queries"]
    assert high_water["max_producer_domain_cache_entries"] >= 1
    assert high_water["max_producer_domain_dependency_rows"] >= 1


def test_identical_open_byte_producer_sites_reuse_unchanged_blocker():
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        unknown_producer_write=True,
        duplicate_consumer_transfer=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert {row.address for row in cfg.control_targets.unresolved if row.kind == "computed-flow-blocker"} >= {
        0x00401047,
        0x0040104E,
    }
    high_water = {row.limit_name: row.observed for row in cfg.high_water_marks}
    assert high_water["max_producer_domain_cache_hits"] >= 1
    assert high_water["max_producer_domain_evaluations"] < high_water["max_producer_domain_queries"]


def test_byte_producer_memo_invalidates_finite_result_for_new_root_writer():
    slot = 0x00402300
    base_image = movzx_dispatch_image(closed_producer_bound=74)
    data = bytearray(base_image.data)
    data[0xB0:0xB6] = bytes.fromhex("a3 00 23 40 00 c3")
    image = replace(
        base_image,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    memo = {}
    base_inventory = build_seed_inventory(image, ())
    finite_recovery = _DirectCfgRecovery(
        image,
        base_inventory,
        generous_limits(image),
        producer_domain_memo=memo,
    )
    finite_recovery.recover()

    def slot_domain(recovery):
        recovery._note_producer_global_slot_dependency(slot)
        return recovery._finite_global_slot_values(slot, frozenset())

    finite = finite_recovery._producer_domain_cached(
        ("producer-global-slot-test", slot),
        0x00401000,
        lambda: slot_domain(finite_recovery),
    )
    assert finite is not None
    assert finite[0] == frozenset({0})

    hidden_writer = SeedRecord(
        address=0x004010B0,
        category="audit-anchor",
        provenance_address=0x004010B0,
        provenance_bytes="a300234000",
        detail="newly reachable global writer",
        is_function=True,
    )
    blocked_recovery = _DirectCfgRecovery(
        image,
        type(base_inventory)((*base_inventory.records, hidden_writer)),
        generous_limits(image),
        producer_domain_memo=memo,
    )
    blocked_recovery.recover()
    blocked = blocked_recovery._producer_domain_cached(
        ("producer-global-slot-test", slot),
        0x00401000,
        lambda: slot_domain(blocked_recovery),
    )

    assert blocked is None
    assert blocked_recovery.high_water["max_producer_domain_invalidations"] >= 1


def test_byte_producer_memo_is_seed_order_independent():
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        duplicate_consumer_transfer=True,
    )
    inventory = build_seed_inventory(image, ())
    records = inventory.records
    forward = _DirectCfgRecovery(
        image,
        type(inventory)(records),
        generous_limits(image),
        producer_domain_memo={},
    ).recover()
    reverse = _DirectCfgRecovery(
        image,
        type(inventory)(tuple(reversed(records))),
        generous_limits(image),
        producer_domain_memo={},
    ).recover()

    assert canonical_jsonl_bytes(forward) == canonical_jsonl_bytes(reverse)


def test_byte_producer_query_cap_fails_closed():
    image = movzx_dispatch_image(closed_producer_bound=74)
    limits = replace(generous_limits(image), max_producer_domain_queries=1)

    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(image, build_seed_inventory(image, ()), limits)
    assert raised.value.limit_name == "max_producer_domain_queries"


@pytest.mark.parametrize(
    ("cap_name", "duplicate_consumer_transfer"),
    [
        ("max_producer_domain_passes", False),
        ("max_producer_domain_queries", False),
        ("max_producer_domain_evaluations", False),
        ("max_producer_domain_cache_hits", True),
        ("max_producer_domain_cache_entries", False),
        ("max_producer_domain_dependency_rows", False),
    ],
)
def test_byte_producer_analysis_caps_fail_closed(cap_name, duplicate_consumer_transfer):
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        duplicate_consumer_transfer=duplicate_consumer_transfer,
    )
    limits = replace(generous_limits(image), **{cap_name: 1})

    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(image, build_seed_inventory(image, ()), limits)
    assert raised.value.limit_name == cap_name


def test_byte_producer_proof_waits_for_quiescence_and_restarts_recovery(
    monkeypatch,
):
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        producer_proof_after_ordinary_round=True,
    )
    producer_attempts = []
    original = _DirectCfgRecovery._movzx_guard_for_index

    def counted_guard(
        recovery,
        transfer_address,
        index_register,
        *,
        producer_domain=False,
    ):
        if producer_domain:
            producer_attempts.append(
                (
                    transfer_address,
                    0x00401090 in recovery.instructions,
                    0x004010A0 in recovery.instructions,
                )
            )
        return original(
            recovery,
            transfer_address,
            index_register,
            producer_domain=producer_domain,
        )

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_movzx_guard_for_index",
        counted_guard,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert producer_attempts == [(0x00401047, True, True)]
    assert cfg.jump_table_at(0x0040102D).targets == (0x00401090,)
    assert cfg.jump_table_at(0x00401047).guard_bound == 74
    assert {row.address for row in cfg.instructions} >= {
        0x00401070,
        0x00401080,
        0x00401090,
        0x004010A0,
    }
    assert any(row.source == 0x00401070 and row.target == 0x00401080 and row.kind == "direct-call" for row in cfg.edges)


def test_validation_scans_run_once_after_target_discovery_restarts(
    monkeypatch,
):
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        producer_proof_after_ordinary_round=True,
    )
    taint_scans = []
    relocation_scans = []
    original_taint = _DirectCfgRecovery._reject_unsafe_initializer_taint
    original_relocations = _DirectCfgRecovery._classify_relocations

    def count_taint(recovery, blocks):
        taint_scans.append(frozenset(address for block in blocks for address in block.instruction_addresses))
        return original_taint(recovery, blocks)

    def count_relocations(recovery):
        relocation_scans.append(frozenset(recovery.instructions))
        return original_relocations(recovery)

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_reject_unsafe_initializer_taint",
        count_taint,
    )
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_classify_relocations",
        count_relocations,
    )

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert cfg.jump_table_at(0x00401047).guard_bound == 74
    assert len(taint_scans) == 1
    assert len(relocation_scans) == 1
    assert taint_scans[0] == frozenset(row.address for row in cfg.instructions)
    assert relocation_scans[0] == taint_scans[0]


@pytest.mark.parametrize(
    ("program_hex", "relocation_offset"),
    [
        ("68 20 10 40 00 c3", 1),
        ("c7 40 04 20 10 40 00 c3", 3),
    ],
)
def test_initializer_uses_preindexed_relocation_va(program_hex, relocation_offset):
    from tools.mwcc_retro import pe as pe_mod

    class CountingRelocations(tuple):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    base = movzx_dispatch_image()
    data = bytearray(base.data)
    program = bytes.fromhex(program_hex)
    data[: len(program)] = program
    data[0x20] = 0xC3
    relocations = CountingRelocations(
        (
            *base.relocations,
            pe_mod.Relocation(
                base.entrypoint + relocation_offset,
                3,
            ),
        )
    )
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        relocations=relocations,
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery._decode_from(image.entrypoint)
    decoded = recovery._owned_decoded(image.entrypoint)
    relocations.iterations = 0

    recovery._record_initializer(decoded, {})

    assert relocations.iterations == 0


def test_irrelevant_dynamic_store_defers_receiver_identity(monkeypatch):
    base = movzx_dispatch_image()
    data = bytearray(base.data)
    data[:8] = bytes.fromhex("c7 40 04 00 00 00 00 c3")
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    receiver_queries = []
    original = _DirectCfgRecovery._dynamic_field_receiver_identity

    def count_receiver(recovery, address, memory, function_entry, **kwargs):
        receiver_queries.append(address)
        return original(
            recovery,
            address,
            memory,
            function_entry,
            **kwargs,
        )

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_dynamic_field_receiver_identity",
        count_receiver,
    )

    recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert receiver_queries == []


def test_finite_control_query_is_reused_across_target_discovery_restart(
    monkeypatch,
):
    from tools.mwcc_retro import pe as pe_mod

    base = movzx_dispatch_image()
    data = bytearray(base.data)
    data[:8] = bytes.fromhex("b8 20 10 40 00 ff d0 c3")
    data[0x20] = 0xC3
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        relocations=(
            *base.relocations,
            pe_mod.Relocation(base.entrypoint + 1, 3),
        ),
    )
    evaluations = Counter()
    original = _DirectCfgRecovery._finite_operand_values_before

    def count_finite(recovery, address, *args, **kwargs):
        evaluations[address] += 1
        return original(recovery, address, *args, **kwargs)

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_finite_operand_values_before",
        count_finite,
    )

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    transfer = base.entrypoint + 5
    assert any(
        row.source == transfer
        and row.target == base.entrypoint + 0x20
        and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )
    assert evaluations[transfer] == 1


def test_finite_edge_only_growth_batches_within_one_outer_pass(monkeypatch):
    image, consumer, source, first_target, second_target = finite_incoming_edge_image()
    messages = []
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_producer_progress_message",
        lambda _recovery, message: messages.append(message),
    )

    cfg = recover_cfg(
        image,
        (image.entrypoint, source, first_target, second_target),
        generous_limits(image),
    )

    finite_edges = {(row.source, row.target) for row in cfg.control_targets.finite_internal_edges}
    assert finite_edges >= {
        (consumer + 4, first_target),
        (consumer + 4, second_target),
        (source + 10, consumer),
    }
    assert sum(message.startswith("ordinary closure finite-flow-start:") for message in messages) == 1


def test_later_finite_edge_revalidates_earlier_incoming_domain_in_phase(
    monkeypatch,
):
    image, consumer, source, first_target, second_target = finite_incoming_edge_image()
    evaluations = Counter()
    messages = []
    original = _DirectCfgRecovery._finite_operand_values_before

    def count_finite(recovery, address, *args, **kwargs):
        evaluations[address] += 1
        return original(recovery, address, *args, **kwargs)

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_finite_operand_values_before",
        count_finite,
    )
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_producer_progress_message",
        lambda _recovery, message: messages.append(message),
    )

    cfg = recover_cfg(
        image,
        (image.entrypoint, source, first_target, second_target),
        generous_limits(image),
    )

    assert evaluations[consumer + 4] == 2
    assert any(
        row.source == consumer + 4 and row.target == second_target for row in cfg.control_targets.finite_internal_edges
    )
    assert any(
        message.startswith(f"finite-control cache-invalidated: transfer={consumer + 4:#x};")
        and f"changed=function:{consumer:#x}" in message
        for message in messages
    )
    assert sum(message.startswith("ordinary closure finite-flow-start:") for message in messages) == 1


def test_finite_new_code_growth_restarts_outer_closure_immediately(
    monkeypatch,
):
    image, second_source, new_target, decoded_target = finite_new_code_image()
    messages = []
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_producer_progress_message",
        lambda _recovery, message: messages.append(message),
    )

    cfg = recover_cfg(
        image,
        (image.entrypoint, second_source, decoded_target),
        generous_limits(image),
    )

    assert any(row.address == new_target and row.mnemonic == "ret" for row in cfg.instructions)
    finite_starts = [message for message in messages if message.startswith("ordinary closure finite-flow-start:")]
    assert len(finite_starts) == 2
    first_restart = next(message for message in messages if message.startswith("ordinary closure finite-flow-restart:"))
    assert "pass=1" in first_restart
    assert "pending=1" in first_restart


def test_nonmonotone_finite_domain_with_retained_edge_fails_closed(
    monkeypatch,
):
    image, consumer, source, first_target, second_target = finite_incoming_edge_image()
    original = _DirectCfgRecovery._finite_operand_values_before
    evaluations = Counter()

    def change_domain(recovery, address, *args, **kwargs):
        if address != consumer + 4:
            return original(recovery, address, *args, **kwargs)
        evaluations[address] += 1
        recovery._note_producer_dependency(first_target)
        target = first_target if evaluations[address] == 1 else second_target
        return frozenset({target}), f"test-domain={target:#x}"

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_finite_operand_values_before",
        change_domain,
    )

    with pytest.raises(
        CfgRecoveryError,
        match="retained finite-control edge became unsound",
    ):
        recover_cfg(
            image,
            (image.entrypoint, source, first_target, second_target),
            generous_limits(image),
        )


def test_callback_hypotheses_run_once_after_code_closure(monkeypatch):
    from tools.mwcc_retro import pe as pe_mod

    base = movzx_dispatch_image()
    data = bytearray(base.data)
    data[:8] = bytes.fromhex("b8 20 10 40 00 ff d0 c3")
    data[0x20] = 0xC3
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        relocations=(
            *base.relocations,
            pe_mod.Relocation(base.entrypoint + 1, 3),
        ),
    )
    calls = []

    for method_name in (
        "_record_copied_descriptor_callback_tables",
        "_record_object_callback_tables",
    ):
        original = getattr(_DirectCfgRecovery, method_name)

        def record_phase(recovery, *, _name=method_name, _original=original):
            before_pending = tuple(recovery.pending)
            before_block_starts = frozenset(recovery.block_starts)
            _original(recovery)
            calls.append(
                (
                    _name,
                    before_pending,
                    before_block_starts,
                    tuple(recovery.pending),
                    frozenset(recovery.block_starts),
                )
            )

        monkeypatch.setattr(_DirectCfgRecovery, method_name, record_phase)

    recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    phase_names = [row[0] for row in calls]
    assert phase_names.count("_record_copied_descriptor_callback_tables") >= 1
    assert phase_names.count("_record_object_callback_tables") == 1
    assert phase_names[-1] == "_record_object_callback_tables"
    assert all(not before_pending for _, before_pending, *_ in calls)
    assert all(
        before_pending == after_pending and before_block_starts == after_block_starts
        for (
            _,
            before_pending,
            before_block_starts,
            after_pending,
            after_block_starts,
        ) in calls
    )


def test_finite_control_waits_for_cheap_resolver_closure(monkeypatch):
    from tools.mwcc_retro import pe as pe_mod

    base = movzx_dispatch_image()
    data = bytearray(base.data)
    data[:15] = bytes.fromhex("b8 30 10 40 00 ff d0 b9 40 10 40 00 ff d1 c3")
    data[0x30] = 0xC3
    data[0x40] = 0xC3
    data[0x50] = 0xC3
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        relocations=(
            *base.relocations,
            pe_mod.Relocation(base.entrypoint + 1, 3),
            pe_mod.Relocation(base.entrypoint + 8, 3),
        ),
    )
    growth_complete = False
    finite_calls = []
    original_cheap = _DirectCfgRecovery._recover_global_slot_targets
    original_finite = _DirectCfgRecovery._recover_finite_value_target

    def grow_from_later_candidate(recovery, decoded, instruction, *, flow_kind):
        nonlocal growth_complete
        if instruction.address == base.entrypoint + 12 and not growth_complete:
            recovery._enqueue(base.entrypoint + 0x50, is_function=True)
            growth_complete = True
            return True
        return original_cheap(recovery, decoded, instruction, flow_kind=flow_kind)

    def record_finite(recovery, decoded, instruction, *, flow_kind):
        finite_calls.append((instruction.address, growth_complete, tuple(recovery.pending)))
        return original_finite(recovery, decoded, instruction, flow_kind=flow_kind)

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_recover_global_slot_targets",
        grow_from_later_candidate,
    )
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_recover_finite_value_target",
        record_finite,
    )

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert finite_calls
    assert all(grew and not pending for _address, grew, pending in finite_calls)
    assert {
        (row.source, row.target)
        for row in cfg.control_targets.finite_internal_edges
        if row.flow_kind == "indirect-call-finite-value"
    } >= {
        (base.entrypoint + 5, base.entrypoint + 0x30),
        (base.entrypoint + 12, base.entrypoint + 0x40),
    }
    assert base.entrypoint + 0x50 in {row.address for row in cfg.instructions}


def test_post_finite_resolvers_batch_without_mutating_finite_phase(
    monkeypatch,
):
    from tools.mwcc_retro import pe as pe_mod

    base = movzx_dispatch_image()
    data = bytearray(base.data)
    data[:15] = bytes.fromhex("b8 30 10 40 00 ff d0 b9 40 10 40 00 ff d1 c3")
    data[0x30] = 0xC3
    data[0x40] = 0xC3
    data[0x50] = 0xC3
    data[0x60] = 0xC3
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        relocations=(
            *base.relocations,
            pe_mod.Relocation(base.entrypoint + 1, 3),
            pe_mod.Relocation(base.entrypoint + 8, 3),
        ),
    )
    lower_mutated_this_pass = False
    finite_observed_late_mutation = False
    batched_second_growth = False
    grown_sources = set()
    original_scan = _DirectCfgRecovery._scan_owned_blocks
    original_lower = _DirectCfgRecovery._recover_sentinel_callback_table

    def reset_phase(recovery, blocks):
        nonlocal lower_mutated_this_pass
        lower_mutated_this_pass = False
        return original_scan(recovery, blocks)

    def reject_finite(recovery, decoded, instruction, *, flow_kind):
        nonlocal finite_observed_late_mutation
        finite_observed_late_mutation |= lower_mutated_this_pass
        return False

    def grow_post_finite(recovery, decoded, instruction, *, flow_kind):
        nonlocal lower_mutated_this_pass, batched_second_growth
        targets = {
            base.entrypoint + 5: base.entrypoint + 0x50,
            base.entrypoint + 12: base.entrypoint + 0x60,
        }
        target = targets.get(instruction.address)
        if target is not None and instruction.address not in grown_sources:
            if instruction.address == base.entrypoint + 12:
                batched_second_growth = bool(recovery.pending)
            grown_sources.add(instruction.address)
            recovery._enqueue(target, is_function=True)
            lower_mutated_this_pass = True
            return True
        return original_lower(recovery, decoded, instruction, flow_kind=flow_kind)

    monkeypatch.setattr(_DirectCfgRecovery, "_scan_owned_blocks", reset_phase)
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_recover_finite_value_target",
        reject_finite,
    )
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_recover_sentinel_callback_table",
        grow_post_finite,
    )

    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    assert not finite_observed_late_mutation
    assert batched_second_growth
    assert {base.entrypoint + 0x50, base.entrypoint + 0x60} <= {row.address for row in cfg.instructions}


def test_function_fingerprints_do_not_repeat_whole_image_sort_after_summary_revision(
    monkeypatch,
):
    image = movzx_dispatch_image(closed_producer_bound=74)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    entries = tuple(sorted(recovery.function_addresses))[:2]
    for entry in entries:
        recovery._producer_function_fingerprint(entry)

    whole_image_sorts = 0
    original_sorted = sorted

    def observe_sorted(iterable, *args, **kwargs):
        nonlocal whole_image_sorts
        if iterable is recovery.instructions:
            whole_image_sorts += 1
        return original_sorted(iterable, *args, **kwargs)

    monkeypatch.setattr("builtins.sorted", observe_sorted)
    recovery.dynamic_field_write_count += 1
    for entry in entries:
        recovery._producer_function_fingerprint(entry)

    assert whole_image_sorts == 0


def test_function_address_index_rebuilds_once_for_new_entry_and_instruction(
    monkeypatch,
):
    base = movzx_dispatch_image(closed_producer_bound=74)
    data = bytearray(base.data)
    data[0x80] = 0xC3
    image = replace(
        base,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    whole_image_sorts = 0
    original_sorted = sorted

    def observe_sorted(iterable, *args, **kwargs):
        nonlocal whole_image_sorts
        if iterable is recovery.instructions:
            whole_image_sorts += 1
        return original_sorted(iterable, *args, **kwargs)

    monkeypatch.setattr("builtins.sorted", observe_sorted)
    recovery._enqueue(base.entrypoint + 0x44, is_function=True)
    assert recovery._function_instruction_addresses(base.entrypoint + 0x40) == (base.entrypoint + 0x40,)
    assert recovery._function_instruction_addresses(base.entrypoint + 0x44) == (
        base.entrypoint + 0x44,
        base.entrypoint + 0x47,
        base.entrypoint + 0x4E,
    )
    assert whole_image_sorts == 1

    function_entry = base.entrypoint + 0x44
    following_entry = min(address for address in recovery.function_addresses if address > function_entry)
    ranges = (
        (function_entry, function_entry),
        (function_entry, function_entry + 1),
        (function_entry + 1, function_entry + 0xA),
        (function_entry + 3, function_entry + 0xA),
        (function_entry, following_entry),
        (function_entry - 0x100, following_entry + 0x100),
        (following_entry, following_entry + 0x100),
    )
    for start, stop in ranges:
        expected = tuple(
            address for address in recovery._function_instruction_addresses(function_entry) if start <= address < stop
        )
        assert recovery._function_instruction_addresses_between(function_entry, start, stop) == expected
    assert whole_image_sorts == 1

    recovery._enqueue(base.entrypoint + 0x80, is_function=True)
    recovery._decode_from(base.entrypoint + 0x80)
    assert recovery._function_instruction_addresses(base.entrypoint + 0x70) == (base.entrypoint + 0x70,)
    assert recovery._function_instruction_addresses(base.entrypoint + 0x80) == (base.entrypoint + 0x80,)
    assert whole_image_sorts == 2


def test_unknown_byte_producer_writer_keeps_movzx_table_blocked():
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        unknown_producer_write=True,
    )
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401047)
    assert any(
        row.address == 0x00401047 and row.kind == "computed-flow-blocker" and "index=75" in row.detail
        for row in cfg.control_targets.unresolved
    )


def test_byte_producer_value_75_keeps_movzx_table_blocked():
    image = movzx_dispatch_image(closed_producer_bound=75)
    cfg = recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )

    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401047)
    assert any(
        row.address == 0x00401047 and row.kind == "computed-flow-blocker" and "index=75" in row.detail
        for row in cfg.control_targets.unresolved
    )


def _write_rehashed_producer_certificate(path, mutate):
    payload = json.loads(path.read_bytes())
    mutate(payload)
    payload["certificate_sha256"] = _producer_certificate_digest(payload)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _rewrite_as_old_semantics_blocked_certificate(path):
    payload = json.loads(path.read_bytes())
    payload["query"]["analysis_semantics"] = "movzx-producer-analysis-v7"
    old_query_sha256 = hashlib.sha256(
        json.dumps(payload["query"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload["query_sha256"] = old_query_sha256
    payload["result"] = {
        "provenance": "producer-domain-analysis-returned-bottom",
        "status": "blocked",
        "values": [],
    }
    payload["certificate_sha256"] = _producer_certificate_digest(payload)
    old_path = path.with_name(f"{old_query_sha256}-{payload['dependency_sha256']}.json")
    old_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    if old_path != path:
        path.unlink()
    return old_path


def _complete_resumable_producer_cfg(image, inventory, limits, checkpoint_dir):
    while True:
        try:
            return recover_cfg(
                image,
                inventory,
                limits,
                producer_checkpoint_dir=checkpoint_dir,
                producer_query_budget=1,
            )
        except ProducerCheckpointIncomplete as exc:
            assert exc.completed_this_run == 1


def test_byte_producer_checkpoint_requires_durable_resume(tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    checkpoint_dir = tmp_path / "producer-checkpoints"
    progress = []

    with pytest.raises(ProducerCheckpointIncomplete) as raised:
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
            producer_progress_callback=progress.append,
        )

    assert raised.value.completed_this_run == 1
    assert raised.value.discovered_queries == 1
    query_progress = [row.split(":", 1)[0] for row in progress if row.startswith("producer query ")]
    assert query_progress == [
        "producer query evaluating",
        "producer query checkpointed",
    ]
    assert {
        "ordinary closure decode-start",
        "ordinary closure decode-complete",
        "ordinary closure block-scan-complete",
        "ordinary closure producer-phase-start",
    } <= {row.split(":", 1)[0] for row in progress}
    certificates = tuple(checkpoint_dir.glob("*.json"))
    assert len(certificates) == 1
    certificate = json.loads(certificates[0].read_bytes())
    assert certificate["compiler_sha256"] == image.sha256
    assert _MOVZX_PRODUCER_ANALYSIS_SEMANTICS == ("movzx-producer-analysis-v17")
    assert certificate["query"]["analysis_semantics"] == (_MOVZX_PRODUCER_ANALYSIS_SEMANTICS)
    assert certificate["query"]["movzx_address"] == 0x00401044
    assert certificate["result"] == {
        "provenance": certificate["result"]["provenance"],
        "status": "finite",
        "values": [0, 74],
    }

    resumed = recover_cfg(
        image,
        inventory,
        generous_limits(image),
        producer_checkpoint_dir=checkpoint_dir,
        producer_query_budget=1,
    )
    assert resumed.jump_table_at(0x00401047).guard_bound == 74


def test_byte_producer_checkpoint_does_not_discover_old_analysis_semantics(
    tmp_path,
):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    limits = generous_limits(image)
    checkpoint_dir = tmp_path / "producer-checkpoints"
    with pytest.raises(ProducerCheckpointIncomplete):
        recover_cfg(
            image,
            inventory,
            limits,
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    current_certificate = next(checkpoint_dir.glob("*.json"))
    old_certificate = _rewrite_as_old_semantics_blocked_certificate(current_certificate)

    with pytest.raises(ProducerCheckpointIncomplete) as raised:
        recover_cfg(
            image,
            inventory,
            limits,
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )

    assert raised.value.completed_this_run == 1
    certificates = tuple(checkpoint_dir.glob("*.json"))
    assert old_certificate in certificates
    assert len(certificates) == 2
    assert {json.loads(path.read_bytes())["result"]["status"] for path in certificates} == {"blocked", "finite"}


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda query: query.pop("analysis_semantics"), "query schema"),
        (
            lambda query: query.__setitem__("analysis_semantics", "movzx-producer-analysis-v7"),
            "analysis semantics",
        ),
    ],
)
def test_byte_producer_checkpoint_rejects_missing_or_wrong_analysis_semantics(tmp_path, mutate, error):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    checkpoint_dir = tmp_path / "producer-checkpoints"
    with pytest.raises(ProducerCheckpointIncomplete):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    certificate = next(checkpoint_dir.glob("*.json"))
    _write_rehashed_producer_certificate(certificate, lambda payload: mutate(payload["query"]))

    with pytest.raises(ProducerCertificateError, match=error):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )


def test_byte_producer_checkpoint_atomic_failure_restarts_cleanly(monkeypatch, tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    checkpoint_dir = tmp_path / "producer-checkpoints"
    real_replace = x86_cfg_module.os.replace

    def fail_certificate_replace(source, destination):
        if Path(destination).suffix == ".json":
            raise OSError("injected certificate replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(x86_cfg_module.os, "replace", fail_certificate_replace)
    with pytest.raises(OSError, match="injected certificate"):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    assert not tuple(checkpoint_dir.glob("*.json"))
    assert not tuple(checkpoint_dir.glob("*.tmp"))

    monkeypatch.setattr(x86_cfg_module.os, "replace", real_replace)
    resumed = _complete_resumable_producer_cfg(
        image,
        inventory,
        generous_limits(image),
        checkpoint_dir,
    )
    assert resumed.jump_table_at(0x00401047).guard_bound == 74


def test_byte_producer_checkpoint_rejects_tamper(tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    checkpoint_dir = tmp_path / "producer-checkpoints"
    with pytest.raises(ProducerCheckpointIncomplete):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    certificate = next(checkpoint_dir.glob("*.json"))
    payload = json.loads(certificate.read_bytes())
    payload["result"]["values"][-1] = 73
    certificate.write_text(json.dumps(payload))

    with pytest.raises(ProducerCertificateError, match="digest"):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )


def test_byte_producer_checkpoint_rejects_wrong_compiler_sha(tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    checkpoint_dir = tmp_path / "producer-checkpoints"
    with pytest.raises(ProducerCheckpointIncomplete):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    certificate = next(checkpoint_dir.glob("*.json"))
    _write_rehashed_producer_certificate(
        certificate,
        lambda payload: payload.__setitem__("compiler_sha256", "0" * 64),
    )

    with pytest.raises(ProducerCertificateError, match="compiler SHA"):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )


def test_byte_producer_checkpoint_rejects_partial_dependencies(tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    checkpoint_dir = tmp_path / "producer-checkpoints"
    with pytest.raises(ProducerCheckpointIncomplete):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    certificate = next(checkpoint_dir.glob("*.json"))

    def remove_dependencies(payload):
        payload["dependencies"] = []
        payload["dependency_count"] = 0
        payload["dependency_sha256"] = hashlib.sha256(b"[]").hexdigest()

    _write_rehashed_producer_certificate(certificate, remove_dependencies)

    with pytest.raises(ProducerCertificateError, match="root dependency"):
        recover_cfg(
            image,
            inventory,
            generous_limits(image),
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )


def test_forwarded_byte_producer_certificate_binds_transitive_callees(
    tmp_path,
):
    image, movzx_address, _transfer_address = forwarded_movzx_dispatch_image()
    inventory = build_seed_inventory(image, ())
    limits = generous_limits(image)
    checkpoint_dir = tmp_path / "producer-checkpoints"
    query = _MovzxProducerQuery(
        function_entry=0x00401080,
        movzx_address=movzx_address,
        movzx_bytes_hex="0fb618",
        destination_register="ebx",
        source_base_register="eax",
        field_path=(0,),
        source_width=1,
    )

    recovery = _DirectCfgRecovery(image, inventory, limits)
    recovery.recover()
    session = _ProducerCertificateSession(
        image_sha256=image.sha256,
        limits=limits,
        checkpoint_dir=checkpoint_dir,
        query_budget=1,
    )

    def compute_domain(target_recovery):
        return target_recovery._finite_object_byte_register_values_before(
            movzx_address,
            "eax",
            0x00401080,
            (0,),
            frozenset(),
        )

    result = session.evaluate(
        recovery=recovery,
        query=query,
        compute=lambda: compute_domain(recovery),
    )
    assert result is not None and result[0] == frozenset({0, 74})
    certificate_path = next(checkpoint_dir.glob("*.json"))
    certificate = json.loads(certificate_path.read_bytes())
    assert {row["identifier"] for row in certificate["dependencies"] if row["kind"] == "function"} == {
        0x00401000,
        0x00401050,
        0x00401080,
        0x004010C0,
        0x004010D0,
    }

    # A changed transitive helper fingerprint makes the durable certificate
    # stale even though the semantic MOVZX query itself is unchanged.
    stale_recovery = _DirectCfgRecovery(image, inventory, limits)
    stale_recovery.recover()
    helper_instruction = stale_recovery.instructions[0x004010D4]
    stale_recovery.instructions[0x004010D4] = replace(helper_instruction, bytes_hex="8b5007")
    stale_recovery.producer_function_fingerprint_cache.clear()
    stale_session = _ProducerCertificateSession(
        image_sha256=image.sha256,
        limits=limits,
        checkpoint_dir=checkpoint_dir,
        query_budget=0,
    )
    assert (
        stale_session.evaluate(
            recovery=stale_recovery,
            query=query,
            compute=lambda: compute_domain(stale_recovery),
        )
        is None
    )
    assert stale_session.query_states[query.sha256] == "pending"
    assert not stale_session.validated_query_ids


@pytest.mark.parametrize("callee_published_outer", [False, True])
def test_callee_stack_writer_certificate_binds_every_effect_function(tmp_path, callee_published_outer):
    image, movzx_address, _transfer_address, _mutator_call = callee_stack_object_writer_image(
        callee_published_outer=callee_published_outer
    )
    inventory = build_seed_inventory(image, ())
    limits = generous_limits(image)
    checkpoint_dir = tmp_path / "producer-checkpoints"
    recovery = _DirectCfgRecovery(image, inventory, limits)
    recovery.recover()
    session = _ProducerCertificateSession(
        image_sha256=image.sha256,
        limits=limits,
        checkpoint_dir=checkpoint_dir,
        query_budget=1,
    )
    query = _MovzxProducerQuery(
        function_entry=0x00401100,
        movzx_address=movzx_address,
        movzx_bytes_hex="0fb618",
        destination_register="ebx",
        source_base_register="eax",
        field_path=(0,),
        source_width=1,
    )

    result = session.evaluate(
        recovery=recovery,
        query=query,
        compute=lambda: (
            recovery._finite_object_byte_register_values_before(
                movzx_address,
                "eax",
                0x00401100,
                (0,),
                frozenset(),
            )
        ),
    )

    assert result is not None and result[0] == frozenset({0, 74})
    certificate = json.loads(next(checkpoint_dir.glob("*.json")).read_bytes())
    expected_dependencies = {
        0x00401000,
        0x00401100,
        0x00401140,
        0x00401160,
        0x00401180,
        0x00401200,
    }
    if callee_published_outer:
        expected_dependencies.update({0x00401260, 0x004012A0})
    assert {
        row["identifier"] for row in certificate["dependencies"] if row["kind"] == "function"
    } == expected_dependencies


def test_byte_producer_checkpoint_is_seed_order_independent(tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = _complete_resumable_producer_cfg(
        image,
        type(inventory)(inventory.records),
        generous_limits(image),
        first_dir,
    )
    second = _complete_resumable_producer_cfg(
        image,
        type(inventory)(tuple(reversed(inventory.records))),
        generous_limits(image),
        second_dir,
    )

    assert tuple(path.read_bytes() for path in first_dir.glob("*.json")) == tuple(
        path.read_bytes() for path in second_dir.glob("*.json")
    )
    assert first.instructions == second.instructions
    assert first.edges == second.edges
    assert first.jump_tables == second.jump_tables
    assert first.control_targets == second.control_targets


def test_byte_producer_checkpoint_cap_failure_publishes_nothing(tmp_path):
    image = movzx_dispatch_image(closed_producer_bound=74)
    limits = replace(generous_limits(image), max_producer_domain_evaluations=1)
    checkpoint_dir = tmp_path / "producer-checkpoints"

    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(
            image,
            build_seed_inventory(image, ()),
            limits,
            producer_checkpoint_dir=checkpoint_dir,
            producer_query_budget=1,
        )
    assert raised.value.limit_name == "max_producer_domain_evaluations"
    assert not tuple(checkpoint_dir.glob("*.json"))


def test_byte_producer_checkpoint_invalidates_changed_writer_to_blocked(
    tmp_path,
):
    image = movzx_dispatch_image(closed_producer_bound=74)
    inventory = build_seed_inventory(image, ())
    limits = generous_limits(image)
    checkpoint_dir = tmp_path / "producer-checkpoints"
    query = _MovzxProducerQuery(
        function_entry=0x00401000,
        movzx_address=0x00401044,
        movzx_bytes_hex="0fb618",
        destination_register="ebx",
        source_base_register="eax",
        field_path=(0,),
        source_width=1,
    )
    slot = 0x00402300

    finite_recovery = _DirectCfgRecovery(image, inventory, limits)
    finite_recovery.recover()
    finite_session = _ProducerCertificateSession(
        image_sha256=image.sha256,
        limits=limits,
        checkpoint_dir=checkpoint_dir,
        query_budget=1,
    )

    def finite_domain():
        finite_recovery._note_producer_global_slot_dependency(slot)
        return frozenset({0, 74}), "closed-global-writer-domain"

    assert finite_session.evaluate(
        recovery=finite_recovery,
        query=query,
        compute=finite_domain,
    ) == (frozenset({0, 74}), "closed-global-writer-domain")

    blocked_recovery = _DirectCfgRecovery(image, inventory, limits)
    blocked_recovery.recover()
    blocked_recovery.global_slot_writes[slot] = {
        _GlobalSlotWrite(
            instruction_address=0x00401013,
            value=None,
            provenance="new-unknown-writer",
        )
    }
    blocked_session = _ProducerCertificateSession(
        image_sha256=image.sha256,
        limits=limits,
        checkpoint_dir=checkpoint_dir,
        query_budget=1,
    )

    def blocked_domain():
        blocked_recovery._note_producer_global_slot_dependency(slot)
        return None

    assert (
        blocked_session.evaluate(
            recovery=blocked_recovery,
            query=query,
            compute=blocked_domain,
        )
        is None
    )
    assert blocked_session.completed_this_run == 1
    assert len(tuple(checkpoint_dir.glob("*.json"))) == 2
    results = {json.loads(path.read_bytes())["result"]["status"] for path in checkpoint_dir.glob("*.json")}
    assert results == {"finite", "blocked"}


def test_byte_producer_checkpoint_final_closure_matches_monolithic(tmp_path):
    image = movzx_dispatch_image(
        closed_producer_bound=74,
        duplicate_consumer_transfer=True,
        producer_proof_after_ordinary_round=True,
    )
    inventory = build_seed_inventory(image, ())
    baseline = recover_cfg(image, inventory, generous_limits(image))
    resumed = _complete_resumable_producer_cfg(
        image,
        inventory,
        generous_limits(image),
        tmp_path / "producer-checkpoints",
    )

    assert resumed.seed_inventory == baseline.seed_inventory
    assert resumed.instructions == baseline.instructions
    assert resumed.blocks == baseline.blocks
    assert resumed.edges == baseline.edges
    assert resumed.direct_calls == baseline.direct_calls
    assert resumed.jump_tables == baseline.jump_tables
    assert resumed.control_targets == baseline.control_targets
    assert resumed.data_regions == baseline.data_regions
    assert resumed.padding_regions == baseline.padding_regions
    assert resumed.function_entries == baseline.function_entries


def test_bounded_registrar_callers_prove_runtime_callback_table(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="registrar-table")
    table = cfg.jump_table_at(0x00401075)
    assert table.guard_operator == "registrar-capacity"
    assert table.guard_bound == 4
    assert table.index_min == table.index_max == 0
    assert table.targets == (0x00401090,)
    assert any(
        row.source == 0x00401075 and row.target == 0x00401090 and row.flow_kind == "indirect-call-registrar-table"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_zero_count_table_is_provisionally_unreachable(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="registrar-empty")
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401075]
    assert any(
        row.kind == "proven-unreachable-control" and row.address == 0x00401075 and "count=0x402300" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_empty_crt_sentinel_table_is_provisionally_unreachable(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="crt-empty-sentinel")
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x0040100C]
    assert any(
        row.kind == "proven-unreachable-control" and row.address == 0x0040100C and "empty .CRT sentinel" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_byte_return_summary_bounds_callback_table(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="byte-return-table")
    table = cfg.jump_table_at(0x00401008)
    assert table.guard_operator == "byte-return-summary"
    assert table.guard_address == 0x00401030
    assert table.guard_bound == 0xFF
    assert (table.index_min, table.index_max) == (0, 0xFF)
    assert set(table.targets) == {0x00401020, 0x00401060}
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401008]


def test_cdecl_argument_spill_reload_closes_callback_target(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-spill-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103C and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "argument=0" in edge.provenance
    assert "stack-argument=0" in edge.provenance
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x0040103C]


def test_cdecl_argument_is_recovered_from_entry_relative_esp(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-esp-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401030 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "stack-argument=0" in edge.provenance


def test_dominating_equal_guard_closes_callback_argument(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="guarded-equal-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401030 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090


def test_equal_guard_rejects_register_clobber_before_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="guarded-equal-clobber")
    assert any(row.address == 0x00401030 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_fixed_outparam_store_closes_stack_callback_value(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="outparam-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401014 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090


def test_conditional_outparam_store_remains_open(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="outparam-conditional-callback")
    assert any(row.address == 0x00401014 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_loader_zero_global_stack_context_closes_callback_field(tmp_path):
    image, call_address = global_stack_callback_image(tmp_path)
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == call_address and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401150
    assert "global-stack-context=0x402300" in edge.provenance
    assert "zero-fill=" in edge.provenance
    assert "saved-nested-context=" in edge.provenance


@pytest.mark.parametrize(
    "variant",
    ["unknown-field", "alternate-global-writer", "unknown-caller"],
)
def test_global_stack_context_requires_closed_writers_and_callers(tmp_path, variant):
    image, call_address = global_stack_callback_image(
        tmp_path,
        unknown_field_write=variant == "unknown-field",
        alternate_global_writer=variant == "alternate-global-writer",
        unknown_caller=variant == "unknown-caller",
    )
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert any(row.address == call_address and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)
    assert not any(
        row.source == call_address and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize("field_offset", (0x10, 0x18, 0x20, 0x24))
def test_nested_global_stack_publications_restore_every_return_arm(
    field_offset,
):
    image, call_address, _publisher, _zero_fill, _publications = nested_global_stack_callback_image(
        field_offset=field_offset
    )
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == call_address and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x004011C0
    assert f"field={field_offset:+#x}" in edge.provenance


def test_inactive_stack_context_writes_do_not_poison_prior_publications():
    image, call_address, _publisher, _zero_fill, _publications = nested_global_stack_callback_image(
        field_offset=0x18,
        mutation="post-restore-overlapping-write",
    )
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert any(
        row.source == call_address and row.target == 0x004011C0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_nested_global_stack_domain_binds_publishers_writers_and_callers():
    image, call_address, publisher, zero_fill, _publications = nested_global_stack_callback_image(field_offset=0x20)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()

    memo = next(value for key, value in recovery.finite_control_memo.items() if key[1] == call_address)
    function_dependencies = {
        identifier: fingerprint for kind, identifier, fingerprint in memo.dependencies if kind == "function"
    }
    assert set(function_dependencies) == {
        0x00401000,
        publisher,
        0x00401180,
        zero_fill,
    }
    assert all(len(fingerprint) == 64 for fingerprint in function_dependencies.values())
    assert any(
        kind == "global-slot" and identifier == 0x00402300 for kind, identifier, _fingerprint in memo.dependencies
    )

    hostile, hostile_call, *_rest = nested_global_stack_callback_image(
        field_offset=0x20,
        mutation="alternate-global-writer",
    )
    hostile_recovery = _DirectCfgRecovery(
        hostile,
        build_seed_inventory(hostile, ()),
        generous_limits(hostile),
    )
    hostile_recovery.recover()
    hostile_memo = next(value for key, value in hostile_recovery.finite_control_memo.items() if key[1] == hostile_call)
    assert any(
        kind == "function" and identifier == 0x004011E0 for kind, identifier, _fingerprint in hostile_memo.dependencies
    )


def test_cached_global_stack_domain_replays_transitive_dependencies():
    image, _call_address, _publisher, _zero_fill, _publications = nested_global_stack_callback_image(field_offset=0x24)
    recovery = _DirectCfgRecovery(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery.recover()
    recovery.global_stack_field_cache.clear()

    observed = []
    for _ in range(2):
        dependencies = set()
        recovery.producer_dependency_collectors.append(dependencies)
        try:
            result = recovery._global_stack_field_values(
                0x00402300,
                0x24,
                frozenset(),
            )
        finally:
            assert recovery.producer_dependency_collectors.pop() is dependencies
        assert result is not None
        observed.append(dependencies)

    assert observed[1] == observed[0]
    assert observed[1] == {
        ("function", 0x00401000),
        ("function", 0x00401050),
        ("function", 0x00401180),
        ("function", 0x004011A0),
        ("global-slot", 0x00402300),
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-restore-arm",
        "out-of-order-restore",
        "overwritten-save-slot",
        "unknown-overlapping-write",
        "alternate-global-writer",
        "alternate-unknown-caller",
    ),
)
def test_nested_global_stack_context_rejects_open_or_hostile_domains(
    mutation,
):
    image, call_address, _publisher, _zero_fill, _publications = nested_global_stack_callback_image(
        field_offset=0x20,
        mutation=mutation,
    )
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert any(row.address == call_address and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)
    assert not any(
        row.source == call_address and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_dominating_cdecl_register_definition_crosses_basic_blocks(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-cross-block-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103B and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dominating-definition=0x401031" in edge.provenance
    assert "argument=0" in edge.provenance


def test_cross_block_register_clobber_keeps_callback_unresolved(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-cross-block-clobber")
    assert any(row.address == 0x0040103D and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_recursive_forwarding_does_not_widen_cdecl_callback_domain(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-recursive-callback")
    edges = {
        row.source: row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.flow_kind == "indirect-call-finite-value"
    }
    assert edges[0x00401035] == 0x00401090
    assert edges[0x00401042] == 0x00401090


def test_recursive_unknown_argument_keeps_callback_unresolved(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-recursive-unknown")
    assert any(row.address == 0x00401035 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_complete_cdecl_forwarder_chain_closes_all_five_callbacks(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain")
    expected_sources = {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    }
    observed = {
        row.source: row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source in expected_sources and row.flow_kind == "indirect-call-finite-value"
    }
    assert observed == {source: 0x00401090 for source in expected_sources}
    assert not expected_sources & {row.address for row in cfg.control_targets.unresolved}


def test_cdecl_forwarder_chain_rejects_an_alternate_unknown_caller(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-alternate-caller")
    assert {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    } <= {row.address for row in cfg.control_targets.unresolved}


def test_cdecl_forwarder_chain_rejects_an_intervening_overwrite(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-overwrite")
    assert {
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
        0x00401042,
    } <= {row.address for row in cfg.control_targets.unresolved}


def test_cdecl_forwarder_chain_uses_stable_canonical_ebp_arguments(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-ebp-complex")
    expected_sources = {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    }
    assert {
        row.source: row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source in expected_sources and row.flow_kind == "indirect-call-finite-value"
    } == {source: 0x00401090 for source in expected_sources}


def test_cdecl_forwarder_chain_rejects_clobbered_frame_pointer(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="cdecl-forwarder-chain-ebp-clobber")
    assert {
        0x00401033,
        0x00401036,
        0x00401039,
        0x0040103C,
        0x0040103F,
    } <= {row.address for row in cfg.control_targets.unresolved}


def test_two_sided_signed_byte_domain_recovers_relocated_callback_table(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="signed-byte-domain-table")
    table = cfg.jump_table_at(0x00401014)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.base,
        table.entry_width,
        table.index_min,
        table.index_max,
    ) == (0x00401005, "signed-memory-range", 16, 0x00402300, 4, 0, 15)
    assert table.raw_entries == (0x00401090,) * 16
    assert table.targets == (0x00401090,) * 16
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401014]


def test_signed_byte_domain_accepts_exact_push_and_spill_shape(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="signed-byte-domain-exact-spill")
    table = cfg.jump_table_at(0x0040101B)
    assert (
        table.guard_address,
        table.guard_operator,
        table.guard_bound,
        table.index_min,
        table.index_max,
    ) == (0x00401005, "signed-memory-range", 16, 0, 15)
    assert table.targets == (0x00401090,) * 16


@pytest.mark.parametrize(
    "mode",
    (
        "signed-byte-domain-one-sided",
        "signed-byte-domain-admits-sixteen",
        "signed-byte-domain-bad-slot",
        "signed-byte-domain-relocations-only",
    ),
)
def test_signed_byte_table_without_a_closed_exact_domain_stays_blocking(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401014 and row.kind == "computed-flow-blocker" for row in cfg.control_targets.unresolved
    )
    with pytest.raises(KeyError):
        cfg.jump_table_at(0x00401014)


def test_zero_domain_and_nonzero_guard_prove_transfer_unreachable(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-guarded-callback")
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401039]
    assert any(
        row.address == 0x00401039
        and row.kind == "proven-unreachable-control"
        and "zero-domain contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_domain_without_guard_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-unguarded-callback")
    assert any(row.address == 0x00401035 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_guarded_zero_context_preserves_nonzero_callback_context(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="mixed-zero-nonzero-guarded-callback")
    edges = {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401039 and row.flow_kind == "indirect-call-finite-value"
    }
    assert edges == {0x00401090}
    assert any(
        row.address == 0x00401039
        and row.kind == "proven-unreachable-control-context"
        and "zero context contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_historical_control_diagnostics_fixture_is_frozen_canonical():
    path = Path(__file__).parent / "fixtures/retro/gc125n-historical-control-diagnostics.v1.json"
    payload = path.read_bytes()
    rows = json.loads(payload)
    assert len(rows) == 705
    assert hashlib.sha256(payload).hexdigest() == ("391d34a85b99f16c1455e473978af7ca2234ba7aaee4787c6c24c5710d6fd3d0")
    assert Counter(row["kind"] for row in rows) == {
        "computed-flow-blocker": 290,
        "indirect-flow": 415,
    }


def test_guarded_callback_table_adds_finite_function_seeds(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="callback-table")
    table = cfg.jump_table_at(0x0040100B)
    assert table.flow_kind == "call"
    assert {(edge.target, edge.kind) for edge in cfg.edges if edge.source == table.address} >= {
        (0x00401020, "indirect-call-table"),
        (0x00401060, "indirect-call-table"),
    }
    callback_seeds = [row for row in cfg.seed_inventory.records if row.category == "callback-table-entry"]
    assert {row.address for row in callback_seeds} == {
        0x00401020,
        0x00401060,
    }


def test_zero_guard_remains_proof_across_an_unchanged_backedge(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-loop-guarded-callback")
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401039]
    assert any(
        row.address == 0x00401039
        and row.kind == "proven-unreachable-control"
        and "zero-domain contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_guard_backedge_clobber_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-loop-clobbered-callback")
    assert any(row.address == 0x00401039 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_zero_guard_accepts_a_proven_noreturn_zero_path(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="noreturn-guarded-callback")
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x0040103E]
    assert any(
        row.address == 0x0040103E
        and row.kind == "proven-unreachable-control"
        and "zero-domain contradicts nonzero guard" in row.detail
        for row in cfg.ownership_diagnostics
    )


def test_zero_guard_returning_zero_path_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="returning-guarded-callback")
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_zero_guard_search_covers_a_large_bounded_function(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-distant-guarded-callback")
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x004010D0]
    assert any(
        row.address == 0x004010D0 and row.kind == "proven-unreachable-control" for row in cfg.ownership_diagnostics
    )


def test_distant_zero_callback_without_guard_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="zero-distant-unguarded-callback")
    assert any(row.address == 0x004010D0 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_stack_argument_uses_bounded_linear_prologue_when_tail_conflicts(
    tmp_path,
):
    image = load_dispatch_image(tmp_path, mode="linear-prologue-conflicting-tail")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    decoded = recovery._owned_decoded(0x00401006)
    assert recovery._function_stack_states(0x00401000) is None
    assert recovery._stack_argument_index_at(decoded.address, decoded.operands[1], 0x00401000) == 0


def test_closed_constructor_field_domain_proves_vtable_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100B and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dynamic-field=+0x104" in edge.provenance


def test_unknown_ebp_object_uses_closed_dynamic_field_domain(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-ebp-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100D and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dynamic-field=+0x104" in edge.provenance


def test_constructor_field_domain_ignores_stack_offset_decoy(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-stack-decoy")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401016 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "dynamic-field=+0x104" in edge.provenance


def test_constructor_field_provenance_is_stable_as_finite_writers_grow(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-late-finite-write")
    edges = {
        row.target: row.provenance
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100B and row.flow_kind == "indirect-call-finite-value"
    }
    assert set(edges) == {0x00401090, 0x004010A0}
    assert all("dynamic-field=+0x104" in row for row in edges.values())


def test_finite_control_invalidation_reports_changed_dependency(tmp_path):
    image = load_dispatch_image(tmp_path, mode="constructor-field-late-finite-write")
    progress = []

    recover_cfg(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
        producer_checkpoint_dir=tmp_path / "producer-checkpoints",
        producer_query_budget=0,
        producer_progress_callback=progress.append,
    )

    assert any(
        row.startswith("finite-control cache-invalidated: transfer=0x40100b;") and "changed=dynamic-field:+0x104" in row
        for row in progress
    )


def test_dynamic_field_writer_subproofs_reuse_after_unrelated_summary_growth(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="constructor-field-unknown-write")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    recovery.dynamic_field_cache.clear()
    recovery.dynamic_field_write_receiver_cache.clear()
    receiver_calls = []
    source_calls = []
    original_receiver = recovery._dynamic_field_receiver_identity
    original_source = recovery._finite_operand_values_before

    def record_receiver(*args, **kwargs):
        receiver_calls.append(args[0])
        return original_receiver(*args, **kwargs)

    def record_source(*args, **kwargs):
        source_calls.append(args[0])
        return original_source(*args, **kwargs)

    monkeypatch.setattr(
        recovery,
        "_dynamic_field_receiver_identity",
        record_receiver,
    )
    monkeypatch.setattr(recovery, "_finite_operand_values_before", record_source)
    identity = _AbstractObjectIdentity("argument", 0)
    first = recovery._finite_dynamic_field_values(0x104, frozenset(), identity)
    first_counts = (len(receiver_calls), len(source_calls))

    recovery.direct_calls.add(DirectCall(0x00401080, 0x00401090))
    recovery.dynamic_field_cache.clear()
    dependencies = set()
    recovery.producer_dependency_collectors.append(dependencies)
    try:
        second = recovery._finite_dynamic_field_values(0x104, frozenset(), identity)
    finally:
        assert recovery.producer_dependency_collectors.pop() is dependencies

    assert first is None and second is None
    assert first_counts == (2, 1)
    assert (len(receiver_calls), len(source_calls)) == first_counts
    assert ("function", 0x00401030) in dependencies


def test_dynamic_field_writer_subproof_reuses_old_writer_and_includes_new_writer(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="constructor-field-late-finite-write")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original_writes = tuple(
        sorted(
            recovery.dynamic_field_writes[0x104],
            key=lambda row: row.instruction_address,
        )
    )
    assert len(original_writes) == 2
    expected_values = tuple(row.value for row in original_writes)
    assert all(value is not None for value in expected_values)
    first_write, second_write = (replace(row, value=None) for row in original_writes)
    recovery.dynamic_field_writes = {0x104: {first_write}}
    recovery.dynamic_field_write_count = 1
    recovery.dynamic_field_cache.clear()
    source_calls = Counter()
    original_source = recovery._finite_operand_values_before

    def record_source(*args, **kwargs):
        source_calls[args[0]] += 1
        return original_source(*args, **kwargs)

    monkeypatch.setattr(recovery, "_finite_operand_values_before", record_source)
    first = recovery._finite_dynamic_field_values(0x104, frozenset())

    recovery.dynamic_field_writes[0x104].add(second_write)
    recovery.dynamic_field_write_count = 2
    recovery.dynamic_field_cache.clear()
    dependencies = set()
    recovery.producer_dependency_collectors.append(dependencies)
    try:
        second = recovery._finite_dynamic_field_values(0x104, frozenset())
    finally:
        assert recovery.producer_dependency_collectors.pop() is dependencies

    assert first is not None and first[0] == frozenset({expected_values[0]})
    assert second is not None and second[0] == frozenset(expected_values)
    assert source_calls == Counter(
        {
            first_write.instruction_address: 1,
            second_write.instruction_address: 1,
        }
    )
    assert {
        ("function", recovery._registrar_function_entry(row.instruction_address)) for row in (first_write, second_write)
    } <= dependencies


def test_dynamic_field_writer_subproof_invalidates_nested_field_dependency(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="constructor-field-callback")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original_write = next(iter(recovery.dynamic_field_writes[0x104]))
    expected_value = original_write.value
    write = replace(original_write, value=None)
    recovery.dynamic_field_writes = {0x104: {write}}
    recovery.dynamic_field_write_count = 1
    recovery.dynamic_field_cache.clear()
    source_calls = 0

    def finite_source(*_args, **_kwargs):
        nonlocal source_calls
        source_calls += 1
        recovery._note_producer_dynamic_field_dependency(0x108)
        return frozenset({expected_value}), "nested-field-source"

    monkeypatch.setattr(recovery, "_finite_operand_values_before", finite_source)
    assert recovery._finite_dynamic_field_values(0x104, frozenset())
    assert source_calls == 1

    recovery.direct_calls.add(DirectCall(0x00401080, 0x00401090))
    recovery.dynamic_field_cache.clear()
    dependencies = set()
    recovery.producer_dependency_collectors.append(dependencies)
    try:
        assert recovery._finite_dynamic_field_values(0x104, frozenset())
    finally:
        assert recovery.producer_dependency_collectors.pop() is dependencies
    assert source_calls == 1
    assert ("dynamic-field", 0x108) in dependencies

    nested_write = _DynamicFieldWrite(
        instruction_address=write.instruction_address,
        displacement=0x108,
        width=4,
        value=0,
        receiver_identity=None,
        provenance="nested-field-growth",
    )
    recovery.dynamic_field_writes[0x108] = {nested_write}
    recovery.dynamic_field_write_count = 2
    recovery.dynamic_field_cache.clear()
    assert recovery._finite_dynamic_field_values(0x104, frozenset())
    assert source_calls == 2


def test_dynamic_field_receiver_memo_invalidates_only_changed_receiver_function(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="constructor-field-callback")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    write = next(iter(recovery.dynamic_field_writes[0x104]))
    identity_calls = 0

    def receiver_identity(*_args, **_kwargs):
        nonlocal identity_calls
        identity_calls += 1
        return _AbstractObjectIdentity("argument", identity_calls)

    monkeypatch.setattr(recovery, "_dynamic_field_receiver_identity", receiver_identity)
    first = recovery._dynamic_field_write_receiver_identity(write)

    recovery.direct_calls.add(DirectCall(0x00401080, 0x00401090))
    dependencies = set()
    recovery.producer_dependency_collectors.append(dependencies)
    try:
        second = recovery._dynamic_field_write_receiver_identity(write)
    finally:
        assert recovery.producer_dependency_collectors.pop() is dependencies
    assert first == second
    assert identity_calls == 1
    assert ("function", 0x00401030) in dependencies

    function_entry = recovery._registrar_function_entry(write.instruction_address)
    recovery.seed_records.add(
        SeedRecord(
            address=function_entry,
            category="explicit-seed",
            provenance_address=function_entry,
            provenance_bytes=recovery.instructions[function_entry].bytes_hex,
            detail="changed receiver function",
            is_function=True,
        )
    )
    recovery.producer_seed_revision += 1
    third = recovery._dynamic_field_write_receiver_identity(write)
    assert third != second
    assert identity_calls == 2


def test_dynamic_field_writer_memo_separates_visited_cuts_and_cycles_fail_closed(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="constructor-field-callback")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original_write = next(iter(recovery.dynamic_field_writes[0x104]))
    write = replace(original_write, value=None)
    recovery.dynamic_field_writes = {0x104: {write}}
    recovery.dynamic_field_write_count = 1
    recovery.dynamic_field_cache.clear()
    source_calls = 0

    def cycle_then_finite(*args, **_kwargs):
        nonlocal source_calls
        source_calls += 1
        if source_calls == 1:
            return recovery._finite_dynamic_field_values(0x104, args[3])
        return frozenset({original_write.value}), "different visited cut"

    monkeypatch.setattr(recovery, "_finite_operand_values_before", cycle_then_finite)
    assert recovery._finite_dynamic_field_values(0x104, frozenset()) is None

    recovery.direct_calls.add(DirectCall(0x00401080, 0x00401090))
    recovery.dynamic_field_cache.clear()
    result = recovery._finite_dynamic_field_values(0x104, frozenset({(0xDEAD, "different-cut")}))
    assert result is not None
    assert result[0] == frozenset({original_write.value})
    assert source_calls == 2


def test_dynamic_field_writer_subproof_cache_respects_entry_limit(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="constructor-field-callback")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    original_write = next(iter(recovery.dynamic_field_writes[0x104]))
    write = replace(original_write, value=None)
    recovery.dynamic_field_writer_source_cache.clear()
    recovery.limits = replace(recovery.limits, max_producer_domain_cache_entries=0)
    monkeypatch.setattr(
        recovery,
        "_finite_operand_values_before",
        lambda *_args, **_kwargs: (
            frozenset({original_write.value}),
            "finite source",
        ),
    )

    with pytest.raises(AnalysisLimitError, match="max_producer_domain_cache_entries"):
        recovery._finite_dynamic_field_writer_source(
            write,
            0x104,
            frozenset({(-1, "dynamic-field:260:unknown")}),
        )


def test_unknown_constructor_field_write_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="constructor-field-unknown-write")
    assert any(row.address == 0x0040100B and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_validated_constructor_descriptor_proves_field_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="validated-constructor-descriptor")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401064 and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "identity-validator=0x401080" in edge.provenance
    assert "constructor=0x4010a0" in edge.provenance
    assert "descriptor-field=+0x34" in edge.provenance
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401064]


def test_constructor_descriptor_validator_follows_retail_guard_arms(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-retail-guard-arms",
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040106C and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0


def test_constructor_descriptor_follows_wrapper_and_global_object_origin(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-wrapper-global",
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401066 and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "constructor=0x4010a0" in edge.provenance
    assert not [row for row in cfg.control_targets.unresolved if row.address == 0x00401066]


def test_constructor_descriptor_follows_forwarded_switch_global_origin(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-forwarded-global-switch",
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401066 and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "global-slot=0x402700" in edge.provenance
    assert "rejected-tag=0x436f6d70" in edge.provenance
    assert "caller=0x40110e" in edge.provenance
    assert "caller=0x401117" in edge.provenance


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-forwarded-global-switch-unknown-tag",
        "validated-constructor-descriptor-forwarded-global-switch-hidden-caller",
        "validated-constructor-descriptor-forwarded-global-switch-alternate-writer",
    ),
)
def test_constructor_descriptor_rejects_open_forwarded_switch_global_origin(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401066 and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401066 and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_constructor_descriptor_follows_relocated_double_global_handle(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-wrapper-global-double",
    )
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401067 and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "constructor=0x4010a0" in edge.provenance
    assert "global-slot=0x402710" in edge.provenance
    assert "global-slot=0x402700" in edge.provenance


def test_constructor_descriptor_rejects_unrelocated_double_global_handle(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode=("validated-constructor-descriptor-wrapper-global-double-unrelocated"),
    )
    assert any(
        row.address == 0x00401067 and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401067 and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_constructor_descriptor_filters_closed_tag_disjoint_producer(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="validated-constructor-descriptor-multi-tag")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401074 and row.flow_kind == "indirect-call-constructor-descriptor"
    )
    assert edge.target == 0x004010F0
    assert "rejected-tag=0x436f6d70" in edge.provenance


def test_constructor_descriptor_marks_closed_rejected_domain_unreachable(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="validated-constructor-descriptor-multi-tag-rejected-only",
    )
    assert not any(row.address == 0x00401074 for row in cfg.control_targets.unresolved)
    diagnostic = next(
        row
        for row in cfg.ownership_diagnostics
        if row.address == 0x00401074 and row.kind == "proven-unreachable-control"
    )
    assert "identity validator rejects closed object domain" in diagnostic.detail
    assert "rejected-tag=0x436f6d70" in diagnostic.detail


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-multi-tag-same-tag",
        "validated-constructor-descriptor-multi-tag-unknown-tag",
    ),
)
def test_constructor_descriptor_rejects_non_disjoint_producer(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401074 and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401074 and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-wrapper-global-alternate-writer",
        "validated-constructor-descriptor-wrapper-global-incomplete-domain",
    ),
)
def test_constructor_descriptor_rejects_open_global_object_origin(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401066 and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401066 and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize(
    "mode",
    (
        "validated-constructor-descriptor-different-writer",
        "validated-constructor-descriptor-alternate-producer",
        "validated-constructor-descriptor-changed-descriptor",
        "validated-constructor-descriptor-tag-only",
        "validated-constructor-descriptor-incomplete-initializer-domain",
    ),
)
def test_constructor_descriptor_requires_complete_object_provenance(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x00401064 and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.source == 0x00401064 and row.flow_kind == "indirect-call-constructor-descriptor"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_registered_copied_descriptor_proves_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103E and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x004010F0
    assert "copied-descriptor-component=0" in edge.provenance


def test_unknown_copied_descriptor_source_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-unknown-source")
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_copied_descriptor_domain_does_not_cover_unproven_objects(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-unproven-object")
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_fresh_copied_descriptor_origin_survives_argument_forwarding(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-forwarded-object")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_source_copied_descriptor_origin_survives_argument_forwarding(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-source-forwarded-object")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_forwarded_unknown_descriptor_source_remains_blocking(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-source-forwarded-object-unknown",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_fresh_copied_descriptor_origin_survives_return_wrapper(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-wrapper-returned-object")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_copy_return_wrapper_rejects_unknown_return_path(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-wrapper-returned-object-unknown-return",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_fresh_copied_descriptor_origin_survives_closed_field_forwarding(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-field-forwarded-object")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_field_origin_accepts_collectively_dominating_safe_writes(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-field-forwarded-object-null-branch",
    )
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_field_origin_rejects_collective_unknown_write(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-field-forwarded-object-unknown-branch",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_copied_descriptor_field_forwarding_rejects_unknown_write(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-field-forwarded-object-unknown-write",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_field_origin_survives_closed_intrusive_list_lookup(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-field-list-returned-object")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_recursive_list_query_does_not_poison_later_field_proof(tmp_path):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-field-list-returned-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, _domains = recovery._copied_descriptor_source_domains(frozenset())
    recovery.global_list_field_cache.clear()
    key = (
        0x00402900,
        0x20,
        0x34,
        copy_function,
        recovery._summary_fact_signature(),
        recovery.control_flow_revision,
    )
    recovery.global_list_field_active.add(key)

    assert not recovery._closed_global_intrusive_list_field_origin(
        0x00402900,
        0x20,
        0x34,
        copy_function,
        frozenset(),
    )

    recovery.global_list_field_active.remove(key)
    assert recovery._closed_global_intrusive_list_field_origin(
        0x00402900,
        0x20,
        0x34,
        copy_function,
        frozenset(),
    )


def test_field_origin_rejects_unknown_intrusive_list_insertion(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-field-list-returned-object-unknown-insert",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_field_origin_accepts_runtime_zeroed_list_container(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-field-list-returned-object-runtime-zeroed",
    )
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_field_origin_rejects_runtime_nonzero_list_container(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-field-list-returned-object-runtime-nonzero",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_copied_descriptor_origin_survives_closed_registry_lookup(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-registered-object")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


@pytest.mark.parametrize(
    "mode",
    (
        "copied-descriptor-registered-object-back-reference",
        "copied-descriptor-registered-object-stack-forwarded-back-reference",
    ),
)
def test_copied_descriptor_origin_survives_initialized_back_reference(tmp_path, mode):
    image = load_dispatch_image(
        tmp_path,
        mode=mode,
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())

    assert recovery._argument_has_copied_descriptor_origin(
        0x00401030,
        0,
        copy_function,
        frozenset(value for value in domains[0] if value),
        frozenset(),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (
            "copied-descriptor-registered-object-global-pointer-back-reference",
            True,
        ),
        (
            "copied-descriptor-registered-object-global-pointer-hostile-back-reference",
            False,
        ),
    ),
)
def test_initialized_back_reference_survives_finite_global_pointer_field(tmp_path, mode, expected):
    image = load_dispatch_image(tmp_path, mode=mode)
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())

    assert (
        recovery._argument_has_copied_descriptor_origin(
            0x00401030,
            0,
            copy_function,
            frozenset(value for value in domains[0] if value),
            frozenset(),
        )
        is expected
    )


@pytest.mark.parametrize("mutation", ("unrelocated-publication", "field-write"))
def test_finite_global_pointer_back_reference_is_fail_closed(tmp_path, mutation):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-global-pointer-back-reference"),
    )
    if mutation == "unrelocated-publication":
        image = replace(
            image,
            relocations=tuple(row for row in image.relocations if row.va != 0x00401122),
        )
    else:
        data = bytearray(image.data)
        offset = image.va_to_offset(0x00401195)
        assert offset is not None
        data[offset : offset + 2] = bytes.fromhex("89 08")
        image = replace(image, data=bytes(data))
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())

    assert not recovery._argument_has_copied_descriptor_origin(
        0x00401030,
        0,
        copy_function,
        frozenset(value for value in domains[0] if value),
        frozenset(),
    )


def _static_global_reference_recovery(tmp_path, code: bytes, relocation_offsets: tuple[int, ...]):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-global-pointer-back-reference"),
    )
    function = 0x004011D0
    data = bytearray(image.data)
    offset = image.va_to_offset(function)
    assert offset is not None
    data[offset : offset + 0x30] = b"\xcc" * 0x30
    data[offset : offset + len(code)] = code
    image = replace(
        image,
        data=bytes(data),
        relocations=tuple(
            sorted(
                (row for row in image.relocations if not function <= row.va < function + 0x30),
                key=lambda row: (row.va, row.type),
            )
        )
        + tuple(pe.Relocation(function + relative, 3) for relative in relocation_offsets),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, (audit_anchor(image, function),)),
        generous_limits(image),
    )
    recovery.recover()
    return recovery


def _has_global_pointer_back_reference_origin(recovery):
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())
    return recovery._argument_has_copied_descriptor_origin(
        0x00401030,
        0,
        copy_function,
        frozenset(value for value in domains[0] if value),
        frozenset(),
    )


@pytest.mark.parametrize(
    ("callee", "extra_relocations", "expected"),
    (
        (bytes.fromhex("8b 44 24 04 8b 48 04 31 c0 c3"), (), True),
        (
            bytes.fromhex("8b 44 24 04 a3 00 2a 40 00 31 c0 c3"),
            (0x15,),
            True,
        ),
        (bytes.fromhex("8b 44 24 04 c7 00 01 00 00 00 31 c0 c3"), (), False),
    ),
)
def test_relocated_static_global_argument_requires_closed_field_use(tmp_path, callee, extra_relocations, expected):
    caller = bytes.fromhex("68 00 2b 40 00 e8 06 00 00 00 59 c3 cc cc cc cc")
    recovery = _static_global_reference_recovery(
        tmp_path,
        caller + callee,
        (1, *extra_relocations),
    )

    assert _has_global_pointer_back_reference_origin(recovery) is expected


@pytest.mark.parametrize(
    ("count_setup", "fill_setup", "direction_setup", "expected"),
    (
        (bytes.fromhex("b9 02 00 00 00"), bytes.fromhex("31 c0"), b"", True),
        (
            bytes.fromhex("b9 02 00 00 00"),
            bytes.fromhex("b8 01 00 00 00"),
            b"",
            False,
        ),
        (bytes.fromhex("8b 4c 24 04"), bytes.fromhex("31 c0"), b"", False),
        (
            bytes.fromhex("b9 02 00 00 00"),
            bytes.fromhex("31 c0"),
            bytes.fromhex("fd"),
            False,
        ),
    ),
)
def test_relocated_static_global_zeroer_proves_exact_forward_zero_fill(
    tmp_path, count_setup, fill_setup, direction_setup, expected
):
    prefix = count_setup + bytes.fromhex("57") + fill_setup + bytes.fromhex("55 bf 00 2b 40 00") + direction_setup
    code = prefix + bytes.fromhex("83 ec 08 f3 ab 66 ab 83 c4 08 5d 5f c3")
    relocation = code.index(bytes.fromhex("00 2b 40 00"))
    recovery = _static_global_reference_recovery(tmp_path, code, (relocation,))

    assert _has_global_pointer_back_reference_origin(recovery) is expected


def _global_pointer_consumer_recovery(tmp_path, code: bytes, *, keep_slot_relocation: bool = True):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-global-pointer-back-reference"),
    )
    data = bytearray(image.data)
    offset = image.va_to_offset(0x00401190)
    assert offset is not None
    data[offset : offset + 0x40] = b"\xcc" * 0x40
    data[offset : offset + len(code)] = code
    image = replace(
        image,
        data=bytes(data),
        relocations=tuple(row for row in image.relocations if keep_slot_relocation or row.va != 0x00401191),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    return recovery


@pytest.mark.parametrize(
    ("store_opcode", "expected"),
    ((bytes.fromhex("a2 00 2c 40 00"), True), (bytes.fromhex("a3 00 2c 40 00"), False)),
)
def test_global_pointer_field_distinguishes_partial_and_full_pointer_stores(tmp_path, store_opcode, expected):
    recovery = _global_pointer_consumer_recovery(
        tmp_path,
        bytes.fromhex("a1 00 2a 40 00 b0 01") + store_opcode + bytes.fromhex("31 c0 c3"),
    )

    assert recovery._pointer_definition_preserves_field_without_escape(0x00401190, 0x00401190, 0) is expected


@pytest.mark.parametrize("hostile", (False, True))
def test_global_pointer_field_tracks_exact_call_return_across_loop(tmp_path, hostile):
    after_call = (
        bytes.fromhex("a3 00 2c 40 00 31 c0 43 83 fb 02 7c ee c3")
        if hostile
        else bytes.fromhex("31 c0 43 83 fb 02 7c f3 c3")
    )
    code = bytes.fromhex("31 db e8 29 00 00 00") + after_call
    code += b"\xcc" * (0x30 - len(code)) + b"\xc3"
    recovery = _global_pointer_consumer_recovery(tmp_path, code, keep_slot_relocation=False)

    assert (
        recovery._pointer_definition_preserves_field_without_escape(
            None,
            0x00401190,
            0,
            root_call=0x00401192,
        )
        is not hostile
    )


@pytest.mark.parametrize("hostile", (False, True))
def test_global_pointer_field_tracks_static_forward_repeated_copy(tmp_path, hostile):
    code = bytearray.fromhex("a1 00 2a 40 00 83 ec 10 89 c6 b9 02 00 00 00 8d 3c 24 83 c6 08")
    if hostile:
        code.append(0xFD)
    code.extend(bytes.fromhex("f3 a5 66 a5 83 c4 10 31 c0 c3"))
    recovery = _global_pointer_consumer_recovery(tmp_path, bytes(code))

    assert recovery._pointer_definition_preserves_field_without_escape(0x00401190, 0x00401190, 0) is not hostile


@pytest.mark.parametrize("canonical_setcc", (True, False))
def test_global_pointer_field_requires_exact_boolean_canonicalization(tmp_path, canonical_setcc):
    prefix = bytes.fromhex("80 78 04 01 0f 95 c0") if canonical_setcc else b""
    recovery = _global_pointer_consumer_recovery(
        tmp_path,
        bytes.fromhex("a1 00 2a 40 00") + prefix + bytes.fromhex("25 ff 00 00 00 a3 00 2c 40 00 31 c0 c3"),
    )

    assert recovery._pointer_definition_preserves_field_without_escape(0x00401190, 0x00401190, 0) is canonical_setcc


@pytest.mark.parametrize("hostile", (False, True))
def test_global_pointer_return_audits_unowned_raw_caller_fallthrough(tmp_path, hostile):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-global-pointer-back-reference"),
    )
    probe = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    owned_call = next(address for address in probe._raw_direct_call_sites(0x00401190) if address < 0x00401100)
    data = bytearray(image.data)
    consumer_offset = image.va_to_offset(0x00401190)
    caller_fallthrough = image.va_to_offset(owned_call + 5)
    hidden_offset = image.va_to_offset(0x004011D0)
    assert consumer_offset is not None
    assert caller_fallthrough is not None
    assert hidden_offset is not None
    data[consumer_offset : consumer_offset + 0x20] = b"\xcc" * 0x20
    data[consumer_offset : consumer_offset + 6] = bytes.fromhex("a1 00 2a 40 00 c3")
    data[caller_fallthrough : caller_fallthrough + 4] = bytes.fromhex("31 c0 5b c3")
    hidden = bytearray.fromhex("e8 bb ff ff ff")
    if hostile:
        hidden.extend(bytes.fromhex("a3 00 2c 40 00"))
    hidden.extend(bytes.fromhex("31 c0 c3"))
    data[hidden_offset : hidden_offset + 0x20] = b"\xcc" * 0x20
    data[hidden_offset : hidden_offset + len(hidden)] = hidden
    image = replace(
        image,
        data=bytes(data),
        relocations=tuple(row for row in image.relocations if not 0x004011D0 <= row.va < 0x004011F0),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._pointer_definition_preserves_field_without_escape(0x00401190, 0x00401190, 0) is not hostile


def test_stack_forwarded_back_reference_requires_local_initializer(tmp_path):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-stack-forwarded-back-reference"),
    )
    data = bytearray(image.data)
    offset = image.va_to_offset(0x004011B5)
    assert offset is not None
    struct.pack_into("<i", data, offset, 0x004010F0 - 0x004011B9)
    image = replace(image, data=bytes(data))
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())

    assert not recovery._argument_has_copied_descriptor_origin(
        0x00401030,
        0,
        copy_function,
        frozenset(value for value in domains[0] if value),
        frozenset(),
    )


def test_stack_forwarded_back_reference_rejects_intervening_clobber(tmp_path):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-stack-forwarded-back-reference"),
    )
    data = bytearray(image.data)
    offset = image.va_to_offset(0x004011D4)
    assert offset is not None
    data[offset : offset + 12] = bytes.fromhex("8b 44 24 04 8b 00 31 c9 89 48 04 c3")
    image = replace(image, data=bytes(data))
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())

    assert not recovery._argument_has_copied_descriptor_origin(
        0x00401030,
        0,
        copy_function,
        frozenset(value for value in domains[0] if value),
        frozenset(),
    )


@pytest.mark.parametrize(
    "mutation",
    ("wrong-source", "missing-initializer", "wrong-global-writer"),
)
def test_copied_descriptor_back_reference_requires_exact_initializer(tmp_path, mutation):
    image = load_dispatch_image(
        tmp_path,
        mode="copied-descriptor-registered-object-back-reference",
    )
    data = bytearray(image.data)
    if mutation == "wrong-source":
        offset = image.va_to_offset(0x00401119)
        assert offset is not None
        data[offset : offset + 3] = bytes.fromhex("89 59 04")
    elif mutation == "missing-initializer":
        offset = image.va_to_offset(0x00401016)
        assert offset is not None
        struct.pack_into("<i", data, offset, 0x004010F0 - 0x0040101A)
    else:
        offset = image.va_to_offset(0x0040101B)
        assert offset is not None
        data[offset : offset + 3] = bytes.fromhex("89 d8 90")
    image = replace(image, data=bytes(data))
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, domains = recovery._copied_descriptor_source_domains(frozenset())

    assert not recovery._argument_has_copied_descriptor_origin(
        0x00401030,
        0,
        copy_function,
        frozenset(value for value in domains[0] if value),
        frozenset(),
    )


def test_registered_copy_origin_survives_closed_link_cursor(tmp_path):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object-link-cursor")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, _domains = recovery._copied_descriptor_source_domains(frozenset())

    assert recovery._register_has_registered_copy_origin(0x0040117E, "eax", 0x00401170, copy_function)


def test_closed_link_cursor_ignores_post_observation_clobber(tmp_path):
    image = load_dispatch_image(
        tmp_path,
        mode=("copied-descriptor-registered-object-link-cursor-post-clobber"),
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, _domains = recovery._copied_descriptor_source_domains(frozenset())

    assert recovery._register_has_registered_copy_origin(0x0040117E, "eax", 0x00401170, copy_function)


def test_registered_copy_origin_rejects_unknown_link_cursor(tmp_path):
    image = load_dispatch_image(
        tmp_path,
        mode="copied-descriptor-registered-object-link-cursor-unknown",
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, _domains = recovery._copied_descriptor_source_domains(frozenset())

    assert not recovery._register_has_registered_copy_origin(0x0040117E, "eax", 0x00401170, copy_function)


def test_registered_copy_origin_survives_runtime_global_field(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-registered-object-runtime-global-field",
    )
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_runtime_global_copy_field_survives_guard_block(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode=("copied-descriptor-registered-object-guarded-runtime-global-field"),
    )
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_runtime_global_copy_field_rejects_guarded_clobber(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode=("copied-descriptor-registered-object-guarded-runtime-global-field-clobber"),
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_runtime_global_copy_field_rejects_unknown_writer(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode=("copied-descriptor-registered-object-runtime-global-field-unknown"),
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_forward_bounded_string_writer_reports_size_argument(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "8b 54 24 04 8b 4c 24 0c 89 d7 01 f9 aa 39 cf 72 fb 29 f9 f3 aa c3",
    )
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()
    recovery.function_addresses.add(0x00401020)

    assert recovery._forward_bounded_string_writer_size_argument(0x0040100A, 0) == 2


def test_field_preservation_tracks_scalar_movsd_pointer_steps(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "8b 7c 24 04 8b 74 24 08 a5 a5 c3",
    )
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()
    recovery.function_addresses.add(0x0040100A)

    assert recovery._function_argument_preserves_field(0x0040100A, 0, 8)
    assert not recovery._function_argument_preserves_field(0x0040100A, 0, 4)


def test_field_preservation_tracks_incremented_pointer(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "8b 44 24 04 40 c6 00 00 c3",
    )
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()
    recovery.function_addresses.add(0x0040100A)

    assert recovery._function_argument_preserves_field(0x0040100A, 0, 4)
    assert not recovery._function_argument_preserves_field(0x0040100A, 0, 0)


def test_return_offsets_accept_pointer_independent_constants(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "8b 4c 24 04 8d 0c 09 85 c9 74 06 b8 08 00 00 00 c3 31 c0 c3",
    )
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()
    recovery.function_addresses.add(0x0040100A)

    assert recovery._function_argument_return_offsets(0x0040100A, 0) == frozenset()


def test_return_offsets_reject_mixed_pointer_return(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "8b 4c 24 04 8d 0c 09 85 c9 74 03 89 c8 c3 31 c0 c3",
    )
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()
    recovery.function_addresses.add(0x0040100A)

    assert recovery._function_argument_return_offsets(0x0040100A, 0) is None


def test_field_summary_accepts_overlap_safe_copy_before_destination(tmp_path):
    image = load_memmove_program(tmp_path)
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._function_argument_preserves_field(0x00401080, 0, -4)
    assert recovery._function_argument_does_not_read_field(0x00401080, 0, -4)
    assert recovery._function_argument_preserves_field(0x00401080, 1, -4)
    assert recovery._function_argument_does_not_read_field(0x00401080, 1, -4)


def test_field_summary_rejects_corrupt_overlap_safe_copy(tmp_path):
    image = load_memmove_program(tmp_path, corrupt_backward_step=True)
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()

    assert not recovery._function_argument_preserves_field(0x00401080, 0, -4)
    assert not recovery._function_argument_does_not_read_field(0x00401080, 0, -4)
    assert not recovery._function_argument_preserves_field(0x00401080, 1, -4)
    assert not recovery._function_argument_does_not_read_field(0x00401080, 1, -4)


def test_field_summary_accepts_forward_copy_before_destination(tmp_path):
    image = load_memcpy_program(tmp_path)
    recovery = _DirectCfgRecovery(
        image,
        inventory(image),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._function_argument_preserves_field(0x00401080, 0, -4)
    assert recovery._function_argument_does_not_read_field(0x00401080, 0, -4)
    assert recovery._function_argument_preserves_field(0x00401080, 1, -4)
    assert recovery._function_argument_does_not_read_field(0x00401080, 1, -4)


def test_registered_copy_origin_survives_stack_return(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-registered-object-stack-return",
    )
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_registered_copy_origin_rejects_clobbered_stack_return(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-registered-object-stack-return-unknown",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_registry_lookup_accepts_proven_null_start_cursor(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-registered-object-cursor-lookup")
    assert any(
        row.source == 0x0040103E and row.target == 0x004010F0 and row.flow_kind == "indirect-call-finite-value"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_registry_lookup_rejects_unknown_start_cursor(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-registered-object-unknown-cursor-lookup",
    )
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_registered_copy_state_is_cached_per_function(tmp_path, monkeypatch):
    class NoIterationSet(set):
        def __iter__(self):
            raise AssertionError("registered-copy state scanned all calls")

    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, _domains = recovery._copied_descriptor_source_domains(frozenset())
    recovery.registered_copy_register_cache.clear()
    recovery.direct_calls = NoIterationSet(recovery.direct_calls)

    assert recovery._register_has_registered_copy_origin(0x0040101D, "eax", 0x00401000, copy_function)

    def reject_cfg_walk(*_args, **_kwargs):
        raise AssertionError("registered-copy state rebuilt for one function")

    monkeypatch.setattr(recovery, "_summary_successors", reject_cfg_walk)
    assert recovery._register_has_registered_copy_origin(0x0040101E, "eax", 0x00401000, copy_function)


def test_registered_copy_cache_tracks_registry_fact_changes(tmp_path):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    copy_function, _domains = recovery._copied_descriptor_source_domains(frozenset())
    registry_key = (copy_function, recovery._summary_fact_signature())
    registries = recovery.copy_registry_cache[registry_key]
    assert registries
    recovery.registered_copy_register_cache.clear()
    recovery.registered_copy_state_cache.clear()
    recovery.copy_registry_cache[registry_key] = ()

    assert not recovery._register_has_registered_copy_origin(0x0040101D, "eax", 0x00401000, copy_function)

    recovery.copy_registry_cache[registry_key] = registries
    assert recovery._register_has_registered_copy_origin(0x0040101D, "eax", 0x00401000, copy_function)


def test_raw_direct_call_scan_is_cached_per_target(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    original_read = pe.Image.read
    executable_reads = 0

    def counted_read(current, va, size):
        nonlocal executable_reads
        if current is image and any(
            section.is_executable and section.va == va and section.raw_size == size for section in image.sections
        ):
            executable_reads += 1
        return original_read(current, va, size)

    monkeypatch.setattr(pe.Image, "read", counted_read)

    first = recovery._raw_direct_call_sites(0x004010F0)
    second = recovery._raw_direct_call_sites(0x004010F0)

    assert second == first
    assert executable_reads == sum(section.is_executable and section.raw_size >= 5 for section in image.sections)


def test_direct_call_domain_is_cached_for_unchanged_facts(tmp_path):
    class NoIterationSet(set):
        def __iter__(self):
            raise AssertionError("direct-call domain rescanned unchanged calls")

    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    first = recovery._direct_call_domain_is_closed(0x00401000)
    recovery.direct_calls = NoIterationSet(recovery.direct_calls)

    assert recovery._direct_call_domain_is_closed(0x00401000) is first


def test_incoming_call_sites_use_target_index(tmp_path):
    class NoIterationSet(set):
        def __iter__(self):
            raise AssertionError("incoming call query rescanned every edge")

    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()
    expected = recovery._incoming_call_sites(0x004010A0)
    recovery.edges = NoIterationSet(recovery.edges)

    assert recovery._incoming_call_sites(0x004010A0) == expected


def test_owned_instruction_reuses_audited_decode(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    expected = recovery.instructions[0x00401000]
    recovery._owned_decoded(0x00401000)
    assert len(recovery.decoded_instruction_cache) <= _DECODED_INSTRUCTION_CACHE_LIMIT

    def reject_decode(_address):
        raise AssertionError("owned instruction was decoded more than once")

    monkeypatch.setattr(recovery, "_decode_one", reject_decode)
    decoded = recovery._owned_decoded(0x00401000)

    assert decoded.address == expected.address
    assert decoded.size == expected.size
    assert bytes(decoded.bytes).hex() == expected.bytes_hex


def test_register_family_reuses_capstone_name_lookup(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.register_family_cache.clear()
    register = capstone.x86_const.X86_REG_EAX
    original = recovery.decoder.reg_name
    calls = []

    def record_name(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(recovery.decoder, "reg_name", record_name)

    assert recovery._register_family(register) == "eax"
    assert recovery._register_family(register) == "eax"
    assert calls == [register]


def test_registrar_lookup_reuses_sorted_function_entries(tmp_path):
    class NoIterationSet(set):
        def __iter__(self):
            raise AssertionError("registrar lookup resorted unchanged entries")

    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    expected = recovery._registrar_function_entry(0x0040101D)
    recovery.function_addresses = NoIterationSet(recovery.function_addresses)

    assert recovery._registrar_function_entry(0x0040101E) == expected


def test_direct_call_target_index_avoids_global_call_scan(tmp_path):
    class NoIterationSet(set):
        def __iter__(self):
            raise AssertionError("targeted caller lookup scanned every call")

    image = load_dispatch_image(tmp_path, mode="copied-descriptor-registered-object")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    target = next(iter(recovery.direct_call_sources_by_target))
    expected = tuple(sorted(recovery.direct_call_sources_by_target[target]))
    recovery.direct_calls = NoIterationSet(recovery.direct_calls)

    assert tuple(row.address for row in recovery._direct_calls_to(target)) == expected


def test_guarded_slot_zero_consumers_are_cached(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    recovery.guarded_slot_zero_consumer_cache.clear()
    expected = recovery._guarded_slot_zero_descriptor_consumers()

    def reject_decode(_address):
        raise AssertionError("guarded consumers were rescanned")

    monkeypatch.setattr(recovery, "_owned_decoded", reject_decode)
    assert recovery._guarded_slot_zero_descriptor_consumers() == expected


def test_copied_descriptor_registry_rejects_unknown_writer(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-registered-object-unknown-writer")
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_copied_descriptor_slot_zero_hypothesis_closes_after_replay(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103D and row.flow_kind == "indirect-call-copied-descriptor-slot-zero"
    )
    assert edge.target == 0x004010F0
    assert "fixed-nine-dword-copy" in edge.provenance


def test_copied_descriptor_slot_zero_preserves_target_source_correlation(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-slot-zero-correlated-sources")
    edges = {
        row.target: row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103D and row.flow_kind == "indirect-call-copied-descriptor-slot-zero"
    }
    assert set(edges) == {0x004010D8, 0x004010F0}
    assert "slots=0x402300" in edges[0x004010F0].provenance
    assert "0x402400" not in edges[0x004010F0].provenance
    assert "slots=0x402400" in edges[0x004010D8].provenance
    assert "0x402300" not in edges[0x004010D8].provenance


def test_copied_descriptor_tag_provenance_closes_rejected_callback(
    tmp_path,
):
    cfg = dispatch_cfg(
        tmp_path,
        mode="copied-descriptor-slot-zero-tagged-rejected-callback",
    )
    assert not any(row.address == 0x004011A5 for row in cfg.control_targets.unresolved)
    diagnostic = next(
        row
        for row in cfg.ownership_diagnostics
        if row.address == 0x004011A5 and row.kind == "proven-unreachable-control"
    )
    assert "required-tag=0x50617273" in diagnostic.detail
    assert "rejected-tag=0x436f6d70" in diagnostic.detail
    assert "source-table=0x402300" in diagnostic.detail


def test_stack_state_applies_closed_indirect_callee_cleanup(tmp_path):
    image = load_dispatch_image(
        tmp_path,
        mode="copied-descriptor-slot-zero-tagged-rejected-callback",
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    states = recovery._function_stack_states(0x00401138)

    assert states is not None
    assert states[0x00401153][0] == -8
    assert states[0x00401158][0] == -8


def test_stack_state_uses_indexed_call_targets(tmp_path):
    class NoIterationSet(set):
        def __iter__(self):
            raise AssertionError("stack analysis scanned the global CFG set")

    image = load_dispatch_image(
        tmp_path,
        mode="copied-descriptor-slot-zero-tagged-rejected-callback",
    )
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()
    recovery.stack_state_cache.clear()
    recovery.callee_cleanup_cache.clear()
    recovery.direct_calls = NoIterationSet(recovery.direct_calls)
    recovery.edges = NoIterationSet(recovery.edges)

    assert recovery._closed_call_stack_cleanup(0x00401151) == 8


def test_stack_state_rejects_incorrect_indirect_callee_cleanup(tmp_path):
    image = load_dispatch_image(
        tmp_path,
        mode="copied-descriptor-slot-zero-tagged-rejected-callback",
    )
    data = bytearray(image.data)
    ret_offset = image.va_to_offset(0x0040112E)
    assert ret_offset is not None
    data[ret_offset : ret_offset + 3] = bytes.fromhex("c3 cc cc")
    image = replace(image, data=bytes(data))
    recovery = _DirectCfgRecovery(
        image,
        build_seed_inventory(image, ()),
        generous_limits(image),
    )
    recovery.recover()

    assert recovery._function_stack_states(0x00401138) is None


@pytest.mark.parametrize(
    "mode",
    (
        "copied-descriptor-slot-zero-tagged-rejected-callback-missing-stamper",
        "copied-descriptor-slot-zero-tagged-rejected-callback-same-tag",
        "copied-descriptor-slot-zero-tagged-rejected-callback-unrelocated-provider",
    ),
)
def test_copied_descriptor_tag_provenance_is_fail_closed(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(
        row.address == 0x004011A5 and row.kind in {"indirect-flow", "computed-flow-blocker"}
        for row in cfg.control_targets.unresolved
    )
    assert not any(
        row.address == 0x004011A5 and row.kind == "proven-unreachable-control" for row in cfg.ownership_diagnostics
    )


@pytest.mark.parametrize(
    "mode",
    (
        "copied-descriptor-slot-zero-hidden-caller",
        "copied-descriptor-slot-zero-unrelocated-record",
    ),
)
def test_copied_descriptor_slot_zero_hypothesis_is_fail_closed(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert any(row.address == 0x0040103D and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)
    assert not any(
        row.source == 0x0040103D and row.flow_kind == "indirect-call-copied-descriptor-slot-zero"
        for row in cfg.control_targets.finite_internal_edges
    )


def test_hypothesis_replay_discovers_second_order_object_table(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-object-hypothesis-chain")
    assert any(
        row.address == 0x00401048 and row.category == "copied-descriptor-callback-entry"
        for row in cfg.seed_inventory.records
    )
    assert any(
        row.address == 0x004010F0 and row.category == "object-callback-table-entry"
        for row in cfg.seed_inventory.records
    )
    assert not any(row.address == 0x00401058 for row in cfg.control_targets.unresolved)


def test_hypothesis_replay_reuses_all_reproduced_trial_cfg(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    recoveries = []
    original = _DirectCfgRecovery.recover

    def record_recovery(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        return cfg

    monkeypatch.setattr(_DirectCfgRecovery, "recover", record_recovery)

    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert len(recoveries) == 2
    assert cfg is recoveries[-1][1]
    assert any(row.category == "copied-descriptor-callback-entry" for row in cfg.seed_inventory.records)


def test_reproduced_trial_revalidates_pre_finite_after_late_finite_edge(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    late_function = 0x00401100
    special_transfer = late_function
    late_transfer = late_function + 2
    data = bytearray(image.data)
    text_section = next(row for row in image.sections if row.name == ".text")
    late_offset = text_section.raw_offset + (late_function - text_section.va)
    data[late_offset : late_offset + 5] = bytes.fromhex("ff d0 ff d1 c3")
    data[late_offset + 0x20] = 0xC3
    data[late_offset + 0x30] = 0xC3
    image = replace(
        image,
        data=bytes(data),
        sha256=hashlib.sha256(data).hexdigest(),
        sections=tuple(
            replace(row, raw_size=0x200, virt_size=0x200) if row.name == ".text" else row for row in image.sections
        ),
        executable_ranges=((text_section.va, text_section.va + 0x200),),
    )
    recoveries = []
    special_observations = {}
    original_recover = _DirectCfgRecovery.recover
    original_special = _DirectCfgRecovery._recover_global_slot_targets
    original_finite = _DirectCfgRecovery._recover_finite_value_target
    original_add_edge = _DirectCfgRecovery._add_edge

    def omit_replayed_hypothesis_edge(recovery, source, target, kind, *, provenance=None):
        if kind == "indirect-call-copied-descriptor-slot-zero":
            return None
        return original_add_edge(
            recovery,
            source,
            target,
            kind,
            provenance=provenance,
        )

    def synthetic_special(recovery, decoded, instruction, *, flow_kind):
        if instruction.address != special_transfer:
            return original_special(recovery, decoded, instruction, flow_kind=flow_kind)
        finite_edge_present = any(
            row.source == late_transfer and row.kind == "indirect-call-finite-value" for row in recovery.edges
        )
        special_observations.setdefault(id(recovery), []).append(finite_edge_present)
        targets = {0x00401120}
        if finite_edge_present:
            targets.add(0x00401130)
        provenance = "test-special-domain=late-finite-edge"
        for target in sorted(targets):
            recovery._add_edge(
                instruction.address,
                target,
                "indirect-call-global-slot",
                provenance=provenance,
            )
            recovery._record_finite_target(target)
            recovery._enqueue(target, is_function=True)
        recovery._record_fixpoint_update()
        return True

    def synthetic_finite(recovery, decoded, instruction, *, flow_kind):
        if instruction.address != late_transfer:
            return original_finite(recovery, decoded, instruction, flow_kind=flow_kind)
        if not recovery._allow_movzx_producer_domains:
            return False
        recovery._add_edge(
            instruction.address,
            0x00401120,
            "indirect-call-finite-value",
            provenance="test-late-finite-domain",
        )
        recovery._record_finite_target(0x00401120)
        recovery._enqueue(0x00401120, is_function=True)
        return True

    def record_recovery(recovery):
        cfg = original_recover(recovery)
        recoveries.append((recovery, cfg))
        return cfg

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_recover_global_slot_targets",
        synthetic_special,
    )
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_add_edge",
        omit_replayed_hypothesis_edge,
    )
    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_recover_finite_value_target",
        synthetic_finite,
    )
    monkeypatch.setattr(_DirectCfgRecovery, "recover", record_recovery)

    cfg = recover_cfg(
        image,
        (image.entrypoint, late_function),
        generous_limits(image),
    )

    assert len(recoveries) == 2
    assert cfg is recoveries[-1][1]
    assert all(observations[0] is False and True in observations[1:] for observations in special_observations.values())
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == special_transfer and row.flow_kind == "indirect-call-global-slot"
    } == {0x00401120, 0x00401130}


def test_reused_trial_discovers_additional_callback_hypothesis(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-object-hypothesis-chain")
    recoveries = []
    original = _DirectCfgRecovery.recover

    def record_recovery(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        return cfg

    monkeypatch.setattr(_DirectCfgRecovery, "recover", record_recovery)

    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert len(recoveries) == 3
    assert recoveries[1][0].object_callback_table_hypotheses
    assert cfg is recoveries[-1][1]
    assert {row.category for row in cfg.seed_inventory.records if "callback" in row.category} == {
        "copied-descriptor-callback-entry",
        "object-callback-table-entry",
    }


def test_invalidated_reused_trial_rebuilds_clean_accepted_seeds(tmp_path, monkeypatch):
    class FirstIterationOnly:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            rows = self.rows
            self.rows = ()
            return iter(rows)

    image = load_dispatch_image(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    recoveries = []
    original = _DirectCfgRecovery.recover

    def invalidate_after_reproduction(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        if len(recoveries) == 2:
            recovery.validated_copied_descriptor_callback_hypotheses = FirstIterationOnly(
                tuple(recovery.validated_copied_descriptor_callback_hypotheses)
            )
        return cfg

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "recover",
        invalidate_after_reproduction,
    )

    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert len(recoveries) == 3
    assert cfg is recoveries[-1][1]
    assert not any("callback" in row.category for row in cfg.seed_inventory.records)


def test_rejected_trial_rebuilds_clean_accepted_seeds(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    recoveries = []
    original = _DirectCfgRecovery.recover

    def reject_trial_candidate(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        if len(recoveries) == 2:
            recovery.validated_copied_descriptor_callback_hypotheses.clear()
        return cfg

    monkeypatch.setattr(_DirectCfgRecovery, "recover", reject_trial_candidate)

    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))

    assert len(recoveries) == 3
    assert cfg is recoveries[-1][1]
    assert not any("callback" in row.category for row in cfg.seed_inventory.records)


def test_reused_trial_preserves_producer_checkpoint_incomplete(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-slot-zero-hypothesis")
    recoveries = []
    original = _DirectCfgRecovery.recover
    trial_query_id = "trial-only-producer-query"

    def mark_trial_query_pending(recovery):
        cfg = original(recovery)
        recoveries.append((recovery, cfg))
        if len(recoveries) == 2:
            session = recovery.producer_certificate_session
            assert session is not None
            recovery.producer_query_ids.add(trial_query_id)
            session.query_states[trial_query_id] = "pending"
        return cfg

    monkeypatch.setattr(_DirectCfgRecovery, "recover", mark_trial_query_pending)

    with pytest.raises(ProducerCheckpointIncomplete) as raised:
        recover_cfg(
            image,
            build_seed_inventory(image, ()),
            generous_limits(image),
            producer_checkpoint_dir=tmp_path / "producer-checkpoints",
            producer_query_budget=0,
        )

    assert len(recoveries) == 2
    assert raised.value.completed_this_run == 0
    assert raised.value.discovered_queries == 1
    assert raised.value.validated_queries == 0
    assert raised.value.pending_queries == 1


def test_certified_copied_descriptor_callback_closes_incoming_domain(
    tmp_path,
):
    image = load_dispatch_image(tmp_path, mode="copied-descriptor-object-hypothesis-chain")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()

    assert recovery._incoming_call_domain_is_closed(0x00401048)


def test_six_movsd_decoy_without_constructor_contract_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-six-movsd-decoy")
    assert any(row.address == 0x0040103E and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_cross_block_callback_clobber_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="copied-descriptor-cross-block-clobber")
    assert any(row.address == 0x00401040 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_bounded_affine_descriptor_array_proves_every_callback(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="bounded-descriptor-array")
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401009 and row.flow_kind == "indirect-call-finite-value"
    } == {0x00401090, 0x004010A0, 0x004010B0}


def test_unbounded_affine_descriptor_array_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="unbounded-descriptor-array")
    assert any(row.address == 0x00401009 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_nested_bounded_affine_descriptor_array_uses_innermost_loop(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="nested-bounded-descriptor-array")
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100D and row.flow_kind == "indirect-call-finite-value"
    } == {0x00401090, 0x004010A0, 0x004010B0}


def test_nested_affine_outer_clobber_remains_blocking(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="nested-bounded-descriptor-array-with-outer-clobber",
    )
    assert any(row.address == 0x0040100D and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_nested_affine_ignores_clobber_on_non_backedge_exit(tmp_path):
    cfg = dispatch_cfg(
        tmp_path,
        mode="nested-bounded-descriptor-array-dead-end-clobber",
    )
    assert {
        row.target
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100D and row.flow_kind == "indirect-call-finite-value"
    } == {0x00401090, 0x004010A0, 0x004010B0}


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing-guard", "finite dominating guard"),
        ("conflicting-width", "entry width conflicts"),
        ("unmapped-entry", "jump-table entry is not wholly mapped"),
        ("target-outside-text", "jump-table target is not executable"),
    ],
)
def test_computed_table_failures_remain_explicit_blockers(tmp_path, mode, message):
    image = load_dispatch_image(tmp_path, mode=mode)
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    assert any(row.kind == "computed-flow-blocker" and message in row.detail for row in cfg.ownership_diagnostics)


def test_guarded_468_way_dispatch_is_recovered(tmp_path):
    cfg = dispatch_cfg(tmp_path, entry_count=468)
    table = cfg.jump_table_at(0x0040100B)
    assert table.index_min == 0
    assert table.index_max == 467
    assert len(table.raw_entries) == 468
    assert len(table.targets) == 468
    assert table.base == 0x00402200


def test_structural_default_limits_derive_from_executable_raw_bytes(
    synthetic_cfg_image,
):
    limits = AnalysisLimits.for_image(synthetic_cfg_image)
    assert limits.max_instructions == 0x88
    assert limits.max_blocks == 0x88
    assert limits.max_edges == 8 * 0x88
    assert limits.max_jump_tables == 65_536
    assert limits.max_jump_table_entries == 524_288
    assert limits.max_functions == 65_536
    assert limits.max_finite_targets == 65_536
    assert limits.max_finite_values == 8_192
    assert limits.max_states_per_block == 256
    assert limits.max_contexts_per_entry == 256
    assert limits.max_scc_iterations == 65_536
    assert limits.max_summary_iterations == 65_536
    assert limits.max_fixpoint_updates == 8_000_000


@pytest.mark.parametrize(
    "cap_name",
    [field.name for field in fields(AnalysisLimits)],
)
@pytest.mark.parametrize("delta", [0, 1], ids=["equal", "over"])
def test_every_analysis_cap_fails_closed_at_equality_and_over(synthetic_cfg_image, cap_name, delta):
    limits = generous_limits(synthetic_cfg_image)
    configured = getattr(limits, cap_name)
    with pytest.raises(AnalysisLimitError) as raised:
        limits.check(cap_name, configured + delta)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == configured
    assert raised.value.observed == configured + delta
    assert f"configured={configured}" in str(raised.value)
    assert f"observed={configured + delta}" in str(raised.value)


def test_seed_order_cannot_change_raw_cfg(synthetic_cfg_image):
    limits = generous_limits(synthetic_cfg_image)
    a = recover_cfg(
        synthetic_cfg_image,
        (0x00401000, 0x00401040, 0x00401070),
        limits,
    )
    b = recover_cfg(
        synthetic_cfg_image,
        (0x00401070, 0x00401040, 0x00401000),
        limits,
    )
    assert a.to_dict() == b.to_dict()


def test_direct_cfg_owns_exact_instructions_blocks_edges_and_calls(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    assert (0x00401003, 0x00401040) in {(call.address, call.target) for call in cfg.direct_calls}
    assert (0x0040104B, 0x00401060) in {(call.address, call.target) for call in cfg.direct_calls}
    assert any(
        edge.source == 0x00401008 and edge.target == 0x00401020 and edge.kind == "conditional-branch"
        for edge in cfg.edges
    )
    call_block = next(block for block in cfg.blocks if block.start == 0x00401000)
    assert call_block.end == 0x00401008
    assert call_block.instruction_addresses == (
        0x00401000,
        0x00401001,
        0x00401003,
    )
    assert all(len(bytes.fromhex(instruction.bytes_hex)) == instruction.size for instruction in cfg.instructions)
    unresolved_indirects = [row for row in cfg.ownership_diagnostics if row.kind == "indirect-flow"]
    assert len(unresolved_indirects) == 1
    assert unresolved_indirects[0].address == 0x0040107D


def test_embedded_e8_is_explained_as_data_not_call(synthetic_cfg_image):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    row = next(row for row in cfg.raw_e8_candidates if row.address == 0x00401080)
    assert row.target == 0x00401060
    assert row.classification == "owned-data"
    data = next(row for row in cfg.data_regions if row.start == 0x00401080 and row.end == 0x00401088)
    assert data.provenance


def test_partial_five_byte_e8_data_containment_is_unresolved(tmp_path):
    image = load_cfg_image(tmp_path, "partial_e8_data_reference")
    with pytest.raises(CfgRecoveryError, match="raw E8 candidate is unresolved"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_interior_e8_crossing_owned_instructions_is_explained(tmp_path):
    image = load_cfg_image(tmp_path, "interior_e8_crosses_owned_instructions")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    row = next(row for row in cfg.raw_e8_candidates if row.address == 0x00401071)
    assert row.target == 0x00401076
    assert row.classification == "owned-instruction-bytes"
    instructions = {row.address: row for row in cfg.instructions}
    assert instructions[0x00401070].mnemonic == "add"
    assert instructions[0x00401072].mnemonic == "add"
    assert instructions[0x00401074].mnemonic == "add"


def test_retail_mwcc_nop_encodings_are_owned_as_padding(tmp_path):
    image = load_cfg_image(tmp_path, "mwcc_padding_encodings")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(region.start == 0x00401061 and region.end == 0x00401070 for region in cfg.padding_regions)


def test_pure_zero_fill_after_terminal_owns_executable_raw_tail(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    data = bytearray(synthetic_cfg_image.data)
    data[text.raw_offset : text.raw_offset + 0x10] = b"\xc3" + b"\0" * 15
    tail_section = replace(text, raw_size=0x10, virt_size=0x10)
    image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=text.va,
        sections=(tail_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((text.va, text.va + 0x10),),
    )
    cfg = recover_cfg(image, (text.va,), generous_limits(image))
    assert any(region.start == text.va + 1 and region.end == text.va + 0x10 for region in cfg.padding_regions)


def test_unsupported_cross_block_initializer_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "unsupported_cross_block_initializer")
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unsupported_indexed_initializer_fails_closed(tmp_path):
    image = load_cfg_image(tmp_path, "unsupported_indexed_initializer")
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_instruction_interior_and_unmapped_seeds_fail_closed(
    synthetic_cfg_image,
):
    limits = generous_limits(synthetic_cfg_image)
    with pytest.raises(CfgRecoveryError, match="instruction interior"):
        recover_cfg(
            synthetic_cfg_image,
            (0x00401003, 0x00401004),
            limits,
        )
    with pytest.raises(CfgRecoveryError, match="not executable"):
        recover_cfg(synthetic_cfg_image, (0x00409999,), limits)


@pytest.mark.parametrize(
    ("mutation", "target", "predecessor"),
    [
        ("late_backward_target", 0x00401001, 0x00401000),
        ("late_target_inside_owned_block", 0x00401046, 0x00401040),
    ],
)
def test_late_target_split_retains_predecessor_fallthrough(tmp_path, mutation, target, predecessor):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(block.start == target for block in cfg.blocks)
    assert any(
        edge.source == predecessor and edge.target == target and edge.kind == "fallthrough" for edge in cfg.edges
    )


@pytest.mark.parametrize(
    ("mutation", "forbidden_start"),
    [
        ("lea_is_not_data", 0x00401068),
        ("write_is_not_data", 0x00401068),
        ("control_operand_is_not_data", 0x004020A0),
    ],
)
def test_only_semantic_memory_reads_produce_data_evidence(tmp_path, mutation, forbidden_start):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(region.start <= forbidden_start < region.end for region in cfg.data_regions)


def test_absolute_iat_call_is_a_typed_terminal_external_edge(tmp_path):
    image = load_cfg_image(tmp_path, "control_operand_is_not_data")
    image = replace(
        image,
        imports=(
            pe.Import(
                dll="KERNEL32.dll",
                name="CloseHandle",
                ordinal=None,
                hint=28,
                iat_va=0x004020A0,
            ),
        ),
    )
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    edge = next(row for row in cfg.control_targets.terminal_external_edges if row.source == 0x00401070)
    assert (edge.flow_kind, edge.iat_va, edge.dll, edge.name) == (
        "call",
        0x004020A0,
        "KERNEL32.dll",
        "CloseHandle",
    )
    assert not any(row.address == 0x00401070 and row.kind == "indirect-flow" for row in cfg.ownership_diagnostics)


def test_relocated_internal_callback_escaping_to_an_import_blocks(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="external-code-pointer-escape")
    escape = next(row for row in cfg.control_targets.external_escapes if row.source == 0x00401005)
    assert escape.target_import_iat == 0x00402160
    assert escape.possible_internal_targets == (0x00401090,)
    assert any(
        row.address == 0x00401005 and row.kind == "external-code-pointer-escape"
        for row in cfg.control_targets.unresolved
    )


def test_reachable_global_initializer_proves_finite_slot_target(tmp_path):
    image = load_cfg_image(tmp_path, "global_callback_slot")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040107A and row.flow_kind == "indirect-jump-global-slot"
    )
    assert edge.target == 0x00401060
    assert "slot=0x4020a0" in edge.provenance
    assert not any(row.address == 0x0040107A and row.kind == "indirect-flow" for row in cfg.ownership_diagnostics)


def test_zero_initialized_bss_slot_accepts_reachable_finite_writes(tmp_path):
    image = load_cfg_image(tmp_path, "bss_global_callback_slot")
    sections = tuple(
        replace(section, raw_size=0x200, virt_size=0x1000) if section.name == ".rdata" else section
        for section in image.sections
    )
    image = replace(image, sections=sections)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040107A and row.flow_kind == "indirect-jump-global-slot"
    )
    assert edge.target == 0x00401060
    assert "slot=0x402300;initial=0x0" in edge.provenance


def test_cdecl_argument_write_proves_global_callback_target(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-cdecl-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040100B and row.flow_kind == "indirect-call-global-slot"
    )
    assert edge.target == 0x00401090
    assert "argument=0" in edge.provenance
    assert "caller=" not in edge.provenance


def test_pre_finite_revalidation_rejects_shrunk_global_slot_domain(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="global-cdecl-callback")
    evaluations = 0
    original = _DirectCfgRecovery._finite_global_slot_values

    def shrinking_domain(recovery, slot, visited):
        nonlocal evaluations
        if slot != 0x00402300:
            return original(recovery, slot, visited)
        evaluations += 1
        values = {0, 0x00401090}
        if evaluations == 1:
            values.add(0x00401030)
        return frozenset(values), "test-closed-global-domain"

    monkeypatch.setattr(
        _DirectCfgRecovery,
        "_finite_global_slot_values",
        shrinking_domain,
    )

    with pytest.raises(
        CfgRecoveryError,
        match="retained pre-finite control target became unsound",
    ):
        recover_cfg(
            image,
            build_seed_inventory(image, ()),
            generous_limits(image),
        )

    assert evaluations == 2


def test_finite_object_field_uses_reachable_runtime_writes(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="finite-object-runtime-field-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401038 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "global-slot=0x402404" in edge.provenance
    assert "fault-before-transfer=0x0" in edge.provenance


def test_finite_object_field_with_unknown_runtime_write_remains_blocking(
    tmp_path,
):
    cfg = dispatch_cfg(tmp_path, mode="finite-object-runtime-field-unknown-write")
    assert any(row.address == 0x00401038 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_global_descriptor_domain_proves_field_callback_target(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401035 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "global-slot=0x402300" in edge.provenance
    assert "fault-before-transfer=0x0" in edge.provenance


def test_ebp_can_hold_a_finite_descriptor_instead_of_a_frame(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-ebp-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x00401036 and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "field=+0x10" in edge.provenance
    assert "global-slot=0x402300" in edge.provenance


def test_loop_local_descriptor_reload_precedes_affine_reasoning(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-loop-reload-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103B and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "definition=0x401034" in edge.provenance
    assert "global-slot=0x402300" in edge.provenance


def test_loop_local_descriptor_reload_rejects_later_clobber(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-loop-reload-clobber")
    assert any(row.address == 0x0040103D and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_guarded_global_descriptor_survives_volatile_alias_block(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-guarded-alias-callback")
    edge = next(
        row
        for row in cfg.control_targets.finite_internal_edges
        if row.source == 0x0040103F and row.flow_kind == "indirect-call-finite-value"
    )
    assert edge.target == 0x00401090
    assert "global-slot=0x402300" in edge.provenance


def test_guarded_global_descriptor_rejects_volatile_alias_clobber(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-guarded-alias-clobber")
    assert any(row.address == 0x00401041 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_unknown_global_descriptor_write_remains_blocking(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="global-descriptor-unknown-write")
    assert any(row.address == 0x00401035 and row.kind == "indirect-flow" for row in cfg.control_targets.unresolved)


def test_reachable_object_callback_table_seeds_every_relocated_entry(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="object-callback-table")
    records = {(row.address, row.provenance_address, row.category) for row in cfg.seed_inventory.records}
    assert records >= {
        (0x00401090, 0x00402300, "object-callback-table-entry"),
        (0x004010A0, 0x00402304, "object-callback-table-entry"),
    }
    assert {row.address for row in cfg.function_entries} >= {0x00401090, 0x004010A0}
    assert any(row.start <= 0x00402300 and 0x0040230C <= row.end for row in cfg.data_regions)


def test_disjoint_fresh_receiver_write_does_not_open_object_field_domain(
    tmp_path,
):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    text = image.sections[0]
    unrelated_entry = text.va + text.raw_size
    data = bytearray(image.data)
    unrelated_offset = text.raw_offset + text.raw_size
    unrelated_program = bytes.fromhex(
        "53 68 18 01 00 00 6a 00 e8 b3 ff ff ff 89 c3 59 85 db 59 74 0c 8b 44 24 08 89 83 04 01 00 00 5b c3 31 c0 5b c3"
    )
    data[unrelated_offset : unrelated_offset + len(unrelated_program)] = unrelated_program
    expanded_text = replace(text, raw_size=0x180, virt_size=0x180)
    image = replace(
        image,
        data=bytes(data),
        sections=(expanded_text, *image.sections[1:]),
        executable_ranges=((text.va, text.va + 0x180),),
    )

    cfg = recover_cfg(
        image,
        (image.entrypoint, image.exports[0].va, unrelated_entry),
        generous_limits(image),
    )

    records = {row for row in cfg.seed_inventory.records if row.category == "object-callback-table-entry"}
    assert {row.address for row in records} == {0x00401090, 0x004010A0}
    assert all("receiver-disjoint=0x401119" in row.detail for row in records)


def test_same_receiver_unknown_write_keeps_object_field_domain_open(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="object-callback-table-unknown-overlap")

    assert not {row.address for row in cfg.seed_inventory.records if row.category == "object-callback-table-entry"}


def test_certified_object_callback_closes_copied_argument_domain(tmp_path):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()

    assert recovery._argument_has_copied_descriptor_origin(
        0x004010A0,
        0,
        0x00401090,
        frozenset({0x00402400}),
        frozenset(),
    )


def test_certified_callback_copy_origin_survives_global_slot(tmp_path):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()

    assert recovery._argument_has_copy_constructor_origin(
        0x004010A0,
        0,
        0x00401090,
        frozenset(),
    )
    assert recovery._argument_has_copy_constructor_origin(
        0x004010C0,
        0,
        0x00401090,
        frozenset(),
    )


def test_global_copy_origin_rejects_noncopy_writer(tmp_path):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    data = bytearray(image.data)
    offset = image.va_to_offset(0x004010C0)
    assert offset is not None
    data[offset : offset + 11] = bytes.fromhex("c7 05 00 25 40 00 00 24 40 00 c3")
    image = replace(
        image,
        data=bytes(data),
        relocations=(*image.relocations, pe.Relocation(0x004010C2, 3)),
    )
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()

    assert not recovery._global_slot_has_copy_constructor_origin(0x00402500, 0x00401090, frozenset())


def test_global_copy_origin_rejects_unowned_reference(tmp_path):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    reference = 0x00402510
    data = bytearray(image.data)
    offset = image.va_to_offset(reference)
    assert offset is not None
    struct.pack_into("<I", data, offset, 0x00402500)
    image = replace(
        image,
        data=bytes(data),
        relocations=(*image.relocations, pe.Relocation(reference, 3)),
    )
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()

    assert not recovery._global_slot_has_copy_constructor_origin(0x00402500, 0x00401090, frozenset())


def test_proven_copied_argument_domain_is_reused(tmp_path, monkeypatch):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()
    arguments = (
        0x004010A0,
        0,
        0x00401090,
        frozenset({0x00402400}),
        frozenset(),
    )
    assert recovery._argument_has_copied_descriptor_origin(*arguments)

    def reject_rescan(_function_entry):
        raise AssertionError("proven copied argument domain was rescanned")

    monkeypatch.setattr(recovery, "_incoming_call_sites", reject_rescan)
    assert recovery._argument_has_copied_descriptor_origin(*arguments)


def test_unaccepted_callback_reference_keeps_argument_domain_open(tmp_path):
    image = load_dispatch_image(tmp_path, mode="object-callback-table")
    cfg = recover_cfg(image, build_seed_inventory(image, ()), generous_limits(image))
    data = bytearray(image.data)
    extra_reference = 0x00402310
    offset = image.va_to_offset(extra_reference)
    assert offset is not None
    struct.pack_into("<I", data, offset, 0x004010A0)
    image = replace(
        image,
        data=bytes(data),
        relocations=(
            *image.relocations,
            pe.Relocation(extra_reference, 3),
        ),
    )
    recovery = _DirectCfgRecovery(image, cfg.seed_inventory, generous_limits(image))
    recovery.recover()

    assert not recovery._argument_has_copied_descriptor_origin(
        0x004010A0,
        0,
        0x00401090,
        frozenset({0x00402400}),
        frozenset(),
    )


@pytest.mark.parametrize(
    "mode",
    (
        "object-callback-table-no-dispatch",
        "object-callback-table-unreachable-store",
        "object-callback-table-unknown-source",
        "object-callback-table-isolated",
        "object-callback-table-missing-terminator",
        "object-callback-table-relocated-terminator",
        "object-callback-table-interior-target",
        "object-callback-table-unknown-overlap",
        "object-callback-table-late-rmw",
    ),
)
def test_relocated_executable_run_without_owned_exact_object_store_is_not_code(tmp_path, mode):
    cfg = dispatch_cfg(tmp_path, mode=mode)
    assert not {row.address for row in cfg.seed_inventory.records if row.category == "object-callback-table-entry"}
    unproven_entry = 0x00401091 if mode == "object-callback-table-interior-target" else 0x00401090
    assert unproven_entry not in {row.address for row in cfg.function_entries}


def test_late_rmw_cannot_leave_a_stale_object_dispatch_proof(tmp_path):
    cfg = dispatch_cfg(tmp_path, mode="object-callback-table-late-rmw")
    assert any(
        row.address == 0x00401034 and row.kind == "object-callback-table-blocker"
        for row in cfg.control_targets.unresolved
    )
    assert any(
        row.source == 0x0040106A and row.flow_kind == "indirect-call-finite-value" and row.target == 0x004010A0
        for row in cfg.control_targets.finite_internal_edges
    )
    assert 0x00401090 not in {row.address for row in cfg.instructions}
    assert not any(row.source == 0x00401090 for row in cfg.control_targets.finite_internal_edges)


def test_data_evidence_cannot_overlap_instruction_or_padding(tmp_path):
    image = load_cfg_image(tmp_path, "data_overlaps_instruction")
    with pytest.raises(CfgRecoveryError, match="ownership overlap"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_partial_width_relocation_does_not_prove_executable_pointer(tmp_path):
    image = load_cfg_image(tmp_path, "partial_relocation_pointer")
    seeds = inventory(image)
    assert not any(row.category == "relocation-executable-pointer" for row in seeds.records)


def test_executable_relocation_crossing_operand_boundary_fails(tmp_path):
    image = load_cfg_image(tmp_path, "exec_relocation_partial_field")
    with pytest.raises(CfgRecoveryError, match="relocation.*boundary"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_executable_highlow_conflicting_data_boundaries_fail_closed(tmp_path):
    image = load_cfg_image(tmp_path, "exec_relocation_data_slot_conflicting_refs")
    with pytest.raises(CfgRecoveryError, match="data boundary is ambiguous.*attributions=2"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_final_relocation_dispositions_distinguish_instruction_typed_and_residue(
    tmp_path,
):
    instruction_image = load_cfg_image(tmp_path, "exec_relocation_immediate")
    instruction_cfg = recover_cfg(
        instruction_image,
        inventory(instruction_image),
        generous_limits(instruction_image),
    )
    assert any(
        row.source_address == 0x0040100B
        and row.status == "owned-instruction-operand"
        and row.source_class == "instruction"
        for row in instruction_cfg.relocation_dispositions
    )

    typed_image = load_cfg_image(tmp_path, "exec_relocation_data_slot_consistent_refs")
    typed_cfg = recover_cfg(typed_image, inventory(typed_image), generous_limits(typed_image))
    assert any(
        row.source_address == 0x00401080
        and row.status == "unresolved-exec-pointer"
        and row.source_class == "unique-typed-data-boundary"
        for row in typed_cfg.relocation_dispositions
    )

    residue_image = load_cfg_image(tmp_path, "exec_relocation_aligned_prologue")
    residue_cfg = recover_cfg(
        residue_image,
        inventory(residue_image),
        generous_limits(residue_image),
    )
    assert any(
        row.source_address == 0x00401035 and row.status == "residue-nonexec-address" and row.source_class == "residue"
        for row in residue_cfg.relocation_dispositions
    )


@pytest.mark.parametrize("mutation", ["transformed_initializer", "cross_block_initializer_value"])
def test_executable_initializer_taint_never_silently_disappears(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_initializer_store",
        "xchg_initializer_store",
        "push_initializer_value",
        "stos_initializer_value",
    ],
)
def test_unsupported_memory_write_of_executable_value_fails_closed(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "full_load_clobbers_initializer_value",
        "zeroing_clobbers_initializer_value",
        "call_clobbers_caller_saved_initializer_value",
    ],
)
def test_full_independent_write_or_call_clobber_kills_initializer_taint(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(
        row.category == "function-pointer-initializer" and 0x0040100A <= row.provenance_address < 0x00401020
        for row in cfg.seed_inventory.records
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_clobber_retains_initializer_taint",
        "call_preserves_callee_saved_initializer_taint",
    ],
)
def test_partial_write_and_callee_saved_call_retain_unsafe_taint(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_register_lea_initializer",
        "register_xchg_initializer",
        "partial_register_copy_initializer",
        "cmov_initializer",
        "arithmetic_cross_register_initializer",
        "vector_register_initializer",
    ],
)
def test_register_transform_retains_unsafe_initializer_taint(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_shrd_implicit_cl_read_preserves_initializer_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "bb 50 10 40 00 0f ad fb 89 1d 90 20 40 00 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_capstone_semantic_contract_is_pinned_before_recovery(synthetic_cfg_image, monkeypatch):
    monkeypatch.setattr(capstone, "__version__", "5.0.7-audited-drift")
    with pytest.raises(CfgRecoveryError, match="Capstone audit contract"):
        recover_cfg(
            synthetic_cfg_image,
            inventory(synthetic_cfg_image),
            generous_limits(synthetic_cfg_image),
        )


@pytest.mark.parametrize(
    ("encoded", "instruction_id", "operand_access", "register_reads"),
    [
        ("0f f7 c1", 376, (1, 1), ("edi",)),
        ("66 0f f7 c1", 359, (1, 1), ("edi",)),
        ("c5 f9 f7 c1", 1004, (1, 1), ("edi",)),
        ("0f ae 01", 212, (2,), ()),
        ("dd 31", 204, (2,), ()),
        ("dd 19", 714, (1,), ()),
        ("0f ae 21", 1511, (2,), ("rdx", "rax")),
        ("0f 38 f6 08", 1485, (0, 0), ()),
        ("66 0f 38 f5 08", 1487, (0, 0), ()),
        ("0f 7e 00", 377, (1, 1), ()),
        ("0f 11 00", 495, (1, 1), ()),
        ("c5 fc 11 00", 1051, (1, 1), ()),
        ("c4 e2 75 2e 00", 1006, (1, 1, 1), ()),
        ("c4 e2 75 8e 00", 1230, (1, 1, 1), ()),
        ("62 f2 7d 49 a2 04 88", 1440, (1, 1, 0), ()),
        ("62 f2 7d 49 a0 04 88", 1317, (1, 1, 0), ()),
    ],
)
def test_audited_capstone_writer_metadata_contract(encoded, instruction_id, operand_access, register_reads):
    decoder, decoded = decode_one(encoded)
    assert decoded.id == instruction_id
    assert tuple(operand.access for operand in decoded.operands) == operand_access
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_read) == (register_reads)


@pytest.mark.parametrize(
    (
        "encoded",
        "instruction_id",
        "mnemonic",
        "operand_registers",
        "operand_access",
        "register_reads",
        "register_writes",
    ),
    [
        ("d9 c1", 331, "fld", ("st(1)",), (1,), (), ("fpsw",)),
        (
            "d9 c9",
            1494,
            "fxch",
            ("st(0)", "st(1)"),
            (1, 0),
            (),
            ("fpsw",),
        ),
        ("dd d1", 713, "fst", ("st(1)",), (1,), (), ("fpsw",)),
        ("dd d9", 714, "fstp", ("st(1)",), (2,), (), ("fpsw",)),
        ("d8 c1", 15, "fadd", ("st(1)",), (1,), (), ()),
        ("de c1", 15, "faddp", ("st(1)",), (1,), (), ()),
    ],
)
def test_audited_capstone_hidden_x87_stack_metadata_contract(
    encoded,
    instruction_id,
    mnemonic,
    operand_registers,
    operand_access,
    register_reads,
    register_writes,
):
    decoder, decoded = decode_one(encoded)
    assert decoded.id == instruction_id
    assert decoded.mnemonic == mnemonic
    assert tuple(decoder.reg_name(op.reg) for op in decoded.operands) == (operand_registers)
    assert tuple(op.access for op in decoded.operands) == operand_access
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_read) == (register_reads)
    assert tuple(decoder.reg_name(reg) for reg in decoded.regs_write) == (register_writes)


@pytest.mark.parametrize(
    "program",
    [
        # A tainted base is an address, not the loaded payload.
        "bb 50 10 40 00 81 c3 00 10 00 00 8b 03 a3 90 20 40 00 c3",
        # A tainted store address does not taint a clean payload.
        "bb 50 10 40 00 31 c0 89 03 c3",
        # STOS consumes EAX, not its EDI destination address.
        "bf 50 10 40 00 31 c0 ab c3",
        # MOVS copies a fresh memory value; ESI is only its source address.
        "be 50 10 40 00 81 c6 00 10 00 00 a5 c3",
        # LODS loads a fresh value even when its source address is tainted.
        "be 50 10 40 00 81 c6 00 10 00 00 ad a3 90 20 40 00 c3",
        # XCHG moves the clean old EAX into EBX positionally.
        "bb 50 10 40 00 31 c0 87 d8 89 1d 90 20 40 00 c3",
        # MASKMOVQ's mask operand is not the stored payload.
        "b8 50 10 40 00 0f 6e c8 0f f7 c1 c3",
        # VMASKMOVDQU's mask operand is not the stored payload.
        "b8 50 10 40 00 66 0f 6e c8 c5 f9 f7 c1 c3",
        # Masked stores do not store their mask register.
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 75 2e 01 c3",
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 75 8e 01 c3",
        # Scatter index registers are addresses, not payload.
        "b8 50 10 40 00 66 0f 6e c8 62 f2 7d 49 a2 04 89 c3",
        # INS consumes DX as a port selector, not a stored payload.
        "ba 50 10 40 00 6d c3",
        # MOVDIR64B consumes EAX as a destination address.
        "b8 50 10 40 00 66 0f 38 f8 00 c3",
        # OUTS targets an I/O port and gather only reads memory.
        "be 50 10 40 00 6f c3",
        "b8 50 10 40 00 66 0f 6e c8 c4 e2 6d 90 04 89 c3",
    ],
)
def test_address_mask_and_protocol_dependencies_are_not_payloads(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Implicit MASKMOV destinations.
        "b8 50 10 40 00 0f 6e c0 0f f7 c1 c3",
        "b8 50 10 40 00 66 0f 6e c0 66 0f f7 c1 c3",
        "b8 50 10 40 00 66 0f 6e c0 c5 f9 f7 c1 c3",
        # ENTER pushes the old EBP value.
        "bd 50 10 40 00 c8 00 00 00 c3",
        # State saves contain hidden MMX/x87/vector payloads.
        "b8 50 10 40 00 0f 6e c0 dd 31 c3",
        "b8 50 10 40 00 0f 6e c0 dd 19 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f ae 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f ae 21 c3",
        # CET stores have access=0 for both operands.
        "b9 50 10 40 00 31 c0 0f 38 f6 08 c3",
        "b9 50 10 40 00 31 c0 66 0f 38 f5 08 c3",
        # Representative legacy and VEX access-metadata defects.
        "b8 50 10 40 00 0f 6e c0 0f 7e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 11 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 c5 fc 11 01 c3",
        # Masked and scatter stores consume operand 2, not their masks/VSIB.
        "b8 50 10 40 00 66 0f 6e c0 c4 e2 75 2e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 c4 e2 75 8e 01 c3",
        "b8 50 10 40 00 66 0f 6e c0 62 f2 7d 49 a2 04 89 c3",
        "b8 50 10 40 00 66 0f 6e c0 62 f2 7d 49 a0 04 89 c3",
    ],
)
def test_semantic_memory_writers_reject_only_tainted_payload(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Full GPR/vector loads replace every written lane.
        "b8 50 10 40 00 8b 01 a3 90 20 40 00 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 10 01 0f 11 01 c3",
        # Vector zero idiom clears the full destination.
        "b8 50 10 40 00 66 0f 6e c0 66 0f ef c0 0f 11 01 c3",
        # A VEX XMM write also clears the upper YMM alias lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 c5 f8 10 01 c5 fc 11 01 c3",
        # FXSAVE stores XMM state, not the untouched upper YMM lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 66 0f ef c0 0f ae 01 c3",
        # Register XADD places the clean old destination in its source.
        "bb 50 10 40 00 31 c0 0f c1 d8 89 1d 90 20 40 00 c3",
        # POP replaces the full destination with a fresh stack value.
        "b8 50 10 40 00 58 a3 90 20 40 00 c3",
        # A state-save address by itself is not saved payload.
        "b9 50 10 40 00 dd 31 c3",
    ],
)
def test_full_lane_replacements_and_address_only_state_are_clean(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Partial GPR/vector loads preserve untouched tainted lanes.
        "b8 50 10 40 00 8a 01 a3 90 20 40 00 c3",
        "b8 50 10 40 00 66 0f 6e c0 0f 12 01 0f 11 01 c3",
        # A legacy XMM write preserves upper YMM lanes.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 0f 10 01 c5 fc 11 01 c3",
        # CMOV can preserve its old destination.
        "b8 50 10 40 00 31 db 85 c9 0f 45 c3 a3 90 20 40 00 c3",
        # PUSH immediate, PUSHA, and PUSHF store their real payloads.
        "68 50 10 40 00 c3",
        "bb 50 10 40 00 60 c3",
        "b8 50 10 40 00 83 c0 00 9c c3",
        # XADD/CMPXCHG memory forms conditionally store the source value.
        "b8 50 10 40 00 0f c1 01 c3",
        "b9 50 10 40 00 0f b1 0b c3",
        # XSAVE can store upper YMM/ZMM state selected at runtime.
        "b8 50 10 40 00 62 f2 7d 28 7c c0 66 0f ef c0 0f ae 21 c3",
    ],
)
def test_partial_conditional_and_stack_payloads_remain_tainted(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_wide_cmpxchg_failure_arm_preserves_accumulator_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f c7 0f a3 90 20 40 00 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize("instruction", ["87 c0", "0f c1 c0"])
def test_aliased_exchange_outputs_retain_old_accumulator_taint(tmp_path, instruction):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 {instruction} a3 90 20 40 00 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_cmpxchg_destination_aliasing_accumulator_uses_source_value(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 31 db 0f b1 d8 a3 90 20 40 00 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # Source aliases the accumulator: either architectural arm can retain it.
        "b8 50 10 40 00 31 db 0f b1 c3 a3 90 20 40 00 c3",
        # Source aliases the destination: the destination remains unchanged.
        "bb 50 10 40 00 31 c0 0f b1 db 89 1d 90 20 40 00 c3",
        # The high-byte source partially aliases the implicit AL accumulator.
        "b8 50 10 40 00 31 db 0f b0 e3 89 1d 90 20 40 00 c3",
    ],
)
def test_cmpxchg_source_destination_and_partial_aliases_join_taint(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize("fld", ["d9 c1", "66 d9 c1", "2e d9 c1"])
def test_fld_register_pushes_hidden_x87_stack_value(tmp_path, fld):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 0f 6e c8 {fld} dd 19 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # FXCH moves the tainted ST(1) value to the memory-visible top.
        "b8 50 10 40 00 0f 6e c8 d9 c9 dd 19 c3",
        # FST copies ST(0) into ST(1) even though Capstone marks it read-only.
        "b8 50 10 40 00 0f 6e c0 dd d1 dd c0 d9 c9 dd 19 c3",
        # FLD shifts a tainted ST(1) to ST(2), then arithmetic consumes it.
        "b8 50 10 40 00 0f 6e c8 d9 e8 d8 c2 dd 19 c3",
        # FADDP writes its hidden destination before popping the x87 stack.
        "b8 50 10 40 00 0f 6e c0 d9 e8 de c1 dd 19 c3",
        # The implicit ST(0) arithmetic input is not reported as an operand.
        "b8 50 10 40 00 0f 6e c0 de c1 dd 19 c3",
    ],
)
def test_x87_swap_store_and_arithmetic_stack_forms_preserve_taint(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_clean_fstp_register_copy_and_pop_is_fully_modeled(tmp_path):
    image = load_cfg_program(tmp_path, "d9 e8 dd d9 dd 19 c3")
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # FLDENV changes control/TOP state but does not overwrite data registers.
        "b8 50 10 40 00 0f 6e c0 d9 21 0f 7e c0 a3 90 20 40 00 c3",
        # EMMS changes tags; the aliased MMX payload remains architecturally present.
        "b8 50 10 40 00 0f 6e c0 0f 77 0f 7e c0 a3 90 20 40 00 c3",
        # FFREE changes a tag; it does not erase the aliased physical payload.
        "b8 50 10 40 00 0f 6e c0 dd c0 0f 7e c0 a3 90 20 40 00 c3",
        # An x87 push into physical slot 7 cannot erase unrelated MM6.
        "b8 50 10 40 00 0f 6e f0 d9 e8 0f 7e f0 a3 90 20 40 00 c3",
    ],
)
def test_x87_stack_and_tag_updates_preserve_mmx_physical_alias_taint(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fldenv_top_ambiguity_cannot_hide_physical_mmx_taint(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 d9 21 dd 19 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_tainted_x87_mutation_with_unknown_top_has_canonical_diagnostic(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d9 21 d9 e8 c3",
    )
    with pytest.raises(
        CfgRecoveryError,
        match=(
            r"address=0x401014;bytes=d9e8;id=330;mnemonic=fld1;"
            r"operands=;reason=ambiguous x87 TOP with tainted physical "
            r"payload: effect=push;top-mask=0xff;valid-must=0x00;"
            r"valid-may=0xff"
        ),
    ):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fst_logical_destination_does_not_clear_unrelated_physical_mmx(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 0f 77 d9 e8 dd d1 0f 7e c8 89 02 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_clean_fld1_fstp_does_not_store_stale_physical_mmx_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 0f 77 d9 e8 dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_ffree_empty_logical_value_does_not_erase_physical_mmx_payload(
    tmp_path,
):
    clean_logical_store = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 dd c0 d9 e8 dd 19 c3",
    )
    recover_cfg(
        clean_logical_store,
        inventory(clean_logical_store),
        generous_limits(clean_logical_store),
    )

    physical_read = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 dd c0 d9 e8 dd 19 0f 7e c0 89 02 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(
            physical_read,
            inventory(physical_read),
            generous_limits(physical_read),
        )


@pytest.mark.parametrize("restore", ["dd 21", "0f ae 09"])
def test_fresh_x87_state_restore_clears_physical_payload_taint(tmp_path, restore):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 0f 6e c0 {restore} dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_fxrstor_replaces_low_xmm_lanes_but_not_upper_vector_lanes(tmp_path):
    restored_xmm = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 66 0f 6e c0 0f ae 09 0f 11 02 c3",
    )
    recover_cfg(
        restored_xmm,
        inventory(restored_xmm),
        generous_limits(restored_xmm),
    )

    retained_upper_ymm = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 62 f2 7d 28 7c c0 0f ae 09 c5 fc 11 02 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(
            retained_upper_ymm,
            inventory(retained_upper_ymm),
            generous_limits(retained_upper_ymm),
        )


@pytest.mark.parametrize("restore", ["dd 21", "0f ae 29"])
def test_other_state_restores_do_not_overclear_vector_state(tmp_path, restore):
    image = load_cfg_program(
        tmp_path,
        f"b8 50 10 40 00 66 0f 6e c0 {restore} 0f 11 02 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_full_mmx_replacement_overwrites_aliased_x87_sign_exponent(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d8 c0 0f ef c0 0f ae 01 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_full_mmx_replacement_propagates_tainted_low_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 d8 c0 0f 6e c0 0f ae 01 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_x87_state_save_sinks_stale_physical_payload_after_emms(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 0f 77 dd 31 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_fldenv_with_clean_physical_state_keeps_logical_stores_clean(tmp_path):
    image = load_cfg_program(tmp_path, "d9 21 d9 e8 dd 19 c3")
    recover_cfg(image, inventory(image), generous_limits(image))


@pytest.mark.parametrize(
    "program",
    [
        # One predecessor increments TOP, so ST(0) can resolve physical MM1.
        "b8 50 10 40 00 0f 6e c8 85 c0 74 02 d9 f7 dd 19 c3",
        # One predecessor empties tags while the other keeps MM0 valid.
        "b8 50 10 40 00 0f 6e c0 85 c0 74 02 0f 77 dd 19 c3",
    ],
)
def test_cfg_join_unions_top_and_may_tags_for_relevant_taint(tmp_path, program):
    image = load_cfg_program(tmp_path, program)
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_cfg_join_with_differing_clean_top_and_tags_is_not_a_pointer_blocker(
    tmp_path,
):
    image = load_cfg_program(
        tmp_path,
        "31 c0 85 c0 74 02 d9 f7 d9 e8 dd 19 c3",
    )
    recover_cfg(image, inventory(image), generous_limits(image))


def test_call_retains_physical_taint_and_invalidates_logical_control(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 e8 04 00 00 00 dd 19 c3 90 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_finit_resets_top_and_tags_but_retains_physical_payload(tmp_path):
    image = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c0 db e3 d9 e8 dd 19 0f 7e c0 89 02 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unresolved function-pointer initializer"):
        recover_cfg(image, inventory(image), generous_limits(image))


def test_unknown_hidden_x87_stack_form_blocks_only_relevant_taint(tmp_path):
    tainted = load_cfg_program(
        tmp_path,
        "b8 50 10 40 00 0f 6e c8 d9 f8 c3",
    )
    with pytest.raises(CfgRecoveryError, match="unmodeled x87 stack effect"):
        recover_cfg(tainted, inventory(tainted), generous_limits(tainted))

    clean = load_cfg_program(tmp_path, "d9 f8 c3")
    recover_cfg(clean, inventory(clean), generous_limits(clean))


def test_entry_export_and_anchor_bind_to_complete_first_instruction(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    export = next(row for row in cfg.seed_inventory.records if row.category == "export")
    assert export.provenance_bytes == "dd0580104000"

    prefix_anchor = AuditAnchor(
        name="prefix-anchor",
        address=0x00401001,
        instruction_bytes=synthetic_cfg_image.read(0x00401001, 1),
        evidence="synthetic-fixture",
    )
    with pytest.raises(CfgRecoveryError, match="complete instruction"):
        recover_cfg(
            synthetic_cfg_image,
            build_seed_inventory(synthetic_cfg_image, (prefix_anchor,)),
            generous_limits(synthetic_cfg_image),
        )


@pytest.mark.parametrize(
    "cap_name",
    [
        "max_instructions",
        "max_blocks",
        "max_edges",
        "max_functions",
        "max_finite_targets",
        "max_finite_values",
        "max_states_per_block",
        "max_fixpoint_updates",
        "max_summary_iterations",
    ],
)
def test_recover_cfg_enforces_every_task3_production_cap(synthetic_cfg_image, cap_name):
    limits = replace(generous_limits(synthetic_cfg_image), **{cap_name: 1})
    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(synthetic_cfg_image, inventory(synthetic_cfg_image), limits)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == 1
    assert raised.value.observed >= 1


def test_high_water_marks_cover_all_caps_and_zero_only_deferred_dimensions(
    synthetic_cfg_image,
):
    cfg = recover_cfg(
        synthetic_cfg_image,
        inventory(synthetic_cfg_image),
        generous_limits(synthetic_cfg_image),
    )
    high_water = {row.limit_name: row.observed for row in cfg.high_water_marks}
    assert set(high_water) == {field.name for field in fields(AnalysisLimits)}
    assert high_water["max_finite_values"] > 0
    assert high_water["max_states_per_block"] == 8
    assert high_water["max_fixpoint_updates"] > 0
    assert high_water["max_summary_iterations"] > 0
    for deferred in (
        "max_jump_tables",
        "max_jump_table_entries",
        "max_contexts_per_entry",
        "max_scc_iterations",
    ):
        assert high_water[deferred] == 0


@pytest.mark.parametrize(
    "cap_name",
    [
        "max_jump_tables",
        "max_jump_table_entries",
        "max_contexts_per_entry",
        "max_scc_iterations",
    ],
)
def test_recover_cfg_rejects_zero_cap_for_unobserved_dimension(synthetic_cfg_image, cap_name):
    limits = replace(generous_limits(synthetic_cfg_image), **{cap_name: 0})
    with pytest.raises(AnalysisLimitError) as raised:
        recover_cfg(synthetic_cfg_image, inventory(synthetic_cfg_image), limits)
    assert raised.value.limit_name == cap_name
    assert raised.value.configured == 0
    assert raised.value.observed == 0


@pytest.mark.parametrize("mutation", ["far_call", "far_jump"])
def test_far_control_transfer_is_unresolved_not_direct(tmp_path, mutation):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert not any(call.address == 0x00401070 for call in cfg.direct_calls)
    assert not any(
        edge.source == 0x00401070
        and edge.kind
        in {
            "direct-call",
            "conditional-branch",
            "unconditional-branch",
        }
        for edge in cfg.edges
    )
    assert any(row.address == 0x00401070 and row.kind == "unsupported-far-flow" for row in cfg.ownership_diagnostics)


def test_decode_lookahead_is_bounded_by_executable_raw_tail(
    synthetic_cfg_image,
):
    text = synthetic_cfg_image.sections[0]
    tail_address = text.va + text.raw_size - 1
    raw_tail = text.raw_offset + text.raw_size - 1
    data = bytearray(synthetic_cfg_image.data)
    data[raw_tail] = 0xC3
    tail_section = replace(
        text,
        va=tail_address,
        raw_offset=raw_tail,
        raw_size=1,
        virt_size=0x10,
    )
    tail_image = replace(
        synthetic_cfg_image,
        data=bytes(data),
        entrypoint=tail_address,
        sections=(tail_section, *synthetic_cfg_image.sections[1:]),
        exports=(),
        relocations=(),
        executable_ranges=((tail_address, tail_address + 0x10),),
    )
    cfg = recover_cfg(tail_image, (tail_address,), generous_limits(tail_image))
    assert [(row.address, row.size) for row in cfg.instructions] == [(tail_address, 1)]


def test_padding_gap_is_partitioned_around_proven_data(tmp_path):
    image = load_cfg_image(tmp_path, "padding_partitioned_by_data")
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    assert any(region.start == 0x00401068 and region.end == 0x0040106C for region in cfg.data_regions)
    assert any(region.start == 0x00401061 and region.end == 0x00401068 for region in cfg.padding_regions)
    assert any(region.start == 0x0040106C and region.end == 0x00401070 for region in cfg.padding_regions)


def test_audit_anchor_requires_exact_instruction_byte_provenance(
    synthetic_cfg_image,
):
    anchor = AuditAnchor(
        name="bad-anchor",
        address=0x00401070,
        instruction_bytes=b"\x90",
        evidence="synthetic-fixture",
    )
    with pytest.raises(CfgRecoveryError, match="audit anchor bytes differ"):
        build_seed_inventory(synthetic_cfg_image, (anchor,))


def test_raw_relocations_never_create_authoritative_roots(
    synthetic_cfg_image,
):
    seeds = build_seed_inventory(synthetic_cfg_image, ())
    assert {row.category for row in seeds.records} <= {
        "entrypoint",
        "export",
        "loader-callback",
        "crt-callback",
        "unwind-callback",
    }
    assert not any(row.category == "relocation-executable-pointer" for row in seeds.records)


@pytest.mark.parametrize(
    ("mutation", "residue_address"),
    [
        ("closed_unreachable_island", 0x00401061),
        ("closed_unreferenced_aligned_function", 0x00401030),
        ("exec_relocation_aligned_prologue", 0x00401030),
    ],
)
def test_syntactically_closed_or_relocated_residue_never_becomes_code(
    tmp_path,
    mutation,
    residue_address,
):
    image = load_cfg_image(tmp_path, mutation)
    cfg = recover_cfg(image, inventory(image), generous_limits(image))
    forbidden = {
        "relocation-aligned-entry",
        "relocation-computed-transfer",
        "relocation-inline-data-successor",
        "closed-executable-island",
        "closed-aligned-function",
    }
    assert not forbidden & {row.category for row in cfg.seed_inventory.records}
    assert all("terminal-noninstruction-separator" not in row.provenance for row in cfg.data_regions)
    assert cfg.provisional_unreachable_residue.contains(residue_address)


def test_atomic_jsonl_is_canonical_and_has_final_newline(synthetic_cfg_image, tmp_path):
    limits = generous_limits(synthetic_cfg_image)
    a = recover_cfg(
        synthetic_cfg_image,
        (0x00401000, 0x00401040, 0x00401070),
        limits,
    )
    b = recover_cfg(
        synthetic_cfg_image,
        (0x00401070, 0x00401040, 0x00401000),
        limits,
    )
    path = tmp_path / "cfg.jsonl"
    write_jsonl_atomic(path, a)
    first = path.read_bytes()
    write_jsonl_atomic(path, b)
    assert path.read_bytes() == first
    assert first.endswith(b"\n")
    rows = [json.loads(line) for line in first.splitlines()]
    keys = [(row["address"], row["record_kind"], row.get("target", -1)) for row in rows]
    assert keys == sorted(keys)
    rendered = first.decode("utf-8")
    assert "elapsed" not in rendered
    assert "timestamp" not in rendered
    assert str(tmp_path) not in rendered
