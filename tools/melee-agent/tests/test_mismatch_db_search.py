"""Regression tests for mismatch-db full-text search."""

from typer.testing import CliRunner

from src.cli import app
from src.mismatch_db.models import Pattern, PatternDB
from src.mismatch_db.sample_entries import load_samples
from src.mismatch_db.schema import init_db


runner = CliRunner()


def test_fulltext_search_handles_hyphenated_query(tmp_path):
    db = PatternDB(init_db(tmp_path / "patterns.db"))
    db.insert(
        Pattern(
            id="stack-layout",
            name="Stack layout mismatch",
            description="Stack layout changes shift local variable offsets.",
            root_cause="A local variable or inline shape changed stack allocation.",
            categories=["stack"],
        )
    )

    patterns = db.search_fulltext("stack-layout")

    assert [pattern.id for pattern in patterns] == ["stack-layout"]


def test_mismatch_show_alias_displays_pattern_details(tmp_path):
    db_path = tmp_path / "patterns.db"
    db = PatternDB(init_db(db_path))
    db.insert(
        Pattern(
            id="stack-layout",
            name="Stack layout mismatch",
            description="Stack layout changes shift local variable offsets.",
            root_cause="A local variable or inline shape changed stack allocation.",
            categories=["stack"],
        )
    )

    result = runner.invoke(app, ["mismatch", "show", "stack-layout", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Stack layout mismatch" in result.stdout
    assert "ID: stack-layout" in result.stdout


def test_search_prints_retrieval_hint(tmp_path):
    """`mismatch search` should tell agents how to fetch a pattern's details.

    Issue #30: search returns IDs but agents didn't know `mismatch get <id>`
    is the retrieval command. The results footer must surface it.
    """
    db_path = tmp_path / "patterns.db"
    db = PatternDB(init_db(db_path))
    db.insert(
        Pattern(
            id="stack-layout",
            name="Stack layout mismatch",
            description="Stack layout changes shift local variable offsets.",
            root_cause="A local variable or inline shape changed stack allocation.",
            categories=["stack"],
        )
    )

    result = runner.invoke(app, ["mismatch", "search", "stack", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "stack-layout" in result.stdout
    assert "mismatch get" in result.stdout


def test_quick_win_harvest_patterns_are_searchable(tmp_path):
    db = PatternDB(init_db(tmp_path / "patterns.db"))
    load_samples(db)

    thp_results = db.search_fulltext("THP predDC restart padding")
    cast_results = db.search_fulltext("function pointer cast blrl")

    assert "thp-component-layout-pred-dc-padding" in {p.id for p in thp_results}
    assert "function-pointer-cast-forces-indirect-call" in {p.id for p in cast_results}
