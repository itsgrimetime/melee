# Issue 967 Plan: Baseline-Escape Continuation

1. Add JSON serializers for `AllocatorFact`, `SourceIdea`, and `FirstDivergenceReport`.
2. Enable allocator-mode `debug inspect first-divergence --json`.
3. Add baseline-escape continuation helpers that read scored candidate `pcdump_path` artifacts and run first-divergence with the candidate function/source function and force map.
4. Add route/blocker classification for Case C, Case C2, Case D, unsupported FPR stack-load/conversion temps, and unavailable pcdumps.
5. Include `post_ceiling_continuation` in scored baseline-escape output and prefer actionable continuation status over first-generation terminal status.
6. Add retained-frontier triage extraction for `post-ceiling-continuation-exhausted`.
7. Verify with focused unit tests, py_compile, CLI help/JSON smoke, and live classified Draw/Sort artifact smoke.
