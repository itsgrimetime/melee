import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))
from retro_pe_fixture import write_synthetic_pe  # noqa: E402
from tools.mwcc_retro import pe  # noqa: E402

EXE_11 = REPO / "build/compilers/GC/1.1/mwcceppc.exe"
EXE_125N = REPO / "build/compilers/GC/1.2.5n/mwcceppc.exe"
EXPECTED_125N_SHA256 = (
    "ccf4b465cec73b5aae9c5c5543dcf8cda8a62aba246f89e2e0b200d742f2e55c"
)


@pytest.fixture
def strict_image(tmp_path):
    path = write_synthetic_pe(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pe.load(
        path,
        expected_sha256=digest,
        require_pe32_i386=True,
    )


def test_strict_pe_exposes_canonical_metadata(strict_image):
    assert strict_image.machine == 0x14C
    assert strict_image.optional_magic == 0x10B
    assert strict_image.entrypoint == 0x00401000
    assert strict_image.executable_ranges == ((0x00401000, 0x00401200),)
    assert [
        (entry.dll, entry.name, entry.ordinal, entry.hint, entry.iat_va)
        for entry in strict_image.imports
    ] == [("KERNEL32.dll", "ExitProcess", None, 0, 0x00402160)]
    assert [
        (entry.name, entry.ordinal, entry.va, entry.forwarded_to)
        for entry in strict_image.exports
    ] == [("fixture_export", 1, 0x00401010, None)]
    assert [
        (entry.va, entry.type) for entry in strict_image.relocations
    ] == [(0x00401010, 3)]


def test_strict_pe_requires_exact_lowercase_hash(tmp_path):
    path = write_synthetic_pe(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert pe.load(path, expected_sha256=digest).sha256 == digest

    with pytest.raises(ValueError, match="PE SHA-256 mismatch"):
        pe.load(path, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        pe.load(path, expected_sha256=digest.upper())


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("wrong_machine", "PE machine must be i386"),
        ("wrong_magic", "optional header must be PE32"),
        ("overlap_raw", "overlapping PE raw sections"),
        ("overlap_virtual", "overlapping PE virtual sections"),
        ("truncated_directory", "truncated PE data directory"),
    ],
)
def test_strict_pe_rejects_malformed_images(tmp_path, mutation, message):
    path = write_synthetic_pe(tmp_path, mutation=mutation)
    with pytest.raises(ValueError, match=message):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_rejects_unmapped_directory(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="invalid_directory")
    with pytest.raises(ValueError, match="PE data directory is not wholly mapped"):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_accepts_empty_export_tables(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="empty_exports")
    image = pe.load(path, require_pe32_i386=True)
    assert image.exports == ()


def test_strict_pe_rejects_forwarder_terminating_outside_directory(tmp_path):
    path = write_synthetic_pe(
        tmp_path, mutation="forwarder_outside_directory"
    )
    with pytest.raises(ValueError, match="unterminated PE export forwarder"):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_rejects_unterminated_iat(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="unterminated_iat")
    with pytest.raises(ValueError, match="unterminated PE import address table"):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_rejects_mismatched_import_table_lengths(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="mismatched_import_tables")
    with pytest.raises(
        ValueError, match="PE import lookup and address table lengths differ"
    ):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_rejects_unknown_i386_relocation_type(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="unknown_relocation_type")
    with pytest.raises(
        ValueError, match="unsupported i386 base relocation type"
    ):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_rejects_highadj_without_companion(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="missing_highadj_companion")
    with pytest.raises(ValueError, match="HIGHADJ relocation missing companion"):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_consumes_highadj_companion(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="valid_highadj")
    image = pe.load(path, require_pe32_i386=True)
    assert [(entry.va, entry.type) for entry in image.relocations] == [
        (0x00401010, 4)
    ]


def test_strict_pe_requires_full_highlow_target_width(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="highlow_at_last_byte")
    with pytest.raises(
        ValueError, match="PE base relocation target is not wholly mapped"
    ):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_deduplicates_canonical_records(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="duplicate_records")
    image = pe.load(path, require_pe32_i386=True)
    assert [
        (entry.dll, entry.name, entry.ordinal, entry.hint, entry.iat_va)
        for entry in image.imports
    ] == [("KERNEL32.dll", "ExitProcess", None, 0, 0x00402160)]
    assert [
        (entry.name, entry.ordinal, entry.va, entry.forwarded_to)
        for entry in image.exports
    ] == [("fixture_export", 1, 0x00401010, None)]
    assert [(entry.va, entry.type) for entry in image.relocations] == [
        (0x00401010, 3)
    ]


def test_strict_pe_import_sort_uses_original_dll_spelling(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="import_dll_case_tie")
    image = pe.load(path, require_pe32_i386=True)
    assert [entry.dll for entry in image.imports] == [
        "KERNEL32.dll",
        "kernel32.dll",
    ]


def test_strict_pe_rejects_unmapped_relocation_target(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="invalid_relocation")
    with pytest.raises(
        ValueError, match="PE base relocation target is not wholly mapped"
    ):
        pe.load(path, require_pe32_i386=True)


def test_strict_pe_rejects_truncated_section_table(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="truncated_section_table")
    with pytest.raises(ValueError, match="truncated PE section table"):
        pe.load(path, require_pe32_i386=True)


def test_read_rejects_short_cross_section_access(strict_image):
    section = strict_image.sections[0]
    with pytest.raises(ValueError, match="read is not wholly mapped"):
        strict_image.read(section.va + section.raw_size - 1, 2)


def test_headers_are_mapped_to_exact_file_bytes(strict_image):
    assert strict_image.va_to_offset(strict_image.image_base) == 0
    assert strict_image.offset_to_va(0x80) == strict_image.image_base + 0x80
    assert strict_image.read(strict_image.image_base, 2) == b"MZ"
    assert strict_image.read(strict_image.image_base + 0x80, 4) == b"PE\0\0"


def test_read_rejects_access_crossing_header_boundary(strict_image):
    with pytest.raises(ValueError, match="read is not wholly mapped"):
        strict_image.read(strict_image.image_base + 0x1FF, 2)


def test_strict_pe_rejects_virtual_section_overlapping_headers(tmp_path):
    path = write_synthetic_pe(tmp_path, mutation="overlap_headers")
    with pytest.raises(ValueError, match="PE virtual section overlaps headers"):
        pe.load(path, require_pe32_i386=True)


def test_real_compiler_strict_identity_and_executable_bounds():
    if not EXE_125N.exists():
        pytest.skip(f"{EXE_125N} not present")

    image = pe.load(
        EXE_125N,
        expected_sha256=EXPECTED_125N_SHA256,
        require_pe32_i386=True,
    )
    assert image.sha256 == EXPECTED_125N_SHA256
    assert image.machine == 0x14C
    assert image.optional_magic == 0x10B
    assert image.image_base == 0x00400000
    assert image.entrypoint == 0x00401000
    text = next(section for section in image.sections if section.name == ".text")
    assert text.characteristics & 0x20000000
    assert (text.va, text.va + max(text.raw_size, text.virt_size)) in (
        image.executable_ranges
    )


def test_image_base_and_sections():
    if not EXE_125N.exists():
        pytest.skip(f"{EXE_125N} not present")
    img = pe.load(EXE_125N)
    assert img.image_base == 0x400000
    names = [s.name for s in img.sections]
    assert ".text" in names and ".data" in names


def test_va_offset_roundtrip():
    if not EXE_125N.exists():
        pytest.skip(f"{EXE_125N} not present")
    img = pe.load(EXE_125N)
    off = img.va_to_offset(0x540BBC)
    assert off is not None
    assert img.offset_to_va(off) == 0x540BBC


def test_find_string_va_banner():
    if not EXE_125N.exists():
        pytest.skip(f"{EXE_125N} not present")
    img = pe.load(EXE_125N)
    vas = img.find_string_vas(b"Metrowerks C/C++ Compiler for Embedded PowerPC")
    assert 0x540BBC in vas


def test_push_imm32_sites_unique_for_iro_anchor():
    if not EXE_125N.exists():
        pytest.skip(f"{EXE_125N} not present")
    img = pe.load(EXE_125N)
    svas = img.find_string_vas(b"Dumping function %s after %s ")
    assert len(svas) == 1
    sites = img.push_imm32_sites(svas[0])
    assert len(sites) == 1


def test_data_drift_text_drift_between_versions():
    if not EXE_11.exists() or not EXE_125N.exists():
        pytest.skip("compiler binaries not present")
    a = pe.load(EXE_11)
    b = pe.load(EXE_125N)
    sa = a.find_string_vas(b"Dumping function %s after %s ")[0]
    sb = b.find_string_vas(b"Dumping function %s after %s ")[0]
    assert sb - sa == -0x1000
    pa = a.push_imm32_sites(sa)[0]
    pb = b.push_imm32_sites(sb)[0]
    assert pb - pa == 0x10
