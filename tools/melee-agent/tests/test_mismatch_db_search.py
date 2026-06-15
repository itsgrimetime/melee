"""Regression tests for mismatch-db full-text search."""

from typer.testing import CliRunner

from src.cli import app
from src.mismatch_db.models import Fix, Pattern, PatternDB
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


def test_mismatch_add_records_inline_pattern(tmp_path):
    db_path = tmp_path / "patterns.db"

    result = runner.invoke(
        app,
        [
            "mismatch",
            "add",
            "double-masking-no-prototype",
            "--name",
            "Double masking from missing inline prototype",
            "--description",
            "An inline helper call is followed by redundant masking.",
            "--root-cause",
            "MWCC sees an imprecise return width because the callee prototype is missing.",
            "--category",
            "inline",
            "--category",
            "type",
            "--opcode",
            "clrlwi",
            "--opcode",
            "rlwinm",
            "--signal-json",
            (
                '{"type":"instruction_sequence",'
                '"sequence":["clrlwi","rlwinm"],'
                '"description":"redundant mask after helper call"}'
            ),
            "--fix",
            "Add the exact callee prototype before extracting the inline body.",
            "--function",
            "mnDiagram2_HandleInput",
            "--scratch",
            "a97f93631",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Added pattern: double-masking-no-prototype" in result.stdout
    assert "mismatch get double-masking-no-prototype" in result.stdout

    pattern = PatternDB(init_db(db_path)).get("double-masking-no-prototype")
    assert pattern is not None
    assert pattern.categories == ["inline", "type"]
    assert pattern.opcodes == ["clrlwi", "rlwinm"]
    assert pattern.signals[0].type == "instruction_sequence"
    assert pattern.signals[0].data["sequence"] == ["clrlwi", "rlwinm"]
    assert pattern.fixes[0].description.startswith("Add the exact callee prototype")
    assert pattern.examples[0].function == "mnDiagram2_HandleInput"
    assert pattern.examples[0].scratch == "a97f93631"
    assert pattern.provenance.discovered_from[0].function == "mnDiagram2_HandleInput"
    assert pattern.provenance.discovered_from[0].date is not None


def test_mismatch_add_rejects_duplicate_pattern_id(tmp_path):
    db_path = tmp_path / "patterns.db"
    db = PatternDB(init_db(db_path))
    db.insert(
        Pattern(
            id="stack-layout",
            name="Stack layout mismatch",
            description="Original description.",
            root_cause="Original root cause.",
        )
    )

    result = runner.invoke(
        app,
        [
            "mismatch",
            "add",
            "stack-layout",
            "--name",
            "Replacement",
            "--description",
            "Should not overwrite.",
            "--root-cause",
            "Should not overwrite.",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "Pattern already exists: stack-layout" in result.stdout
    assert PatternDB(init_db(db_path)).get("stack-layout").name == "Stack layout mismatch"


def test_mismatch_rm_deletes_pattern(tmp_path):
    db_path = tmp_path / "patterns.db"
    db = PatternDB(init_db(db_path))
    db.insert(
        Pattern(
            id="duplicate-pattern",
            name="Duplicate pattern",
            description="This pattern should be removed.",
            root_cause="It duplicates a canonical entry.",
            categories=["inline"],
        )
    )

    result = runner.invoke(app, ["mismatch", "rm", "duplicate-pattern", "--db", str(db_path)])

    assert result.exit_code == 0, result.stdout
    assert "Deleted pattern: duplicate-pattern" in result.stdout
    assert PatternDB(init_db(db_path)).get("duplicate-pattern") is None

    get_result = runner.invoke(
        app,
        ["mismatch", "get", "duplicate-pattern", "--db", str(db_path)],
    )
    assert get_result.exit_code == 1
    assert "Pattern not found: duplicate-pattern" in get_result.stdout


def test_mismatch_rm_rejects_missing_pattern(tmp_path):
    db_path = tmp_path / "patterns.db"
    db = PatternDB(init_db(db_path))
    db.insert(
        Pattern(
            id="canonical-pattern",
            name="Canonical pattern",
            description="This pattern should remain.",
            root_cause="It is the canonical entry.",
            categories=["inline"],
        )
    )

    result = runner.invoke(app, ["mismatch", "rm", "missing-pattern", "--db", str(db_path)])

    assert result.exit_code == 1
    assert "Pattern not found: missing-pattern" in result.stdout
    assert PatternDB(init_db(db_path)).get("canonical-pattern") is not None


def test_mismatch_add_rejects_malformed_signal_json(tmp_path):
    db_path = tmp_path / "patterns.db"

    result = runner.invoke(
        app,
        [
            "mismatch",
            "add",
            "bad-json",
            "--name",
            "Bad JSON",
            "--description",
            "Invalid signal JSON.",
            "--root-cause",
            "Invalid signal JSON.",
            "--signal-json",
            '{"type":"instruction_sequence"',
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "Invalid JSON for --signal-json" in result.stdout
    assert PatternDB(init_db(db_path)).get("bad-json") is None


def test_mismatch_add_rejects_unknown_signal_type(tmp_path):
    db_path = tmp_path / "patterns.db"

    result = runner.invoke(
        app,
        [
            "mismatch",
            "add",
            "bad-signal",
            "--name",
            "Bad signal",
            "--description",
            "Invalid signal input.",
            "--root-cause",
            "Invalid signal input.",
            "--signal-json",
            '{"type":"not-a-signal"}',
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported signal type for --signal-json: not-a-signal" in result.stdout
    assert PatternDB(init_db(db_path)).get("bad-signal") is None


def test_mismatch_add_rejects_invalid_category(tmp_path):
    db_path = tmp_path / "patterns.db"

    result = runner.invoke(
        app,
        [
            "mismatch",
            "add",
            "bad-category",
            "--name",
            "Bad category",
            "--description",
            "Invalid category input.",
            "--root-cause",
            "Invalid category input.",
            "--category",
            "compiler-magic",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported category: compiler-magic" in result.stdout
    assert "Valid categories:" in result.stdout
    assert "stack" in result.stdout
    assert "control-flow" in result.stdout
    assert PatternDB(init_db(db_path)).get("bad-category") is None


def test_mismatch_add_accepts_common_mwcc_category_slugs(tmp_path):
    db_path = tmp_path / "patterns.db"
    categories = [
        "data",
        "cast",
        "section",
        "cse",
        "optimization",
        "frame",
        "value",
        "global",
        "comparison",
        "memory",
    ]

    result = runner.invoke(
        app,
        [
            "mismatch",
            "add",
            "common-mwcc-slugs",
            "--name",
            "Common MWCC slugs",
            "--description",
            "Uses category names agents naturally reach for while filing patterns.",
            "--root-cause",
            "The CLI category taxonomy accepts common mismatch classes.",
            *[
                arg
                for category in categories
                for arg in ("--category", category)
            ],
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    pattern = PatternDB(init_db(db_path)).get("common-mwcc-slugs")
    assert pattern is not None
    assert pattern.categories == categories


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


def test_register_keyword_stale_pattern_is_corrected(tmp_path):
    db = PatternDB(init_db(tmp_path / "patterns.db"))
    db.insert(
        Pattern(
            id="register-keyword-respected-by-mwcc",
            name="`register` keyword still respected by MWCC for allocation hints",
            description="MWCC (1.2.5n) honors register as an allocation hint.",
            root_cause="MWCC respects register as a hint.",
            fixes=[
                Fix(
                    description=(
                        "When target keeps a loop temp in a dedicated register, "
                        "try adding register keyword. MWCC respects it as a hint."
                    ),
                    success_rate=0.5,
                )
            ],
            categories=["register"],
            opcodes=["lwz", "mr"],
        )
    )

    corrected = PatternDB(db.conn).get("register-keyword-respected-by-mwcc")

    assert corrected is not None
    assert "does not respect" in corrected.description
    assert "do not spend time" in corrected.fixes[0].description.lower()
    stale_text = " ".join(
        [
            corrected.name,
            corrected.description,
            corrected.root_cause,
            corrected.fixes[0].description,
        ]
    )
    assert "MWCC respects" not in stale_text


def test_cmd_buffer_and_for_condition_reload_patterns_are_searchable(tmp_path):
    db = PatternDB(init_db(tmp_path / "patterns.db"))
    load_samples(db)

    cmd_buffer_results = db.search_fulltext(
        "fixed-size scratch array no zero initialization"
    )
    reload_results = db.search_fulltext(
        "for-condition comma assignment reload coalescing"
    )
    inverse_results = db.search_fulltext(
        "inverse CSE rematerialize non-volatile global read"
    )

    assert "sparse-scratch-array-no-zero-init" in {
        p.id for p in cmd_buffer_results
    }
    assert "loop-field-reload-comma-assignment" in {
        p.id for p in reload_results
    }
    assert "inverse-cse-rematerialized-global-read" in {
        p.id for p in inverse_results
    }


def test_new_mismatch_patterns_are_migrated_into_existing_db(tmp_path):
    db = PatternDB(init_db(tmp_path / "patterns.db"))

    cmd_buffer_results = db.search_fulltext(
        "fixed-size scratch array no zero initialization"
    )
    reload_results = db.search_fulltext(
        "for-condition comma assignment reload coalescing"
    )
    inverse_results = db.search_fulltext(
        "inverse CSE rematerialize non-volatile global read"
    )

    assert "sparse-scratch-array-no-zero-init" in {
        p.id for p in cmd_buffer_results
    }
    assert "loop-field-reload-comma-assignment" in {
        p.id for p in reload_results
    }
    assert "inverse-cse-rematerialized-global-read" in {
        p.id for p in inverse_results
    }


def test_migrated_patterns_preserve_recorded_success_on_reopen(tmp_path):
    db_path = tmp_path / "patterns.db"
    db = PatternDB(init_db(db_path))
    db.record_success("sparse-scratch-array-no-zero-init", "fn_80000000")

    reopened = PatternDB(init_db(db_path))
    pattern = reopened.get("sparse-scratch-array-no-zero-init")

    assert pattern is not None
    assert [entry.function for entry in pattern.provenance.helped_match] == [
        "fn_80000000"
    ]


def test_load_samples_keeps_rich_payload_for_migrated_patterns(tmp_path):
    db = PatternDB(init_db(tmp_path / "patterns.db"))
    load_samples(db)

    pattern = db.get("sparse-scratch-array-no-zero-init")

    assert pattern is not None
    assert pattern.examples[0].before is not None
    assert pattern.examples[0].after is not None
