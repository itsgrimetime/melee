"""
Migration tool to parse existing mismatch-db markdown into structured patterns.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import Example, Fix, Pattern, Provenance, Signal


def slugify(name: str) -> str:
    """Convert a pattern name to a slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extract code blocks with their language hints."""
    pattern = r"```(\w*)\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return [(lang or "text", code.strip()) for lang, code in matches]


def extract_opcodes(text: str) -> list[str]:
    """Extract PowerPC opcodes mentioned in the text."""
    # Common PPC opcodes
    opcodes = [
        "mflr",
        "mtlr",
        "blr",
        "bl",
        "b",
        "beq",
        "bne",
        "blt",
        "bgt",
        "ble",
        "bge",
        "lwz",
        "stw",
        "lfs",
        "stfs",
        "lfd",
        "stfd",
        "lbz",
        "stb",
        "lhz",
        "sth",
        "stwu",
        "lwzu",
        "addi",
        "addis",
        "li",
        "lis",
        "mr",
        "or",
        "ori",
        "cmpwi",
        "cmplwi",
        "cmpw",
        "cmplw",
        "fcmpo",
        "fcmpu",
        "add",
        "sub",
        "subf",
        "subfic",
        "mullw",
        "divw",
        "slwi",
        "srwi",
        "rlwinm",
        "clrlwi",
        "rlwimi",
        "fmul",
        "fdiv",
        "fadd",
        "fsub",
        "fneg",
        "fabs",
        "fmr",
        "crclr",
        "crset",
        "crnot",
    ]
    found = set()
    text_lower = text.lower()
    for op in opcodes:
        # Match as whole word
        if re.search(rf"\b{op}\b", text_lower):
            found.add(op)
    return sorted(found)


def infer_categories(text: str, name: str) -> list[str]:
    """Infer categories based on content."""
    categories = []
    text_lower = (text + " " + name).lower()

    category_keywords = {
        "stack": ["stack", "stwu", "r1", "local variable", "pad_stack"],
        "branch": ["branch", "beq", "bne", "blt", "bgt", "polarity"],
        "control-flow": ["loop", "if-else", "ternary", "switch", "while", "for"],
        "register": ["register", "r27", "r28", "r29", "r30", "r31", "callee-saved"],
        "inline": ["inline", "inlining", "static inline"],
        "struct": ["struct", "field", "vec3", "copy"],
        "type": ["type", "cast", "signed", "unsigned", "u8", "s32", "float"],
        "float": ["float", "fcmpo", "fcmpu", "fabs", "fneg", "lfs", "stfs"],
        "bitfield": ["bitfield", "bit ", "mask", "shift"],
        "loop": ["loop", "increment", "counter", "for ", "while"],
        "calling-conv": ["va_list", "variadic", "calling convention", "vararg"],
        "data-layout": ["string", "data section", "rodata", "sda", "assertion"],
    }

    for category, keywords in category_keywords.items():
        if any(kw in text_lower for kw in keywords):
            categories.append(category)

    return categories


def infer_signals(text: str, diff_blocks: list[str]) -> list[Signal]:
    """Infer signals from the pattern content."""
    signals = []

    # Look for opcode mismatches in diffs
    for diff in diff_blocks:
        lines = diff.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("-") and i + 1 < len(lines) and lines[i + 1].startswith("+"):
                # Extract opcodes from both lines
                old_line = line[1:].strip()
                new_line = lines[i + 1][1:].strip()

                # Simple opcode extraction (first word after address)
                old_match = re.search(r":\s*(\w+)", old_line)
                new_match = re.search(r":\s*(\w+)", new_line)

                if old_match and new_match:
                    old_op = old_match.group(1).lower()
                    new_op = new_match.group(1).lower()
                    if old_op != new_op:
                        signals.append(
                            Signal(
                                type="opcode_mismatch",
                                data={"expected": old_op, "actual": new_op},
                            )
                        )

    # Look for offset patterns
    if "offset" in text.lower() and "r1" in text.lower():
        signals.append(
            Signal(
                type="offset_delta",
                data={"register": "r1"},
                description="Stack offset mismatch",
            )
        )

    # Look for m2c artifacts mentioned
    m2c_artifacts = ["M2C_STRUCT_COPY", "M2C_FIELD", "M2C_ERROR", "M2C_UNK"]
    for artifact in m2c_artifacts:
        if artifact in text:
            signals.append(
                Signal(
                    type="m2c_artifact",
                    data={"artifact": artifact},
                )
            )

    return signals


@dataclass
class MarkdownSection:
    """A section extracted from markdown."""

    name: str
    description: str = ""
    example_diff: str = ""
    example_code: str = ""
    supporting_evidence: list[str] = field(default_factory=list)
    root_cause: str = ""
    fix_text: str = ""
    fix_code_blocks: list[tuple[str, str]] = field(default_factory=list)
    notes: str = ""
    finding_similar: str = ""


def parse_markdown(content: str) -> list[MarkdownSection]:
    """Parse mismatch-db markdown into sections."""
    sections = []

    # Split by horizontal rules
    parts = re.split(r"\n---\n", content)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Look for ## heading
        heading_match = re.search(r"^## (.+)$", part, re.MULTILINE)
        if not heading_match:
            continue

        section = MarkdownSection(name=heading_match.group(1).strip())

        # Extract description (text after heading, before first ###)
        heading_end = heading_match.end()
        next_section = re.search(r"^### ", part[heading_end:], re.MULTILINE)
        if next_section:
            section.description = part[heading_end : heading_end + next_section.start()].strip()
        else:
            section.description = part[heading_end:].strip()

        # Extract subsections
        subsections = re.split(r"^### ", part, flags=re.MULTILINE)

        for subsec in subsections[1:]:  # Skip first (before any ###)
            lines = subsec.strip().split("\n")
            if not lines:
                continue

            title = lines[0].strip().lower()
            content_text = "\n".join(lines[1:]).strip()

            if "example diff" in title or title == "example":
                code_blocks = extract_code_blocks(content_text)
                if code_blocks:
                    section.example_diff = code_blocks[0][1]
                else:
                    section.example_code = content_text

            elif "supporting evidence" in title:
                # Extract bullet points
                bullets = re.findall(r"^[-*]\s+(.+)$", content_text, re.MULTILINE)
                section.supporting_evidence = bullets

            elif "root cause" in title:
                section.root_cause = content_text

            elif "fix" in title and "finding" not in title:
                section.fix_text = re.sub(r"```\w*\n.*?```", "", content_text, flags=re.DOTALL).strip()
                section.fix_code_blocks = extract_code_blocks(content_text)

            elif "note" in title:
                section.notes = content_text

            elif "finding similar" in title:
                section.finding_similar = content_text

            elif "potential fixes" in title:
                section.fix_text += "\n" + content_text

        sections.append(section)

    return sections


def section_to_pattern(section: MarkdownSection) -> Pattern:
    """Convert a markdown section to a Pattern object."""
    pattern_id = slugify(section.name)

    # Combine all text for analysis
    all_text = "\n".join(
        [
            section.description,
            section.example_diff,
            section.example_code,
            "\n".join(section.supporting_evidence),
            section.root_cause,
            section.fix_text,
            section.notes,
        ]
    )

    # Extract data
    opcodes = extract_opcodes(all_text)
    categories = infer_categories(all_text, section.name)

    diff_blocks = [section.example_diff] if section.example_diff else []
    signals = infer_signals(all_text, diff_blocks)

    # Build examples
    examples = []
    if section.example_diff or section.example_code:
        ex = Example(
            function="generic",
            diff=section.example_diff if section.example_diff else None,
        )
        # Try to extract before/after from fix code blocks
        if len(section.fix_code_blocks) >= 1:
            for lang, code in section.fix_code_blocks:
                if lang == "diff" and "\n-" in code and "\n+" in code:
                    # Parse diff to get before/after
                    before_lines = []
                    after_lines = []
                    for line in code.split("\n"):
                        if line.startswith("-") and not line.startswith("---"):
                            before_lines.append(line[1:])
                        elif line.startswith("+") and not line.startswith("+++"):
                            after_lines.append(line[1:])
                    if before_lines:
                        ex.before = "\n".join(before_lines)
                    if after_lines:
                        ex.after = "\n".join(after_lines)
                    break
        examples.append(ex)

    # Build fixes
    fixes = []
    if section.fix_text:
        fix = Fix(description=section.fix_text[:500])  # Truncate long descriptions
        if section.fix_code_blocks:
            # Try to use the last code block as the "after" example
            for lang, code in section.fix_code_blocks:
                if lang in ("c", "diff", ""):
                    if not fix.after:
                        fix.after = code
        fixes.append(fix)

    # Build notes
    notes_parts = []
    if section.notes:
        notes_parts.append(section.notes)
    if section.finding_similar:
        notes_parts.append(f"Finding similar:\n{section.finding_similar}")

    return Pattern(
        id=pattern_id,
        name=section.name,
        description=section.description,
        root_cause=section.root_cause,
        signals=signals,
        examples=examples,
        fixes=fixes,
        provenance=Provenance(),
        related_patterns=[],
        opcodes=opcodes,
        categories=categories,
        notes="\n\n".join(notes_parts) if notes_parts else None,
    )


def migrate_markdown_file(
    markdown_path: Path,
    db,
    dry_run: bool = False,
) -> list[Pattern]:
    """
    Parse a markdown file and insert patterns into the database.

    Args:
        markdown_path: Path to the markdown file
        db: PatternDB instance
        dry_run: If True, don't insert, just return patterns

    Returns:
        List of patterns parsed
    """
    content = markdown_path.read_text()
    sections = parse_markdown(content)

    patterns = []
    for section in sections:
        # Skip non-pattern sections
        if section.name in ("Common Causes for Match Failure", "Understanding Match Percentages"):
            continue
        if "Authoritative" in section.name or "What DOL" in section.name or "How to Verify" in section.name:
            continue

        pattern = section_to_pattern(section)
        patterns.append(pattern)

        if not dry_run:
            try:
                db.insert(pattern)
                print(f"  Inserted: {pattern.id}")
            except Exception as e:
                print(f"  Skipped {pattern.id}: {e}")

    return patterns


if __name__ == "__main__":
    import sys

    from .models import PatternDB
    from .schema import init_db

    skill_md = Path(__file__).parent.parent.parent / ".claude" / "skills" / "mismatch-db" / "SKILL.md"

    if not skill_md.exists():
        print(f"Markdown file not found: {skill_md}")
        sys.exit(1)

    print(f"Parsing: {skill_md}")
    content = skill_md.read_text()
    sections = parse_markdown(content)

    print(f"\nFound {len(sections)} sections:")
    for section in sections:
        print(f"  - {section.name}")
        pattern = section_to_pattern(section)
        print(f"    ID: {pattern.id}")
        print(f"    Opcodes: {pattern.opcodes[:5]}...")
        print(f"    Categories: {pattern.categories}")
        print(f"    Signals: {len(pattern.signals)}")
