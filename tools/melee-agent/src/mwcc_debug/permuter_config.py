"""Render decomp-permuter settings.toml from a mwcc-debug pattern.

The decomp-permuter project loads per-function settings from
`<perm_root>/nonmatchings/<fn>/settings.toml`. Schema (verified against
upstream's `src/main.py` + `src/helpers.py`):

    func_name = "..."             # required by import.py, optional at runtime
    compiler_type = "mwcc"        # base / ido / mwcc / gcc
    objdump_command = "..."       # passed to scorer

    [weight_overrides]
    perm_reorder_decls = 80.0     # any of the 32 perm_* mutation names
    perm_temp_for_expr = 30.0

This module:
1. Renders a fresh settings.toml from a pattern's `permuter_weights`.
2. Merges with an existing settings.toml (pattern wins on conflict
   unless `--merge` is set, in which case existing keys are preserved
   for any name NOT in the pattern's profile).
3. Refuses to render for patterns with `permuter_skip=True` unless
   the caller overrides.

We intentionally do NOT call permuter or import its modules — this is
a pure file-rendering helper.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .patterns import MutationPattern

# Default scorer disassembly command for Melee's gekko target. This uses the
# project dtk binary through melee-agent so local and remote permuter runs do
# not depend on a system powerpc-eabi-objdump install.
DEFAULT_OBJDUMP_COMMAND = "melee-agent debug target dtk-objdump"

# decomp-permuter's internal-type randomizer has a higher crash rate on
# preprocessed Melee sources because prior mutations can leave StructRef
# expressions whose base no longer resolves to a struct/union pointer. Keep
# generated configs at stock weight instead of letting pattern profiles make
# that mutation dominate the run.
WEIGHT_OVERRIDE_CAPS: Mapping[str, float] = {
    "perm_randomize_internal_type": 10.0,
}


@dataclass
class ScorerConfig:
    """Optional [scorer] section for settings.toml.

    Maps to decomp-permuter's CustomCommandScorer interface (added by
    the companion patch on the decomp-permuter side). When present, the
    rendered settings.toml emits a ``[scorer]`` table; permuter then
    invokes ``command <candidate.o>`` per iteration and reads an
    integer score from stdout instead of running the built-in
    objdiff scorer.

    Fields:
      command: Shell command line (will be shlex-split by permuter).
        E.g. ``"melee-agent debug target score-simplify-order -f fn -t spec.yaml"``.
        Permuter appends the candidate .o path as the final argv.
      timeout_seconds: Per-call timeout. Permuter treats timeouts as
        PENALTY_INF iterations (graceful). Default 5s.
    """

    command: str
    timeout_seconds: float = 5.0


@dataclass
class SettingsTomlSpec:
    """Resolved settings about to be rendered to disk."""
    func_name: str
    compiler_type: str  # "mwcc" / "ido" / etc.
    objdump_command: str
    weight_overrides: dict[str, float]
    pattern_name: str | None  # for the header comment, may be None
    randomize_funcs: list[str] | None = None
    scorer: ScorerConfig | None = None  # optional [scorer] table


@dataclass
class BootstrapSettingsRepair:
    """Result from repairing an existing bootstrap settings.toml."""

    text: str
    changed: bool
    randomize_funcs: list[str] | None


class PatternSkippedError(RuntimeError):
    """Raised when the requested pattern has permuter_skip=True and
    the caller didn't pass force=True."""


def _cap_weight_overrides(overrides: dict[str, float]) -> dict[str, float]:
    capped = dict(overrides)
    for key, max_value in WEIGHT_OVERRIDE_CAPS.items():
        if key in capped and capped[key] > max_value:
            capped[key] = max_value
    return capped


def _quote_toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_toml_string_list(values: list[str]) -> str:
    return "[" + ", ".join(_quote_toml_string(value) for value in values) + "]"


def build_spec(
    func_name: str,
    pattern: MutationPattern | None,
    *,
    compiler_type: str = "mwcc",
    objdump_command: str = DEFAULT_OBJDUMP_COMMAND,
    existing_overrides: dict[str, float] | None = None,
    merge: bool = False,
    force: bool = False,
    scorer: ScorerConfig | None = None,
    randomize_funcs: list[str] | None = None,
) -> SettingsTomlSpec:
    """Resolve a SettingsTomlSpec from inputs.

    If `pattern` is None, emits stock settings with no weight overrides.
    If `pattern.permuter_skip` is True and `force` is False, raises
    PatternSkippedError so the CLI can print a guidance message.
    If `merge` is True, existing_overrides not in pattern's profile
    are preserved.

    If `scorer` is provided, the rendered settings.toml will include a
    ``[scorer]`` section pointing at the configured command. Permuter
    (patched with the [scorer] interface) will invoke it per iteration
    in place of the built-in scorer.
    """
    if pattern is not None and pattern.permuter_skip and not force:
        raise PatternSkippedError(pattern.name)

    overrides: dict[str, float] = {}
    if merge and existing_overrides:
        overrides.update(existing_overrides)
    if pattern is not None:
        overrides.update(pattern.permuter_weights)
    overrides = _cap_weight_overrides(overrides)

    return SettingsTomlSpec(
        func_name=func_name,
        compiler_type=compiler_type,
        objdump_command=objdump_command,
        weight_overrides=overrides,
        pattern_name=pattern.name if pattern else None,
        randomize_funcs=randomize_funcs,
        scorer=scorer,
    )


