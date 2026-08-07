# Private-Heap Bounded-Interior Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the lossy private-heap publication exception with a
dependency-bound proof that helper dereferences lie within the exact factory
allocation extent.

**Architecture:** Keep the generic finite/stack/fresh address domains intact.
Add a private typed provenance/capacity witness at the publication boundary,
derive it from the existing private-heap/factory contracts and exact
page-provider/helper forwarding closure, then authorize only recorded bounded
spans.

**Tech Stack:** Python 3, Capstone x86 decoding, pytest, Ruff.

## Global Constraints

- Modify only `tools/mwcc_retro/x86_cfg.py`, its focused test module, and these
  linked Task 4 documents.
- Fail closed; no retail-address exceptions or generic private-heap arithmetic.
- Bind every fact to instruction, call-edge, factory-contract, and dependency
  replay evidence.
- Do not launch a retail replay during implementation.

---

### Task 1: Freeze the typed-base boundary

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

**Interfaces:**
- Consumes: `_PrivateHeapAllocatorContract`, `_PrivateRegionFactoryShape`
- Produces: a private publication address domain that records call, allocator,
  and factory identity.

- [x] **Step 1: Write failing tests**

```python
assert parser._publication_body_address_domains(...) is None
assert parser._publication_body_address_domains(...untyped_call...) is None
```

- [x] **Step 2: Run the focused test selection and verify failure**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'publication_body or private_heap'`
Observed 2026-08-06: the new unbounded-private-heap assertion failed before
the generic dereference was closed.

- [x] **Step 3: Implement the minimal typed-base domain**

```python
@dataclass(frozen=True, slots=True)
class _PublicationPrivateHeapAddressDomain:
    kind: Literal["private-heap"]
    call_address: int
    allocator_root: int
    factory_entry: int
```

The typed identity remains available for future provenance construction, but
generic private-heap dereferences now return `None` until a bounded witness
exists.

- [x] **Step 4: Run the focused selection and verify it passes**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'publication_body or private_heap'`
Observed 2026-08-06: `3 passed, 1522 deselected`.

### Task 2: Define and test bounded forwarding provenance

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

**Interfaces:**
- Consumes: Task 1 typed base and factory shape fields.
- Produces: immutable provider/helper extent witness with exact incoming calls
  and factory forwarding instructions.

- [x] **Step 1: Write failing hostile tests**

```python
assert bounded_private_heap_role(image, helper) is None  # EBX redefined
assert bounded_private_heap_role(image, helper) is None  # incoming caller missing
assert bounded_private_heap_role(image, helper) is None  # min guard missing
```

- [x] **Step 2: Run the two hostile tests and verify failure**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'bounded_private_heap and (redefined or incoming)'`
Observed 2026-08-06: the initial forwarding cases failed with the expected
missing `_publication_private_heap_extent_witness` attribute. The revised
normalization test then failed RED because the direct-argument rule accepted
the unguarded case and rejected the canonicalized case.

- [x] **Step 3: Implement the fail-closed provider/helper closure**

```python
@dataclass(frozen=True, slots=True)
class _PublicationPrivateHeapExtentWitness:
    factory_call: int
    factory_entry: int
    helper_call: int
    helper_entry: int
    extent_argument_index: int
    payload_argument_index: int
```

The implemented witness additionally binds the provider, factory header and
return offsets, the two exact reaching extent-definition addresses, topology
instruction addresses, a token hash, a nonzero minimum extent, and provider /
helper function fingerprints. It requires exactly one raw-reconciled direct
helper caller, the private allocator's selected page provider, and a single
full-width `MOV` of that factory result into helper argument zero.

The extent is not required to remain a raw formal: it must be the same
register at both pushes and have exactly two reaching definitions: page-mask
`AND` and the minimum-arm full-width `MOV`. The witness requires exact
`CMP register, MIN` followed by unsigned `JAE`/`JNB`, whose target is the
two-predecessor join immediately after the fallback `MOV register, MIN`.
`MIN` must be nonzero and at most `UINT32_MAX - factory_header_size`. No
reachable intervening extent write or direct call other than the factory call
is allowed between the two pushes.

- [x] **Step 4: Run the hostile and positive role tests**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'bounded_private_heap'`
Observed 2026-08-06: `5 passed, 1525 deselected`; only the normalized exact
forwarding case passed. Missing-min-guard, raw and normalized extent
redefinition (the latter rewrites EBX between factory/helper), and incomplete
incoming-caller hostiles rejected. The provider/helper fingerprints are stored
in the witness for later dependency replay; this task adds no memoized reuse.

