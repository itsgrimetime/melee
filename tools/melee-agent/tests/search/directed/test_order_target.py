import pytest

from src.search.directed.order_target import (
    OrderTarget,
    Routing,
    ValidationError,
    validate_order_target,
)


def _directed_target(**over):
    # Numbers are internally consistent with --force-iter-first semantics:
    # list [46, 28, 29] -> ranks {46: 1, 28: 2, 29: 3} (rank = list index + 1).
    base = dict(
        function="mnDiagram_OnFrame",
        unit="melee/mn/mndiagram",
        class_id=0,
        phys_target={28: 29, 29: 28},
        phys_conflicts=[],
        force_iter_first=[46, 28, 29],
        order_target={28: 2, 29: 3},
        target_roles=[28, 29],
        unscored_roles=[],
        forced_decisions_sha256=["aa", "aa"],
        baseline_source_sha256="bb",
        baseline_pcdump_sha256="cc",
        routing="directed",
        class_evidence="",
        named_pair=[28, 29],
        named_pair_provenance="freeze-time auto-selection",
    )
    base.update(over)
    return OrderTarget(**base)


def test_routing_enum_values():
    assert {r.value for r in Routing} == {
        "directed", "not_order_class", "unanchorable",
        "force_cap_blocked", "unstable_target",
    }


def test_roundtrip_yaml(tmp_path):
    t = _directed_target()
    path = tmp_path / "mnDiagram_OnFrame.yaml"
    t.save_yaml(path)
    loaded = OrderTarget.load_yaml(path)
    assert loaded == t
    # int keys must survive the YAML round-trip (YAML stringifies dict keys).
    assert loaded.order_target == {28: 2, 29: 3}
    assert loaded.phys_target == {28: 29, 29: 28}
    assert loaded.named_pair == [28, 29]


def test_load_yaml_tolerates_missing_named_pair(tmp_path):
    # Files written before the named_pair field existed must still load.
    t = _directed_target()
    path = tmp_path / "old.yaml"
    t.save_yaml(path)
    import yaml
    data = yaml.safe_load(path.read_text())
    del data["named_pair"]
    del data["named_pair_provenance"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    loaded = OrderTarget.load_yaml(path)
    assert loaded.named_pair == []
    assert loaded.named_pair_provenance == ""


def test_validate_directed_ok():
    validate_order_target(_directed_target())  # no raise


def test_validate_directed_requires_two_roles():
    with pytest.raises(ValidationError, match="at least 2 target_roles"):
        validate_order_target(_directed_target(
            target_roles=[28], order_target={28: 2}, named_pair=[]))


def test_validate_directed_rejects_conflicts():
    with pytest.raises(ValidationError, match="phys_conflicts"):
        validate_order_target(_directed_target(
            phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]))


def test_validate_directed_target_role_must_be_in_order_target():
    with pytest.raises(ValidationError, match="not present in order_target"):
        validate_order_target(_directed_target(target_roles=[28, 99], named_pair=[]))


def test_validate_force_cap():
    with pytest.raises(ValidationError, match="64"):
        validate_order_target(_directed_target(force_iter_first=list(range(65))))


def test_validate_named_pair_must_be_two_target_roles():
    with pytest.raises(ValidationError, match="named_pair"):
        validate_order_target(_directed_target(named_pair=[28, 99]))
    with pytest.raises(ValidationError, match="named_pair"):
        validate_order_target(_directed_target(named_pair=[28]))
    validate_order_target(_directed_target(named_pair=[]))  # empty is allowed


def test_validate_non_directed_skips_role_checks():
    # A not_order_class target need not satisfy the directed invariants.
    t = _directed_target(
        routing="not_order_class", target_roles=[], order_target={},
        named_pair=[], named_pair_provenance="",
        phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}],
        class_evidence=(
            "instruction-content/emission divergence upstream of select "
            "(8024227C: param-alias statement-copy skew; ORACLE ROUND 2 erratum — "
            "verify with: git show 8bd6f8648:CAMPAIGN-STATE-D1COMPLETION.md "
            "| grep -n -A4 'ORACLE ROUND 2')"
        ),
    )
    validate_order_target(t)  # no raise


def test_validate_unknown_routing():
    with pytest.raises(ValidationError, match="routing"):
        validate_order_target(_directed_target(routing="bogus"))
