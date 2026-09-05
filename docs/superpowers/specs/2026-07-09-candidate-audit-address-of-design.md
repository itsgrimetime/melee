# Candidate Audit Address-of Read Classification Design

## Goal

Allow candidate C that takes the address of an uninitialized local while continuing to reject expressions that read that local’s uninitialized value.

## Context

The candidate audit scans identifiers in statements and classifies each known local that is neither initialized nor assigned as a use-before-definition. It currently treats `&sp_jobj2` as a read, rejecting valid out-parameter calls such as `lb_80011E24(jobj, &sp_jobj2, 2, -1)`. C address-taking does not access the pointed-to local’s value.

## Approaches Considered

1. Remove use-before-definition auditing for all local expressions. This would admit invalid value reads and is rejected.
2. Skip every identifier immediately preceded by `&`. This incorrectly exempts the right operand of binary bitwise and logical-and expressions, such as `flags & local` and `ready && local`. It is rejected.
3. Recognize only a unary address-of operator preceding the identifier, based on the prior non-space token. This admits valid `&local` output arguments while retaining binary `&` and `&&` value reads. This is selected.

## Design

Add a narrowly scoped candidate-audit helper that determines whether an identifier is directly preceded by unary `&`. The operator is unary at statement or expression boundaries (for example after `(`, `,`, `=`, or another unary operator) and is not unary when the preceding non-space token ends an expression (an identifier, literal, `)`, or `]`) or is another `&`.

`_local_reads` will exclude a known local only when that helper identifies unary address-taking. Existing member-access and assignment-left-hand-side behavior remains unchanged. No definition is recorded for `&local`: later direct value reads still remain use-before-definition risks until an initializer or assignment exists.

## Testing

- Add a candidate-audit test with a declared `HSD_JObj* out;`, `void* alias = &out;`, and an out-parameter call. Assert no use-before-definition risk for `out`.
- Add a negative test with `int flags; int local; use(flags & local);` and assert `local` is rejected as a use-before-definition.
- Add a negative logical-and case if the existing helper’s token classifier does not cover both binary spellings through the same assertion.
- Run the focused candidate-audit test file and `git diff --check`.

## Scope

Only `tools/melee-agent/src/mwcc_debug/candidate_audit.py` and `tools/melee-agent/tests/test_mwcc_debug_candidate_audit.py` change. The audit remains a conservative heuristic rather than a C parser.
