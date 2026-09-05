"""Regression tests for confirmed correctness bugs in decomp_analyzer.

Covers audit bugs 14-18:
- BUG 14: commit_success_rate never assigned in compute_aggregate_metrics
- BUG 15: analyze_session crashes on list-typed tool_result content (drops session)
- BUG 16: build_first_try_rate over-reports (counts never-built functions)
- BUG 17: extract_tool_calls double-counts usage across split parallel tool calls
- BUG 18: analyze_all treats since_days=0 as "no filter"
"""

from datetime import datetime, timedelta
from pathlib import Path

from src.analytics.decomp_analyzer import (
    DecompAnalyzer,
    DecompSession,
    FunctionAttempt,
    MatchProgress,
    WorkflowStage,
)


def _make_session(functions):
    s = DecompSession(
        session_id="sid",
        project="melee",
        session_path=Path("/tmp/sid.jsonl"),
    )
    s.functions = list(functions)
    return s


# ---------------------------------------------------------------------------
# BUG 14: commit_success_rate is never assigned (always 0.0)
# ---------------------------------------------------------------------------


def test_bug14_commit_success_rate_all_committed():
    analyzer = DecompAnalyzer()
    analyzer.sessions = [
        _make_session([FunctionAttempt(function_name="fn_A", committed=True)])
    ]
    metrics = analyzer.compute_aggregate_metrics()
    assert metrics.commit_success_rate == 1.0


def test_bug14_commit_success_rate_half_committed():
    analyzer = DecompAnalyzer()
    analyzer.sessions = [
        _make_session(
            [
                FunctionAttempt(function_name="fn_A", committed=True),
                FunctionAttempt(function_name="fn_B", committed=False),
            ]
        )
    ]
    metrics = analyzer.compute_aggregate_metrics()
    assert metrics.commit_success_rate == 0.5


def test_bug14_commit_success_rate_no_functions_guard():
    # Over-correction guard: with no functions the rate must stay 0.0 (no ZeroDivision).
    analyzer = DecompAnalyzer()
    analyzer.sessions = [_make_session([])]
    metrics = analyzer.compute_aggregate_metrics()
    assert metrics.commit_success_rate == 0.0


# ---------------------------------------------------------------------------
# BUG 15: list-typed tool_result content crashes analyze_session -> session dropped
# ---------------------------------------------------------------------------


