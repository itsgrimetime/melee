import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_identity  # noqa: E402


def test_output_dir_includes_path_safe_unit_and_function_hash():
    out = backend_identity.output_dir_for(
        root=Path("/repo"),
        src="src/melee/mn/mndiagram.c",
        function="mnDiagram_UpdateScrollArrows",
        command="mwcceppc -c src/melee/mn/mndiagram.c",
    )
    text = out.as_posix()
    assert text.startswith("/repo/build/mwcc_retro/src_melee_mn_mndiagram-")
    assert "mnDiagram_UpdateScrollArrows-" in text


def test_identity_matches_aliases_not_runtime_address():
    identity = backend_identity.FunctionIdentity(
        requested="fn_80240000",
        canonical_name="mnDiagram_UpdateScrollArrows",
        symbol_name="mnDiagram_UpdateScrollArrows",
        source_name="mnDiagram_UpdateScrollArrows",
        aliases=("fn_80240000", "static_mnDiagram_UpdateScrollArrows"),
        source_file="src/melee/mn/mndiagram.c",
    )
    assert identity.matches("mnDiagram_UpdateScrollArrows")
    assert identity.matches("fn_80240000")
    assert not identity.matches("0x80240000")
    assert not identity.matches("0X80240000")


def test_identity_does_not_match_empty_optional_names():
    identity = backend_identity.FunctionIdentity(
        requested="fn_80240000",
        canonical_name="mnDiagram_UpdateScrollArrows",
        symbol_name=None,
        source_name=None,
        aliases=(),
        source_file="src/melee/mn/mndiagram.c",
    )
    assert not identity.matches("")


def test_path_slug_avoids_hidden_special_and_path_segments():
    for text in (".hidden", "..", ".", "../path", "..."):
        slug = backend_identity.path_slug(text)
        assert not slug.startswith(".")
        assert "/" not in slug
        assert "\\" not in slug
        assert slug not in {".", ".."}