def render_settings_toml(spec: SettingsTomlSpec) -> str:
    """Render a SettingsTomlSpec as TOML text.

    Produces a settings.toml that decomp-permuter will load directly.
    The header comment records the source pattern and tool that
    generated it (for traceability when humans audit the file).
    """
    lines: list[str] = []
    lines.append("# Generated by melee-agent debug permute config")
    if spec.pattern_name:
        lines.append(f"# Pattern: {spec.pattern_name}")
    else:
        lines.append("# Pattern: (none detected — stock weights)")
    lines.append("")
    lines.append(f'func_name = "{spec.func_name}"')
    if spec.randomize_funcs is not None:
        lines.append(
            f"randomize_funcs = {_render_toml_string_list(spec.randomize_funcs)}"
        )
    lines.append(f'compiler_type = "{spec.compiler_type}"')
    lines.append(f'objdump_command = "{spec.objdump_command}"')

    if spec.weight_overrides:
        lines.append("")
        lines.append("[weight_overrides]")
        if spec.pattern_name:
            lines.append(f"# {spec.pattern_name} — bias toward the "
                         f"mutation family that addresses this pattern")
        # Sort for stability — diff-friendly across regenerations
        for key in sorted(spec.weight_overrides):
            value = spec.weight_overrides[key]
            # Render as float (matching upstream convention) — int values
            # like 80 become "80.0" so the file is unambiguous when read
            # back by toml.load.
            lines.append(f"{key} = {value}")

    if spec.scorer is not None:
        lines.append("")
        lines.append("[scorer]")
        lines.append("# Custom scorer (requires the [scorer] interface patch on")
        lines.append("# the decomp-permuter side). When this section is present,")
        lines.append("# permuter invokes `command <candidate.o>` per iteration")
        lines.append("# and reads an integer score from stdout instead of")
        lines.append("# running the built-in objdiff scorer.")
        # TOML strings: escape backslashes and double-quotes. shlex-able
        # commands rarely contain either, but be defensive.
        escaped = (
            spec.scorer.command
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )
        lines.append(f'command = "{escaped}"')
        lines.append(f"timeout_seconds = {spec.scorer.timeout_seconds}")

    return "\n".join(lines) + "\n"


# Pattern that picks the `[weight_overrides]` table from an existing
# settings.toml. We use regex rather than the `toml` library because
# (a) we don't want to add a dependency just for this read, and
# (b) we only need to extract one section to preserve user values.
_WEIGHT_OVERRIDES_SECTION_RE = re.compile(
    r"\[weight_overrides\]\s*\n(.*?)(?=\n\[|\Z)",
    re.DOTALL,
)
_OVERRIDE_LINE_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*([+-]?[0-9.eE+-]+)\s*(?:#.*)?$"
)


def parse_existing_overrides(toml_text: str) -> dict[str, float]:
    """Extract the [weight_overrides] table from a settings.toml text.

    Returns {} if the section is missing. Handles comments and blank
    lines within the section. Doesn't validate against permuter's
    schema — caller may pass invalid keys.
    """
    m = _WEIGHT_OVERRIDES_SECTION_RE.search(toml_text)
    if not m:
        return {}
    out: dict[str, float] = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        match = _OVERRIDE_LINE_RE.match(line)
        if match:
            try:
                out[match.group(1)] = float(match.group(2))
            except ValueError:
                continue
    return out


_BOOTSTRAP_SETTINGS_CONTROLLED_KEYS = {
    "func_name",
    "randomize_funcs",
    "compiler_type",
    "objdump_command",
}
_BOOTSTRAP_SETTINGS_STALE_TOOLCHAIN_KEYS = {
    "compiler_command",
    "assembler_command",
    "asm_prelude_file",
    "asm_pattern",
}
_TOP_LEVEL_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=")


