# Discord Conversation Distillation Prompt

You are reviewing a month of Discord conversations from the `#smash-bros-melee` channel in the gc-wii-decomp server. Your task is to extract and distill useful decompilation knowledge into structured documentation.

## Context

This Discord server is dedicated to GameCube/Wii decompilation projects. The conversations contain:
- Compiler behavior insights (mwcc/Metrowerks CodeWarrior)
- Function matching strategies and tricks
- Type/struct discoveries and layouts
- Tool usage tips (decomp.me, objdiff, dtk)
- Common pitfalls and how to avoid them

## Output Format

Create a markdown document with these sections (only include sections that have relevant content):

### Compiler Patterns
Document any insights about mwcc compiler behavior:
- Optimization quirks (-O4,p, -inline auto, etc.)
- Register allocation patterns
- Instruction selection behaviors
- Known bugs or unexpected behaviors

### Matching Techniques
Strategies for achieving 100% matches:
- Specific code patterns that produce expected assembly
- Loop unrolling techniques
- Conditional expression ordering
- Cast and type annotation tricks

### Type Information
Struct layouts, field offsets, and type relationships:
- Discovered struct sizes
- Field offset information
- Enum values
- Inheritance/composition patterns

### Function-Specific Insights
Document any function-specific knowledge mentioned:
- Function names and their purposes
- Parameter types discovered
- Return value behavior
- Inlining behavior

### Tool Tips
Practical tips for decompilation tools:
- decomp.me usage
- objdiff interpretation
- Ghidra/IDA techniques
- Build system tips

### Pitfalls and Gotchas
Common mistakes and how to avoid them:
- Things that cause mismatches
- Misleading decompiler output
- Cross-file dependencies

## Guidelines

1. **Be specific**: Include exact values, offsets, and code snippets when mentioned
2. **Attribute when possible**: Note who shared the insight if it seems authoritative
3. **Skip noise**: Ignore off-topic chatter, greetings, and messages with no technical content
4. **Preserve context**: If a discussion thread reveals something important, summarize the conclusion
5. **Code examples**: Include relevant code snippets in fenced blocks with language hints

## Example Output

```markdown
# Decompilation Knowledge: 2022-02

## Compiler Patterns

### Inline Auto with Frank
- Using `-inline auto` with Frank's scheduling patch can introduce extra instructions after prologues in some unrolled loops
- Workaround: Try removing explicit inline auto flag if seeing unexpected prologue differences
- Source: werewolf.zip (2022-02-02)

### dont_inline Pragma
- The `dont_inline` pragma applies to the **called** function, not the caller
- Any function listed in the pragma block will not be inlined anywhere
- Source: camthesaxman (2022-02-02)

## Matching Techniques

### Hand-Unrolled Loops
- Some loops needed manual unrolling to match the original assembly
- After match achieved, inline auto flag may not be needed
- Example function: func_8036AA9C (FObj-related)

## Pitfalls

### decomp.me Relocation Errors
- Invalid target ASM can cause cryptic relocation errors like:
  `Error running asm-differ: unknown relocation type 'R_PPC_REL14'`
- Always verify target ASM is complete and valid before debugging other issues
```

---

## Your Task

Review the conversation log provided below and extract all useful decompilation knowledge following the format above. Focus on actionable insights that would help someone match functions in the Melee decompilation project.
