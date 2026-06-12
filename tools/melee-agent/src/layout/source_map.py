"""Best-effort map from data-symbol name -> file-scope declaration line."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DECL = re.compile(
    r"^\s*(?P<static>static\s+)?(?:const\s+)?(?:volatile\s+)?"
    r"[A-Za-z_]\w*[\w\s\*]*?\b(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])*\s*(?:=|;)"
)


@dataclass(frozen=True)
class Decl:
    name: str
    line: int
    is_static: bool


def map_decls(c_file: Path) -> dict[str, Decl]:
    out: dict[str, Decl] = {}
    depth = 0
    for n, raw in enumerate(Path(c_file).read_text(errors="replace").splitlines(), 1):
        if depth == 0:
            m = _DECL.match(raw)
            if m and "(" not in raw.split(m.group("name"))[0]:
                out.setdefault(m.group("name"),
                               Decl(m.group("name"), n, bool(m.group("static"))))
        depth += raw.count("{") - raw.count("}")
        if depth < 0:
            depth = 0
    return out