def _write_session(tmp_path, entries):
    import json

    p = tmp_path / "session.jsonl"
    with open(p, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _bash_claim_entries(result_content):
    """Build a minimal session: an assistant Bash tool_use that claims fn_X,
    and a user tool_result carrying `result_content`."""
    return [
        {
            "type": "user",
            "timestamp": "2026-06-07T00:00:00Z",
            "message": {"content": "melee-agent claim add fn_X"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-06-07T00:00:01Z",
            "message": {
                "id": "msg_1",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {"command": "melee-agent claim add fn_X"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-06-07T00:00:02Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": result_content,
                        "is_error": False,
                    }
                ]
            },
        },
    ]


def test_bug15_list_content_does_not_drop_session(tmp_path):
    # Anthropic content-block shape: a list of dicts. Must not raise / drop the session.
    entries = _bash_claim_entries([{"type": "text", "text": "Claimed fn_X"}])
    path = _write_session(tmp_path, entries)
    analyzer = DecompAnalyzer()
    session = analyzer.analyze_session(path)
    assert session is not None
    names = [f.function_name for f in session.functions]
    assert "fn_X" in names


def test_bug15_string_content_still_parses_guard(tmp_path):
    # Over-correction guard: plain string content keeps working exactly as before.
    entries = _bash_claim_entries("Claimed fn_X")
    path = _write_session(tmp_path, entries)
    analyzer = DecompAnalyzer()
    session = analyzer.analyze_session(path)
    assert session is not None
    names = [f.function_name for f in session.functions]
    assert "fn_X" in names


def test_bug15_list_content_text_is_searchable(tmp_path):
    # The flattened list text must still feed string detection (claim conflict here).
    entries = _bash_claim_entries(
        [{"type": "text", "text": "Error: fn_X is already claimed by agent-2"}]
    )
    path = _write_session(tmp_path, entries)
    analyzer = DecompAnalyzer()
    session = analyzer.analyze_session(path)
    assert session is not None
    fn = next(f for f in session.functions if f.function_name == "fn_X")
    assert any(e.category.value == "claim_conflict" for e in fn.errors)


# ---------------------------------------------------------------------------
# BUG 16: build_first_try_rate counts never-built functions as first-try passes
# ---------------------------------------------------------------------------


def test_bug16_build_first_try_rate_excludes_never_built():
    # fn_A only claimed (never built, default build_passed_first_try=True).
    fn_a = FunctionAttempt(function_name="fn_A")
    # fn_B actually built (reached COMMIT) but failed first try.
    fn_b = FunctionAttempt(function_name="fn_B", build_passed_first_try=False)
    fn_b.stages_completed.append(WorkflowStage.COMMIT)

    analyzer = DecompAnalyzer()
    analyzer.sessions = [_make_session([fn_a, fn_b])]
    metrics = analyzer.compute_aggregate_metrics()
    # Only one builder (fn_B), which failed -> 0.0 (not 0.5).
    assert metrics.build_first_try_rate == 0.0


def test_bug16_build_first_try_rate_two_builders_guard():
    # Over-correction guard: two genuine builders, one pass one fail -> 0.5.
    fn_pass = FunctionAttempt(function_name="fn_pass", build_passed_first_try=True)
    fn_pass.stages_completed.append(WorkflowStage.COMMIT)
    fn_fail = FunctionAttempt(function_name="fn_fail", build_passed_first_try=False)
    fn_fail.stages_completed.append(WorkflowStage.COMMIT)

    analyzer = DecompAnalyzer()
    analyzer.sessions = [_make_session([fn_pass, fn_fail])]
    metrics = analyzer.compute_aggregate_metrics()
    assert metrics.build_first_try_rate == 0.5


def test_bug16_build_first_try_rate_no_builders_is_zero():
    # No builders at all -> rate stays 0.0 (no ZeroDivision).
    fn_a = FunctionAttempt(function_name="fn_A")
    analyzer = DecompAnalyzer()
    analyzer.sessions = [_make_session([fn_a])]
    metrics = analyzer.compute_aggregate_metrics()
    assert metrics.build_first_try_rate == 0.0


# ---------------------------------------------------------------------------
# BUG 17: extract_tool_calls double-counts usage across split parallel calls
# ---------------------------------------------------------------------------


def _assistant_tooluse_entry(message_id, tool_id, input_tokens, output_tokens):
    return {
        "type": "assistant",
        "timestamp": "2026-06-07T00:00:00Z",
        "message": {
            "id": message_id,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "Bash",
                    "input": {"command": "echo hi"},
                }
            ],
        },
    }


def _tool_result_entry(tool_id):
    return {
        "type": "user",
        "timestamp": "2026-06-07T00:00:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "ok",
                    "is_error": False,
                }
            ]
        },
    }


def test_bug17_same_message_id_usage_counted_once():
    # Two assistant entries sharing the SAME message.id, each carrying the full usage.
    entries = [
        _assistant_tooluse_entry("msg_same", "toolu_a", 100, 50),
        _tool_result_entry("toolu_a"),
        _assistant_tooluse_entry("msg_same", "toolu_b", 100, 50),
        _tool_result_entry("toolu_b"),
    ]
    analyzer = DecompAnalyzer()
    tools = analyzer.extract_tool_calls(entries)
    total_input = sum(t["input_tokens"] for t in tools)
    total_output = sum(t["output_tokens"] for t in tools)
    assert total_input == 100
    assert total_output == 50


def test_bug17_different_message_ids_counted_fully_guard():
    # Over-correction guard: distinct message.ids each count fully (200 / 100).
    entries = [
        _assistant_tooluse_entry("msg_a", "toolu_a", 100, 50),
        _tool_result_entry("toolu_a"),
        _assistant_tooluse_entry("msg_b", "toolu_b", 100, 50),
        _tool_result_entry("toolu_b"),
    ]
    analyzer = DecompAnalyzer()
    tools = analyzer.extract_tool_calls(entries)
    total_input = sum(t["input_tokens"] for t in tools)
    total_output = sum(t["output_tokens"] for t in tools)
    assert total_input == 200
    assert total_output == 100


