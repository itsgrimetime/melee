from src.backtest.provenance import weighted_jaccard, is_in_corpus, diff_to_feature_vector

PATTERNS = [
    {"id": "u8-mask", "name": "u8 parameter mask clrlwi", "opcodes": ["clrlwi"],
     "categories": ["register", "type"], "signals": [{"type": "opcode_mismatch"}]},
]

def test_exact_name_overlap_scores_high():
    cand = {"name": "u8 parameter mask clrlwi", "opcodes": ["clrlwi"],
            "categories": ["register", "type"], "signals": [{"type": "opcode_mismatch"}]}
    assert weighted_jaccard(cand, PATTERNS[0]) > 0.9
    assert is_in_corpus(cand, PATTERNS) is True

def test_unrelated_is_held_out():
    cand = {"name": "frame slot rotation", "opcodes": [],
            "categories": ["frame"], "signals": [{"type": "register"}]}
    assert is_in_corpus(cand, PATTERNS, threshold=0.5) is False


# ---------------------------------------------------------------------------
# diff_to_feature_vector (M-1.5): load-bearing for the in-corpus label.
# ---------------------------------------------------------------------------

def test_diff_to_feature_vector_returns_four_keys():
    fv = diff_to_feature_vector("@@\n-    int mode = get();\n+    u8 mode = get();\n", "retype")
    assert set(fv) == {"opcodes", "categories", "name", "signals"}


def test_diff_to_feature_vector_opcodes_empty_for_source_diffs():
    # Source diffs carry no PPC opcodes; opcodes must always be empty.
    fv = diff_to_feature_vector("@@\n-    int x = f();\n+    u8 x = f();\n", "retype")
    assert fv["opcodes"] == []


def test_diff_to_feature_vector_categories_derived_from_lever_class():
    # Known lever class -> mapped categories.
    assert diff_to_feature_vector("@@\n+x\n", "retype")["categories"] == ["type", "register"]
    assert diff_to_feature_vector("@@\n+x\n", "struct_overlay")["categories"] == ["struct", "data-layout"]
    # Unknown/unmapped lever class -> falls back to [lever_class].
    assert diff_to_feature_vector("@@\n+x\n", "hoist_to_local")["categories"] == ["hoist_to_local"]


def test_diff_to_feature_vector_name_contains_changed_identifiers():
    # Whitespace-split tokens that are pure identifiers are kept; trailing
    # punctuation (e.g. "get();") makes a token a non-identifier, so use bare names.
    fv = diff_to_feature_vector(
        "@@\n-    int oldmode = legacy ;\n+    u8 newmode = current ;\n", "retype"
    )
    names = fv["name"].split()
    # Identifiers from BOTH added and removed lines appear.
    assert "oldmode" in names and "legacy" in names   # removed line
    assert "newmode" in names and "current" in names   # added line
    assert "u8" in names and "int" in names
    # Non-identifier tokens (operators) are excluded.
    assert "=" not in names
