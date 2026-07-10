# Bounded Lifetime-Pressure Validation Safety Design

## Goal

Make `debug inspect lifetime-pressure --validate bounded --timeout N` honor one wall-clock budget and prevent it from automatically spawning the unsafe select-order search backend.

## Context

Bounded validation currently launches lifetime-layout, simplify-order, and one select-order search per direct blocker. Each receives the complete timeout independently. A multi-target report can therefore run many sequential workflows, and select-order starts source-mutating probe children in a separate session. The outer bounded runner can time out and kill only the delegated CLI, leaving its source-mutating child alive.

## Approaches Considered

1. Keep automatic select-order and add immediate process-tree supervision. This solves the child ownership problem but requires a larger cancellation protocol with graceful cleanup and is the direct #1209 repair.
2. Remove select-order completely from the diagnostic output. This is safe but hides a useful next command from the user.
3. Defer select-order from automatic bounded execution, emit its fully formed command as an advisory result, and give all remaining safe workflows one monotonic deadline. This immediately removes the hang path while retaining the diagnostic guidance. It is selected.

## Design

`run_bounded_validation()` will build only lifetime-layout and simplify-order as runnable workflows. For each direct blocker it will append a result with status `deferred`, a reason that automatic select-order is disabled for bounded validation, and the exact command a user can run separately.

When `timeout > 0`, the function will create one monotonic deadline. Before each runnable workflow it will calculate remaining seconds and pass only that remaining budget to the runner. Once the deadline expires, it will not start later workflows; it will append `skipped_timeout` results for them. `timeout <= 0` preserves the existing unlimited behavior.

## Testing

- Replace the current direct-blocker test’s expectation that a runner invokes `select-order-search` with assertions that no such command reaches the runner and that a deferred result contains the exact command.
- Use an injectable monotonic clock and fake runner to advance beyond the shared deadline after the first workflow; assert later workflows are `skipped_timeout` and are not invoked.
- Keep FPR command construction coverage for the deferred command.
- Run the bounded-validation test selection, the lifetime-pressure test file, and `git diff --check`.

## Scope

Only `tools/melee-agent/src/mwcc_debug/pressure_explorer/validation.py` and `tools/melee-agent/tests/test_lifetime_pressure_explorer.py` change. Direct `debug select-order-search` cancellation belongs to #1209 and is not changed here.
