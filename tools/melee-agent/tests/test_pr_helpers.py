"""Tests for PR description validation helpers."""

from src.cli.pr._helpers import validate_pr_description


def test_validate_pr_description_warns_for_fork_only_attempt_db_language():
    body = (
        "Remaining lbmthp unmatched functions are documented in the local attempts DB; "
        "the PR keeps natural-C improvements without chasing register-only local maxima."
    )

    warnings = validate_pr_description(body, [], {})

    assert any("fork-only tooling" in warning for warning in warnings)


def test_validate_pr_description_warns_for_local_tooling_mentions():
    body = "Verified with tools/checkdiff.py and melee-agent attempts show lbmthp_8001F87C."

    warnings = validate_pr_description(body, [], {})

    assert any("fork-only tooling" in warning for warning in warnings)
