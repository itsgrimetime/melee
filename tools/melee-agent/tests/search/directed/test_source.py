"""Tests for DirectedSource."""

from src.search.directed.source import DirectedSource
from src.search.types import SourceSpec


class _DM:
    def __init__(self, disp): self.displacement = disp


class _Scored:
    def __init__(self, byte, disp, blob=None):
        self.byte_score = byte
        self.directed_meta = _DM(disp)
        self.source_blob = blob


def _spec(base="BASE"):
    return SourceSpec(base_source=base, target=None)


def test_next_batch_proposes_until_exhausted():
    seq = iter([("reorder_local_decls", object()), ("change_counter_width", object()), None])
    s = DirectedSource(propose=lambda src, tried: next(seq), apply=lambda k, a, src: src + f"/*{k}*/")
    s.seed(_spec("BASE"))
    batch = s.next_batch(8)
    assert len(batch) == 2
    assert batch[0].source_text == "BASE/*reorder_local_decls*/"
    assert batch[0].provenance.mutation == "reorder_local_decls"


def test_propose_three_tuple_sets_producer_meta():
    # propose may return (key, anchor, meta); the meta is merged into
    # Provenance.producer_meta so a blind/non-actionable proposal is tagged.
    seq = iter([("reorder_local_decls@0", object(), {"non_actionable": True}), None])
    s = DirectedSource(propose=lambda src, tried: next(seq), apply=lambda k, a, src: src + k)
    s.seed(_spec("B"))
    batch = s.next_batch(8)
    assert len(batch) == 1
    assert batch[0].provenance.mutation == "reorder_local_decls@0"
    assert batch[0].provenance.producer_meta == {"non_actionable": True}


def test_propose_two_tuple_has_empty_producer_meta():
    seq = iter([("m1", object()), None])
    s = DirectedSource(propose=lambda src, tried: next(seq), apply=lambda k, a, src: src)
    s.seed(_spec())
    batch = s.next_batch(8)
    assert batch[0].provenance.producer_meta == {}


def test_next_batch_caps_at_n():
    seq = iter([("m1", object()), ("m2", object()), ("m3", object())])
    s = DirectedSource(propose=lambda src, tried: next(seq, None), apply=lambda k, a, src: src)
    s.seed(_spec())
    assert len(s.next_batch(2)) == 2


def test_next_batch_empty_when_propose_none():
    s = DirectedSource(propose=lambda src, tried: None, apply=lambda k, a, src: src)
    s.seed(_spec())
    assert s.next_batch(8) == []


def test_skips_unappliable_mutator():
    seq = iter([("bad", object()), ("good", object()), None])
    s = DirectedSource(propose=lambda src, tried: next(seq), apply=lambda k, a, src: None if k == "bad" else src + k)
    s.seed(_spec("B"))
    batch = s.next_batch(8)
    assert len(batch) == 1 and batch[0].source_text == "Bgood"   # "bad" skipped (apply None), still marked tried


def test_observe_resets_stalls_on_improvement_then_stalls():
    s = DirectedSource(propose=lambda src, tried: None, apply=lambda k, a, src: src)
    s.seed(_spec())
    s.observe([_Scored(5, 0.4)])           # first displacement -> improvement, stalls 0
    assert s.stalls == 0
    s.observe([_Scored(5, 0.4)])           # no improvement -> stall
    s.observe([_Scored(5, 0.3)])           # worse -> stall
    assert s.stalls >= 2


def test_observe_empty_increments_stall():
    s = DirectedSource(propose=lambda s_, t: None, apply=lambda k, a, s_: s_)
    s.seed(_spec())
    s.observe([])
    assert s.stalls >= 1
