#!/usr/bin/env python3
"""Compare function match percentages between two report.json files."""

import argparse
import json
import sys
from pathlib import Path


def load_report(path: Path) -> dict:
    """Load a report.json file."""
    if not path.exists():
        print(f"Error: {path} not found.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def find_unit(data: dict, unit_name: str) -> dict | None:
    """Find a unit by exact or partial name match."""
    # Try exact match first
    for unit in data["units"]:
        if unit["name"] == unit_name:
            return unit
    # Try partial match
    matches = [u for u in data["units"] if unit_name in u["name"]]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Ambiguous unit name '{unit_name}'. Matches:", file=sys.stderr)
        for m in matches:
            print(f"  {m['name']}", file=sys.stderr)
        sys.exit(1)
    return None


def compare_units(current_unit: dict, other_unit: dict, show_all: bool = False) -> None:
    """Compare function match percentages between two units."""
    # fuzzy_match_percent is absent for unmatched functions (treat as 0%)
    current_funcs = {f["name"]: f.get("fuzzy_match_percent", 0.0) for f in current_unit["functions"]}
    other_funcs = {f["name"]: f.get("fuzzy_match_percent", 0.0) for f in other_unit["functions"]}

    all_funcs = sorted(set(current_funcs.keys()) | set(other_funcs.keys()))

    print(f"\n{'Function':<40} {'Current':>10} {'Other':>10} {'Diff':>10}")
    print("-" * 72)

    total_diff = 0.0
    changed = 0

    for func in all_funcs:
        curr = current_funcs.get(func, 0.0)
        other = other_funcs.get(func, 0.0)
        diff = curr - other

        if diff != 0 or show_all:
            diff_str = f"{diff:+.1f}%" if diff != 0 else ""
            indicator = ""
            if diff > 0:
                indicator = "↑"
            elif diff < 0:
                indicator = "↓"

            print(f"{func:<40} {curr:>9.1f}% {other:>9.1f}% {diff_str:>9} {indicator}")

        if diff != 0:
            total_diff += diff
            changed += 1

    print("-" * 72)
    if changed > 0:
        print(f"Changed: {changed} functions, net diff: {total_diff:+.1f}%")
    else:
        print("No differences found.")


def main():
    parser = argparse.ArgumentParser(
        description="Compare function match % between two report.json files",
        epilog="Example: %(prog)s mnvibration ../other-branch/build/GALE01/report.json",
    )
    parser.add_argument("unit", help="Translation unit name (e.g., main/melee/mn/mnvibration or just mnvibration)")
    parser.add_argument("other_report", help="Path to the other report.json to compare against")
    parser.add_argument("-c", "--current", help="Path to current report.json (default: build/GALE01/report.json)")
    parser.add_argument("-a", "--all", action="store_true", help="Show all functions, not just changed ones")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent

    # Load reports
    current_path = Path(args.current) if args.current else repo_root / "build/GALE01/report.json"
    other_path = Path(args.other_report)

    current_report = load_report(current_path)
    other_report = load_report(other_path)

    # Find the unit in both reports
    current_unit = find_unit(current_report, args.unit)
    if not current_unit:
        print(f"Error: Unit '{args.unit}' not found in {current_path}.", file=sys.stderr)
        sys.exit(1)

    other_unit = find_unit(other_report, args.unit)
    if not other_unit:
        print(f"Error: Unit '{args.unit}' not found in {other_path}.", file=sys.stderr)
        sys.exit(1)

    print(f"Comparing: {current_unit['name']}")
    print(f"  Current: {current_path}")
    print(f"  Other:   {other_path}")

    compare_units(current_unit, other_unit, show_all=args.all)


if __name__ == "__main__":
    main()