Independent-review revision, 2026-08-06: both push sites now bind the existing
cross-block reaching-definition engine and require the identical exact set
`{page_mask_and, fallback_min_mov}`. The token additionally binds the provider
argument-0 full-width load, `LEA +0x1017`, mask, compare, unsigned branch,
fallthrough, and join edges; it rejects an alternate predecessor/bypass. The
payload must pass an exact non-null `TEST` plus success branch, with the
failure fallthrough unable to reach the helper. The extent-mask upper bound is
checked against `UINT32_MAX - factory_header_size`, not an invented cap.

Retail replay evidence, 2026-08-06: the exact hydrated query
`hydrate-cfg-query.py --private-heap-extent 0x404610 0x403dd0 0x57fd78
--no-semantic-trace` returned `contract=True` and a non-null witness. The
retail provider's `push ebp` between `LEA` and `AND` is accepted only as an
exact callee-saved prologue push unrelated to the extent; all other prefix
instructions remain rejected.

### Task 3: Bound helper memory spans and replay dependencies

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

**Interfaces:**
- Consumes: `_PublicationPrivateHeapExtentWitness`.
- Produces: publication-body witnesses for exact base/end-relative spans only.

- [x] **Step 1: Write failing span and replay hostiles**

```python
assert audit(...scale=2...) is None
assert audit(...extra_out_of_range_write...) is None
assert replay(changed_provider_bytes) is None
```

- [x] **Step 2: Run the hostile tests and verify failure**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'bounded_private_heap and (scale or range or replay)'`
Observed 2026-08-06: the valid metadata round-trip failed before symbolic
reduction existed, while changed-mask and intervening-clobber fixtures already
failed closed.

- [x] **Step 3: Implement only symbolic intervals with proven no-wrap bounds**

```python
def _publication_private_heap_bounded_span(...):
    """Return an exact recorded span, otherwise None."""
```

- [x] **Step 4: Run focused validation**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'publication_body or private_heap' && python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py && ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py && git diff --check`
Observed 2026-08-06: the focused publication/private-heap selection passed,
along with `py_compile`, Ruff, and `git diff --check`.  The exact hydrated
retail probe accepted all six `0x403dd0` memory spans: base-relative `+8` and
`+0xc`, plus end-relative `-8` and `-4`, bound to the provider/helper
fingerprints and extent token.

### Task 4: Close helper side effects or retain the boundary

**Files:**
- Modify: `tools/melee-agent/tests/test_retro_x86_cfg.py`
- Modify: `tools/mwcc_retro/x86_cfg.py`

**Interfaces:**
- Consumes: bounded helper spans.
- Produces: either an exact closed helper-effect witness or an explicit
  unavailable result that cannot authorize the retail helper.

- [x] **Step 1: Add RED tests for each helper call and indirect edge**

```python
assert bounded_private_heap_role(...unknown_helper_call...) is None
```

- [x] **Step 2: Run the helper-effect test and verify failure**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'bounded_private_heap and helper_effect'`
Observed 2026-08-06: the synthetic recursive helper rejected before the
context-sensitive closure existed; a reachable metadata-clobbering callee is
retained as a hostile.

- [x] **Step 3: Implement exact effect closure or keep the role unavailable**

```python
if not helper_effects_are_closed:
    return None
```

Implemented as a bounded symbolic initializer execution over exact `P`/`E`
affine values and low-bit metadata tags.  Calls require exact pushed-argument
bindings, remain inside the certified allocator dependency closure, preserve
`P+0xc`, and recursively bind all executed bodies and fingerprints.  Exact
branch values prune only recorded call sites.  The retail context reaches
`0x403dd0`, `0x403fd0`, and `0x403ed0`; its initialized zero sentinel proves
the two deeper calls unreachable.  The exact mini body-domain replay produced
30 bounded witnesses.

- [x] **Step 4: Run final local verification**

Run: `python -m pytest tools/melee-agent/tests/test_retro_x86_cfg.py -q -k 'publication_body or private_heap' && python -m py_compile tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py && ruff check tools/mwcc_retro/x86_cfg.py tools/melee-agent/tests/test_retro_x86_cfg.py && git diff --check`
Observed 2026-08-06 after independent hostile review: `32 passed, 1511
deselected`; `py_compile`, Ruff, and `git diff --check` also passed.  The
closure now replays the complete allocator dependency fingerprint inventory,
reconciles every executed direct call against decoded and raw call indexes,
uses only unchanged incoming stack-argument reads, and serializes exact branch
comparisons plus selected/excluded successors for every pruned call.  The
hardened exact retail probe still produced 30 bounded body-domain witnesses,
with two pruned call sites justified by four exact branch witnesses.  The full
root certificate replay is tracked by the parent Task 4 plan.
