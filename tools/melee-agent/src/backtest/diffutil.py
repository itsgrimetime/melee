from __future__ import annotations


def function_diff(git_runner, c_sha: str, file: str) -> str:
    return git_runner(["show", c_sha, "--", file])


def diff_stats(diff: str) -> dict:
    added = removed = hunks = files = 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            hunks += 1
        elif line.startswith("+++ "):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"added": added, "removed": removed, "hunks": hunks, "files": files}


def is_small_singular(diff: str, *, max_changed_lines: int = 30,
                      max_hunks: int = 2, single_file: bool = True) -> bool:
    s = diff_stats(diff)
    if single_file and s["files"] != 1:
        return False
    if s["hunks"] > max_hunks:
        return False
    return (s["added"] + s["removed"]) <= max_changed_lines
