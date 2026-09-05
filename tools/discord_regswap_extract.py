#!/usr/bin/env python3
"""Extract register-swap-related Discord conversations with thread context.

Searches #match-help and #general for messages mentioning register
allocation, regswaps, callee-saved registers, stmw, mr vs addi, etc.,
and pulls a context window (10 min before, 30 min after) around each hit
to capture the discussion.

Output is plain text chunks ready for agent consumption.

Usage:
    python tools/discord_regswap_extract.py --output /tmp/regswap_threads.txt
    python tools/discord_regswap_extract.py --keyword "stmw" --output /tmp/stmw.txt
    python tools/discord_regswap_extract.py --list-keywords
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / "code/index/discord_archive_gc-wii-decomp.db"

# Keywords categorized — each tuple is (group_name, FTS query)
KEYWORD_GROUPS = [
    ("regswap-direct", '"register swap" OR regswap OR regswaps'),
    ("regalloc-direct", '"register allocation" OR regalloc OR "register alloc"'),
    ("callee-saved", '"callee-saved" OR "callee saved" OR "callee_saved"'),
    ("stmw-lmw", "stmw OR lmw"),
    ("addi-mr-peephole", '"addi r" OR "mr r" OR "addi rX" OR peephole'),
    ("specific-regs-r-low", "r27 OR r28 OR r29 OR r30 OR r31"),
    ("specific-regs-r-high", "r3 OR r4 OR r5 OR r6 OR r7 OR r8"),
    ("specific-regs-f", "f29 OR f30 OR f31 OR f0 OR f1"),
    ("declaration-order", '"declaration order" OR "decl order" OR "variable order"'),
    ("self-assign-trick", '"x = x" OR "self-assignment" OR "self assignment"'),
    ("dead-statement", '"dead store" OR "dead statement" OR "discard"'),
    ("spill", "spill OR spilled OR spilling"),
    ("live-range", '"live range" OR "liverange" OR liveness'),
    ("scratch-register", '"scratch register" OR "scratch reg"'),
    ("save-restore", '"save and restore" OR savearea OR "save area"'),
    ("permuter-regswap", "permuter AND regswap"),
    ("mismatch-register", '"register mismatch" OR "reg mismatch"'),
]


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def search_messages(query: str, channels: list[str] | None = None) -> list[dict]:
    """FTS search across channels."""
    conn = get_connection()
    cursor = conn.cursor()

    where_parts = ["messages_fts MATCH ?"]
    params: list = [query]

    if channels:
        placeholders = ",".join("?" * len(channels))
        where_parts.append(f"m.channel_name IN ({placeholders})")
        params.extend(channels)

    sql = f"""
        SELECT
            m.id, m.timestamp, m.channel_name, m.author_name,
            m.content, m.is_reply, m.reply_to_id
        FROM messages_fts fts
        JOIN messages m ON m.rowid = fts.rowid
        WHERE {" AND ".join(where_parts)}
        ORDER BY m.timestamp
    """

    cursor.execute(sql, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def fetch_context(
    channel_name: str,
    around_timestamp: str,
    minutes_before: int = 10,
    minutes_after: int = 30,
) -> list[dict]:
    """Fetch messages around a timestamp for context."""
    conn = get_connection()
    cursor = conn.cursor()

    # Parse timestamp (ISO 8601 with timezone)
    # Format: 2022-03-15T10:23:45.123-07:00
    ts_str = around_timestamp.split("+")[0].split("-08:")[0].split("-07:")[0]
    if "." in ts_str:
        ts_str = ts_str.split(".")[0]
    ts = datetime.fromisoformat(ts_str)

    start = (ts - timedelta(minutes=minutes_before)).isoformat()
    end = (ts + timedelta(minutes=minutes_after)).isoformat()

    cursor.execute(
        """
        SELECT id, timestamp, author_name, content, is_reply, reply_to_id
        FROM messages
        WHERE channel_name = ?
          AND substr(timestamp, 1, 19) >= ?
          AND substr(timestamp, 1, 19) <= ?
        ORDER BY timestamp
        """,
        (channel_name, start, end),
    )

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def format_thread(channel: str, messages: list[dict]) -> str:
    """Format a thread of messages for agent consumption."""
    if not messages:
        return ""

    first_ts = messages[0]["timestamp"][:10]
    lines = [
        f"### Thread in #{channel} on {first_ts}",
        "",
    ]

    for msg in messages:
        time = msg["timestamp"][11:16]
        author = msg["author_name"]
        content = msg["content"].strip()
        prefix = "↳ " if msg["is_reply"] else ""
        # Truncate very long messages
        if len(content) > 800:
            content = content[:800] + "... [truncated]"
        lines.append(f"[{time}] {prefix}{author}: {content}")

    return "\n".join(lines)


def dedupe_threads(threads: list[tuple[str, str]], window_minutes: int = 60) -> list[tuple[str, str]]:
    """Dedupe overlapping threads. Each thread is (key, content).

    Threads with the same (channel, hour-bucket) get merged."""
    seen = {}
    for key, content in threads:
        if key not in seen:
            seen[key] = content
    return list(seen.items())


def extract_for_keyword_group(
    name: str,
    fts_query: str,
    channels: list[str],
    max_results: int = 50,
) -> list[tuple[str, str]]:
    """Extract thread contexts for a keyword group, return [(thread_key, text)]."""
    hits = search_messages(fts_query, channels=channels)
    print(f"  {name}: {len(hits)} direct hits", file=sys.stderr)

    if not hits:
        return []

    # Limit to spread across time - take every Nth hit if too many
    if len(hits) > max_results:
        step = len(hits) // max_results
        hits = hits[::step][:max_results]

    threads = []
    for hit in hits:
        ctx = fetch_context(hit["channel_name"], hit["timestamp"])
        if not ctx:
            continue

        # Dedupe key: channel + hour
        hour_bucket = hit["timestamp"][:13]
        thread_key = f"{hit['channel_name']}|{hour_bucket}"

        text = format_thread(hit["channel_name"], ctx)
        threads.append((thread_key, text))

    return dedupe_threads(threads)


def main():
    parser = argparse.ArgumentParser(description="Extract regswap-related Discord threads")
    parser.add_argument("--output", help="Output file (default: stdout)")
    parser.add_argument("--keyword", help="Single keyword group to extract (default: all)")
    parser.add_argument(
        "--channels",
        nargs="+",
        default=["match-help", "general", "smash-bros-melee"],
        help="Channels to search (default: match-help, general, smash-bros-melee)",
    )
    parser.add_argument(
        "--max-per-group",
        type=int,
        default=40,
        help="Max threads per keyword group (default: 40)",
    )
    parser.add_argument("--list-keywords", action="store_true", help="List keyword groups and exit")
    args = parser.parse_args()

    if args.list_keywords:
        for name, query in KEYWORD_GROUPS:
            print(f"{name:30s}  {query}")
        return

    groups = KEYWORD_GROUPS
    if args.keyword:
        groups = [(n, q) for n, q in KEYWORD_GROUPS if n == args.keyword]
        if not groups:
            print(f"Unknown keyword group: {args.keyword}", file=sys.stderr)
            print("Available:", file=sys.stderr)
            for n, _ in KEYWORD_GROUPS:
                print(f"  {n}", file=sys.stderr)
            sys.exit(1)

    output_lines = []
    output_lines.append("# Register-swap related Discord discussions")
    output_lines.append(f"# Channels: {', '.join(args.channels)}")
    output_lines.append("")

    all_threads_seen = {}

    for name, fts_query in groups:
        print(f"Extracting {name}...", file=sys.stderr)
        threads = extract_for_keyword_group(name, fts_query, args.channels, args.max_per_group)
        print(f"  -> {len(threads)} unique threads", file=sys.stderr)

        if threads:
            output_lines.append(f"\n\n## {name}\n")

            new_threads = []
            for thread_key, text in threads:
                if thread_key in all_threads_seen:
                    continue
                all_threads_seen[thread_key] = name
                new_threads.append(text)

            print(f"  -> {len(new_threads)} new (after global dedup)", file=sys.stderr)
            output_lines.extend(new_threads)
            output_lines.append("")

    print(f"\nTotal unique threads: {len(all_threads_seen)}", file=sys.stderr)

    output = "\n".join(output_lines)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Wrote {len(output)} chars to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
