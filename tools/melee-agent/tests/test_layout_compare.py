from src.layout.compare import Interval, compare_section, compare_layout


def I(name, off, size, binding="STB_GLOBAL", anonymous=False):
    return Interval(name=name, offset=off, size=size, binding=binding, anonymous=anonymous)


def kinds(fs):
    return {f.kind for f in fs}


def test_ok_identical_layout_no_findings():
    t = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    assert compare_section(".data", t, list(t)) == []


def test_split_one_target_many_current():
    t = [I("blob", 0, 0x30)]
    c = [I("blob", 0, 0xC), I("p1", 0xC, 0xC), I("p2", 0x18, 0xC), I("p3", 0x24, 0xC)]
    assert "split" in kinds(compare_section(".data", t, c))


def test_size_mismatch_same_name_same_offset():
    f = compare_section(".data", [I("s", 0, 0xA)], [I("s", 0, 0xC)])
    assert any(x.kind == "size-mismatch" and x.target[0] == "s" for x in f)


def test_merge_one_current_spans_two_targets():
    t = [I("a", 0, 0xC), I("b", 0xC, 0xC)]
    f = compare_section(".data", t, [I("a", 0, 0x18)])
    assert kinds(f) == {"merge"}  # b is skipped as covered, no extra noise


def test_reorder_name_at_wrong_offset():
    t = [I("a", 0, 0x8), I("b", 0x8, 0x8)]
    c = [I("b", 0, 0x8), I("a", 0x8, 0x8)]
    assert "reorder" in kinds(compare_section(".sdata", t, c))


def test_binding_mismatch_is_opt_in():
    t = [I("a", 0, 0x8, binding="STB_GLOBAL")]
    c = [I("a", 0, 0x8, binding="STB_LOCAL")]
    assert compare_section(".data", t, c) == []  # default: off
    assert "binding-mismatch" in kinds(compare_section(".data", t, c, check_binding=True))


def test_missing_target_uncovered():
    t = [I("a", 0, 0x8), I("gen", 0x8, 0x8)]
    assert "missing" in kinds(compare_section(".sdata2", t, [I("a", 0, 0x8)]))


def test_anonymous_current_covers_target():
    c = [I("@123", 0, 0x4, anonymous=True)]
    assert "anonymous" in kinds(compare_section(".sdata2", [I("lit", 0, 0x4)], c))


def test_section_mismatch_name_in_other_section():
    t = {".bss": [I("g", 0x10, 0x10)]}
    c = {".sbss": [I("g", 0, 0x4)]}
    assert any(x.kind == "section-mismatch" for x in compare_layout(t, c))


def test_foreign_name_occupies_slot():
    # 'b' (a known target name) sits at 'a's slot; 'a' is absent from current
    t = [I("a", 0, 0x8), I("b", 0x10, 0x8)]
    c = [I("b", 0, 0x8)]
    f = compare_section(".sdata", t, c)
    reorders = [x for x in f if x.kind == "reorder"]
    assert any(x.target[0] == "a" and x.current[0][0] == "b" for x in reorders), \
        "expected foreign-name reorder: b occupies slot of a"


def test_section_mismatch_when_old_slot_is_anonymous():
    # g moved to .sdata; its old .data slot is covered by anonymous @1
    t = {".data": [I("g", 0, 0x4)]}
    c = {".sdata": [I("g", 0, 0x4)],
         ".data": [I("@1", 0, 0x4, anonymous=True)]}
    assert any(x.kind == "section-mismatch" for x in compare_layout(t, c))
