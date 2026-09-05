from src.search.directed.diagnosis import build_diagnosis


class _Case:
    def __init__(self, v):
        self.value = v


class _Fact:
    def __init__(self):
        self.case = _Case("B")
        self.ig_idx = 37


class _State:
    def __init__(self):
        self.fact = _Fact()


class _Re:
    def __init__(self, matched):
        self.matched = matched


class _Report:
    def __init__(self):
        self.fact = object()
        self.source = None


class _Compile:
    def __init__(self):
        self.fn = object()


class _Pair:
    def __init__(self, a, b):
        self.from_virt = a
        self.to_virt = b


class _SugReport:
    def __init__(self, pairs):
        self.pairs = pairs


class _Anchor:
    def __init__(self, k):
        self.mutator_key = k


def test_analysis_valid_but_not_actionable_when_anchor_unresolved():
    d = build_diagnosis(
        state=_State(),
        report=_Report(),
        reanchor=_Re({1: 37}),
        compile=_Compile(),
        function="grIceMt_801F9ACC",
        source_text="SRC",
        pcdump_text="PC",
        suggest=lambda **k: _SugReport([]),
        attach=lambda fact, src, fn, pre_pass: object(),
        resolve=lambda idea, src: None,
    )
    assert d.analysis_valid is True and d.actionable is False and d.mutator_key is None


def test_actionable_with_anchor_and_pair():
    d = build_diagnosis(
        state=_State(),
        report=_Report(),
        reanchor=_Re({1: 37}),
        compile=_Compile(),
        function="grIceMt_801F9ACC",
        source_text="SRC",
        pcdump_text="PC",
        suggest=lambda **k: _SugReport([_Pair(34, 37)]),
        attach=lambda *a, **k: object(),
        resolve=lambda idea, src: _Anchor("reorder_local_decls"),
    )
    assert (
        d.actionable is True
        and d.mutator_key == "reorder_local_decls"
        and d.coalesce_pair == (34, 37)
    )


def test_invalid_analysis_when_case_none():
    s = _State()
    s.fact.case = _Case("none")
    d = build_diagnosis(
        state=s,
        report=_Report(),
        reanchor=_Re({1: 37}),
        compile=_Compile(),
        function="f",
        source_text="",
        pcdump_text="",
        suggest=lambda **k: _SugReport([]),
        attach=lambda *a, **k: object(),
        resolve=lambda i, s: None,
    )
    assert d.analysis_valid is False and d.invalid_reason == "none"


def test_attach_receives_pre_pass_compile_fn():
    seen = {}
    compile_obj = _Compile()
    build_diagnosis(
        state=_State(),
        report=_Report(),
        reanchor=_Re({1: 37}),
        compile=compile_obj,
        function="f",
        source_text="S",
        pcdump_text="P",
        suggest=lambda **k: _SugReport([]),
        attach=lambda fact, src, fn, pre_pass: seen.update(pp=pre_pass) or object(),
        resolve=lambda i, s: None,
    )
    assert seen["pp"] is compile_obj.fn  # pre_pass must be compile.fn, not None