# ---------------------------------------------------------------------------
# BUG 18: analyze_all treats since_days=0 as falsy (no time filter)
# ---------------------------------------------------------------------------


def _make_dated_session(when):
    s = DecompSession(
        session_id="sid",
        project="melee",
        session_path=Path("/tmp/sid.jsonl"),
        started_at=when,
    )
    return s


def test_bug18_since_days_zero_applies_same_day_cutoff(monkeypatch):
    # "recent" is at/after the cutoff instant; offset slightly into the future so the
    # strict `ts < cutoff` comparison inside analyze_all keeps it regardless of the
    # few microseconds that elapse before the cutoff is computed.
    recent = _make_dated_session(datetime.now() + timedelta(seconds=5))
    old = _make_dated_session(datetime.now() - timedelta(days=100))

    analyzer = DecompAnalyzer()

    fake_dir = Path("/tmp/fake_project")

    def fake_find_project_dirs():
        return [fake_dir]

    yielded = iter([recent, old])

    def fake_analyze_session(_path):
        try:
            return next(yielded)
        except StopIteration:
            return None

    # Two fake session files so the inner glob loop runs twice.
    monkeypatch.setattr(analyzer, "find_project_dirs", fake_find_project_dirs)
    monkeypatch.setattr(analyzer, "analyze_session", fake_analyze_session)
    monkeypatch.setattr(
        Path,
        "glob",
        lambda self, pattern: iter([fake_dir / "a.jsonl", fake_dir / "b.jsonl"]),
    )

    sessions = analyzer.analyze_all(since_days=0)
    # The 100-day-old session must be excluded by the same-day cutoff.
    assert old not in sessions
    assert recent in sessions


def test_bug18_since_days_none_returns_all_guard(monkeypatch):
    # Over-correction guard: since_days=None means no filter -> both returned.
    recent = _make_dated_session(datetime.now())
    old = _make_dated_session(datetime.now() - timedelta(days=100))

    analyzer = DecompAnalyzer()
    fake_dir = Path("/tmp/fake_project")

    def fake_find_project_dirs():
        return [fake_dir]

    yielded = iter([recent, old])

    def fake_analyze_session(_path):
        try:
            return next(yielded)
        except StopIteration:
            return None

    monkeypatch.setattr(analyzer, "find_project_dirs", fake_find_project_dirs)
    monkeypatch.setattr(analyzer, "analyze_session", fake_analyze_session)
    monkeypatch.setattr(
        Path,
        "glob",
        lambda self, pattern: iter([fake_dir / "a.jsonl", fake_dir / "b.jsonl"]),
    )

    sessions = analyzer.analyze_all(since_days=None)
    assert old in sessions
    assert recent in sessions


# ---------------------------------------------------------------------------
# BUG 19: had_thrashing contract — code & docstring now agree (>= 2 reversals)
# ---------------------------------------------------------------------------


def _attempt_with_history(pcts):
    fa = FunctionAttempt(function_name="fn")
    fa.match_history = [MatchProgress(None, p, i) for i, p in enumerate(pcts)]
    return fa


def test_had_thrashing_requires_two_direction_reversals():
    """A single down-then-up dip is recovery, not thrashing (matches the
    documented 'repeated oscillation' contract: >= 2 reversals)."""
    # 1 reversal (down then up) -> not thrashing
    assert _attempt_with_history([80, 70, 90]).had_thrashing is False
    # 1 reversal (up then down) -> not thrashing
    assert _attempt_with_history([80, 90, 70]).had_thrashing is False
    # 2 reversals (down-up-down) -> thrashing
    assert _attempt_with_history([70, 90, 60, 95]).had_thrashing is True


def test_had_thrashing_false_for_monotonic_and_short_history():
    """Monotonic progress and <3 samples are never thrashing."""
    assert _attempt_with_history([80, 90, 100]).had_thrashing is False
    assert _attempt_with_history([100, 90, 80]).had_thrashing is False
    assert _attempt_with_history([80, 90]).had_thrashing is False
