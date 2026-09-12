# Issue 970 Implementation Plan

1. Add failing regression assertions to the existing Draw and Sort final
   synthesis tests.
2. Add source-family discovery helpers in
   `post_ceiling_baseline_escape.py`:
   - locate source neighborhoods with conservative regexes;
   - generate bounded Draw and Sort probe variants;
   - attach retained scored evidence and validation metadata;
   - emit an explicit terminal summary when spans are missing.
3. Attach the discovery object from `_post_ceiling_final_synthesis_summary`.
4. Verify with the focused post-ceiling test module and CLI smoke runs on the
   filed Draw and Sort artifacts.
5. Commit the spec, plan, tests, and implementation together; refresh the
   editable `melee-agent` install and resolve #970 only after verification.
