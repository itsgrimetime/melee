from __future__ import annotations
import re

_STUB = re.compile(r"///\s*#?\s*(\w+)")
_DEF = re.compile(r"^\s*(?:static\s+)?[A-Za-z_][\w \*]*\b(\w+)\s*\(")
_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "do", "else"}
_HELPER_HINTS = ("sdata2", "order_sdata2")


def _added(diff): return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
def _removed(diff): return [l[1:] for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]


def classify_shape(diff: str) -> str:
    removed = _removed(diff)
    if any(_STUB.search(l) for l in removed):
        return "stub_to_def"
    added = _added(diff)
    if added and not removed and any(_DEF.match(l) for l in added):
        return "new_fn"
    return "tweak"


def parse_match_function(diff: str):
    # prefer the stub-marker symbol (a removed `/// #fn` line)
    for l in _removed(diff):
        m = _STUB.search(l)
        if m:
            return m.group(1)
    # else first added function definition
    for l in _added(diff):
        m = _DEF.match(l)
        if m and m.group(1) not in _KEYWORDS:
            return m.group(1)
    return None


def _is_helper(fn: str) -> bool:
    return any(h in fn for h in _HELPER_HINTS) or fn.endswith("_inline") or fn.endswith("_noinline")


def discover_match_commits(git_runner, *, limit: int = 20, max_lines: int = 60, scan: int = 4000) -> list:
    """Scan master for single-.c match commits (commit-first). Returns up to `limit`
    {function, c_sha, cprev_sha, file, added, removed, shape} dicts, skipping data/inline helpers."""
    out = git_runner(["log", "master", "-n", str(scan), "--numstat", "--format=__C__|%H|%P|%s"])
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("__C__|"):
            if cur:
                commits.append(cur)
            _, h, p, s = line.split("|", 3)
            cur = {"sha": h, "parent": (p.split()[0] if p else ""), "files": []}
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                cur["files"].append(parts)
    if cur:
        commits.append(cur)

    results = []
    for c in commits:
        cfiles = [f for f in c["files"] if f[2].endswith(".c")]
        if len(cfiles) != 1:
            continue
        a, r, path = cfiles[0]
        if not path.startswith("src/melee/") or a in ("-", "") or r in ("-", ""):
            continue
        if int(a) + int(r) > max_lines:
            continue
        diff = git_runner(["show", c["sha"], "--", path])
        fn = parse_match_function(diff)
        if not fn or _is_helper(fn):
            continue
        results.append({"function": fn, "c_sha": c["sha"], "cprev_sha": c["parent"],
                        "file": path, "added": int(a), "removed": int(r), "shape": classify_shape(diff)})
        if len(results) >= limit:
            break
    return results
