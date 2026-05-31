"""Regression tests for canonical mwcc-debug docs command names."""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

CANONICAL_DOCS = [
    REPO_ROOT / ".claude" / "skills" / "mwcc-debug" / "SKILL.md",
    REPO_ROOT / "docs" / "mwcc-debug.md",
    REPO_ROOT / "docs" / "mwcc-debug-roadmap.md",
]

REFERENCE_TEXTS = [
    *CANONICAL_DOCS,
    REPO_ROOT / "docs" / "mwcc-debug-permuter-integration.md",
    REPO_ROOT / "tools" / "melee-agent" / "scripts" / "permute_with_mwcc.py",
    *sorted((REPO_ROOT / "tools" / "melee-agent" / "src" / "mwcc_debug").glob("*.py")),
    *[
        path
        for path in sorted((REPO_ROOT / "tools" / "melee-agent" / "tests").glob("test_*.py"))
        if path.name != "test_mwcc_debug_docs_cli_reorg.py"
    ],
]

STALE_FORMS = [
    "melee-agent debug pcdump-local",
    "melee-agent debug pcdump ",
    "melee-agent debug setup-local",
    "melee-agent debug analyze",
    "melee-agent debug guide",
    "melee-agent debug derive-target",
    "melee-agent debug score ",
    "melee-agent debug score-source",
    "melee-agent debug suggest-casts",
    "melee-agent debug suggest-coalesce-source",
    "melee-agent debug suggest-inlines",
    "melee-agent debug verify-perm",
    "melee-agent debug enumerate-decl-orders",
    "melee-agent debug triage-perm",
    "melee-agent debug gen-permuter-config",
    "melee-agent debug fix-perm-compile",
    "melee-agent debug restore-object-report",
    "melee-agent debug pattern-catalog",
    "melee-agent debug name-magic",
    "melee-agent debug verify-with-name-magic",
    "melee-agent debug var-to-virtual",
    "melee-agent debug virtual-to-var",
    "melee-agent debug virtual-to-ig",
    "melee-agent debug trace-copy",
]

STALE_REFERENCE_PATTERNS = [
    r"(?<![\w-])debug pcdump-local\b",
    r"(?<![\w-])debug pcdump\b",
    r"(?<![\w-])debug setup-local\b",
    r"(?<![\w-])debug analyze\b",
    r"(?<![\w-])debug simulate\b",
    r"(?<![\w-])debug diff\b",
    r"(?<![\w-])debug guide\b",
    r"(?<![\w-])debug stuck\b",
    r"(?<![\w-])debug ceiling\b",
    r"(?<![\w-])debug rank-callees\b",
    r"(?<![\w-])debug derive-target\b",
    r"(?<![\w-])debug score\b",
    r"(?<![\w-])debug score-source\b",
    r"(?<![\w-])debug match-iter-first\b",
    r"(?<![\w-])debug suggest-casts\b",
    r"(?<![\w-])debug suggest-coalesce-source\b",
    r"(?<![\w-])debug suggest-inlines\b",
    r"(?<![\w-])debug enumerate-decl-orders\b",
    r"(?<![\w-])debug tier3-search\b",
    r"(?<![\w-])debug verify-perm\b",
    r"(?<![\w-])debug triage-perm\b",
    r"(?<![\w-])debug gen-permuter-config\b",
    r"(?<![\w-])debug fix-perm-compile\b",
    r"(?<![\w-])debug restore-object-report\b",
    r"(?<![\w-])debug permute\s+-",
    r"(?<![\w-])debug pattern-catalog\b",
    r"(?<![\w-])debug name-magic\b",
    r"(?<![\w-])debug verify-with-name-magic\b",
    r"(?<![\w-])debug var-to-virtual\b",
    r"(?<![\w-])debug virtual-to-var\b",
    r"(?<![\w-])debug virtual-to-ig\b",
    r"(?<![\w-])debug trace-copy\b",
]

EXPECTED_FORMS = [
    "melee-agent debug dump local",
    "melee-agent debug dump remote",
    "melee-agent debug dump setup",
    "melee-agent debug dump restore-object-report",
    "melee-agent debug inspect guide",
    "melee-agent debug inspect analyze",
    "melee-agent debug target derive",
    "melee-agent debug target score-dump",
    "melee-agent debug target score-source",
    "melee-agent debug suggest casts",
    "melee-agent debug suggest coalesce",
    "melee-agent debug suggest inlines",
    "melee-agent debug mutate decl-orders",
    "melee-agent debug permute verify",
    "melee-agent debug permute triage",
    "melee-agent debug permute config",
    "melee-agent debug permute fix-compile",
    "melee-agent debug permute run",
    "melee-agent debug util patterns",
    "melee-agent debug util name-magic",
    "melee-agent debug inspect var-to-virtual",
    "melee-agent debug inspect virtual-to-var",
    "melee-agent debug inspect virtual-to-ig",
    "melee-agent debug inspect trace-copy",
]


def test_canonical_docs_exist() -> None:
    missing = [str(path) for path in CANONICAL_DOCS if not path.exists()]
    assert missing == []


def test_canonical_docs_use_grouped_debug_commands() -> None:
    combined = "\n".join(path.read_text() for path in CANONICAL_DOCS)

    stale_hits = [form for form in STALE_FORMS if form in combined]
    assert stale_hits == []

    missing_expected = [form for form in EXPECTED_FORMS if form not in combined]
    assert missing_expected == []


def test_reference_texts_do_not_emit_removed_debug_commands() -> None:
    missing = [str(path) for path in REFERENCE_TEXTS if not path.exists()]
    assert missing == []

    stale_hits = []
    for path in REFERENCE_TEXTS:
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            for pattern in STALE_REFERENCE_PATTERNS:
                if re.search(pattern, line):
                    stale_hits.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line}")

    assert stale_hits == []