def _existing_randomize_funcs(toml_text: str) -> list[str] | None:
    try:
        parsed = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError:
        return None
    value = parsed.get("randomize_funcs")
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def repair_bootstrap_settings_toml(
    toml_text: str,
    func_name: str,
) -> BootstrapSettingsRepair:
    """Repair a kept bootstrap settings.toml without clobbering tuning.

    Older permuter imports and hand-maintained dirs often carry hardcoded
    devkitPPC compiler/assembler/objdump assumptions. Bootstrap should keep
    user-tuned sections such as [weight_overrides], but the root toolchain
    keys must match the project-local compile.sh and dtk objdump wrapper.
    """
    randomize_funcs = _existing_randomize_funcs(toml_text)
    lines = toml_text.splitlines(keepends=True)

    table_start = len(lines)
    for idx, line in enumerate(lines):
        if re.match(r"^\s*\[", line):
            table_start = idx
            break

    root_lines = lines[:table_start]
    table_lines = lines[table_start:]
    dropped_keys = (
        _BOOTSTRAP_SETTINGS_CONTROLLED_KEYS
        | _BOOTSTRAP_SETTINGS_STALE_TOOLCHAIN_KEYS
    )
    preserved_root: list[str] = []
    for line in root_lines:
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match is not None and match.group(1) in dropped_keys:
            continue
        preserved_root.append(line)

    canonical_lines = [
        f"func_name = {_quote_toml_string(func_name)}\n",
    ]
    if randomize_funcs is not None:
        canonical_lines.append(
            f"randomize_funcs = {_render_toml_string_list(randomize_funcs)}\n"
        )
    canonical_lines.extend(
        [
            'compiler_type = "mwcc"\n',
            f"objdump_command = {_quote_toml_string(DEFAULT_OBJDUMP_COMMAND)}\n",
        ]
    )

    insert_at = 0
    while insert_at < len(preserved_root):
        stripped = preserved_root[insert_at].strip()
        if stripped and not stripped.startswith("#"):
            break
        insert_at += 1
    repaired_lines = (
        preserved_root[:insert_at]
        + canonical_lines
        + preserved_root[insert_at:]
        + table_lines
    )
    repaired_text = "".join(repaired_lines)

    return BootstrapSettingsRepair(
        text=repaired_text,
        changed=repaired_text != toml_text,
        randomize_funcs=randomize_funcs,
    )


def write_settings_toml(
    spec: SettingsTomlSpec,
    out_path: Path,
) -> None:
    """Write the rendered TOML to disk. Creates parent dirs if needed."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_settings_toml(spec))


def render_simplify_order_target_yaml(
    *,
    function: str,
    simplify_order_target: tuple[int, ...] | list[int] = (),
    simplify_order_target_late: tuple[int, ...] | list[int] = (),
    class_id: int,
    baseline_dump: Path,
    force_phys: Mapping[int, int] | None = None,
    coalesce_preservation: bool = True,
) -> str:
    """Render a SimplifyOrderTargetSpec to YAML.

    Exactly one of simplify_order_target (front-target) or
    simplify_order_target_late (end-target) must be non-empty. The
    renderer emits only the non-empty one; the loader's
    mutual-exclusion check rejects YAMLs that contain both.

    Output is hand-formatted (rather than via PyYAML) so the file is
    diff-friendly across regenerations and doesn't require PyYAML at
    write time — it's only needed at scorer-read time.

    force_phys is optional. When provided as a non-empty mapping, it is
    rendered as a YAML mapping under the ``force_phys`` key in sorted key
    order. When None or empty, the key is omitted entirely (keeps
    target.yaml minimal for cases where the screening agent didn't supply
    force-phys).

    coalesce_preservation is True by default and the key is omitted in
    that case (the loader defaults to True). When False, emits
    ``coalesce_preservation: false`` so the loader sees the opt-out.
    """
    if bool(simplify_order_target) == bool(simplify_order_target_late):
        raise ValueError(
            "render_simplify_order_target_yaml requires exactly one of "
            "simplify_order_target or simplify_order_target_late"
        )

    lines: list[str] = [
        "# Generated by melee-agent debug permute setup-simplify-order-scorer",
        f"function: {function}",
    ]
    if simplify_order_target:
        target_list = ", ".join(str(x) for x in simplify_order_target)
        lines.append(f"simplify_order_target: [{target_list}]")
    else:
        late_list = ", ".join(str(x) for x in simplify_order_target_late)
        lines.append(f"simplify_order_target_late: [{late_list}]")
    lines.extend([
        f"class_id: {class_id}",
        f"baseline_dump: {baseline_dump}",
    ])
    if force_phys:
        lines.append("force_phys:")
        for ig_idx, phys in sorted(force_phys.items()):
            lines.append(f"  {ig_idx}: {phys}")
    if not coalesce_preservation:
        lines.append("coalesce_preservation: false")
    return "\n".join(lines) + "\n"
