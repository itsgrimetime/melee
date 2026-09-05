from types import SimpleNamespace

from src.cli.extract import _count_matching_only_file_exclusions


def test_count_matching_only_file_exclusions_reports_hidden_report_hits() -> None:
    funcs = [
        SimpleNamespace(
            name="ftCh_Init_80156AD8",
            current_match=0.989,
            size_bytes=96,
            file_path="melee/ft/chara/ftCrazyHand/ftCh_Init.c",
            object_status="NonMatching",
        ),
        SimpleNamespace(
            name="other",
            current_match=0.50,
            size_bytes=96,
            file_path="melee/ft/chara/ftOther/file.c",
            object_status="NonMatching",
        ),
    ]

    count = _count_matching_only_file_exclusions(
        funcs,
        min_match=0.0,
        max_match=0.999999,
        min_size=0,
        max_size=10000,
        merged=set(),
        module=None,
        is_excluded_subdir=lambda path: False,
        matches_file_filter=lambda path: "ftcrazyhand/ftch_init" in path.lower(),
    )

    assert count == 1
