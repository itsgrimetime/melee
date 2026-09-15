#!/usr/bin/env python3
"""Extract Discord archive data by channel and time period.

Usage:
    python tools/discord_extract.py list-months smash-bros-melee
    python tools/discord_extract.py extract smash-bros-melee 2022-02
    python tools/discord_extract.py stats smash-bros-melee
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / "code/index/discord_archive_gc-wii-decomp.db"


def get_connection():
    """Get database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def list_months(channel: str) -> list[dict]:
    """List all months with message counts for a channel."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            strftime('%Y-%m', timestamp) as month,
            COUNT(*) as msg_count,
            MIN(date(timestamp)) as first_day,
            MAX(date(timestamp)) as last_day
        FROM messages
        WHERE channel_name = ?
        GROUP BY month
        ORDER BY month
    """, (channel,))

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def extract_month(channel: str, month: str, format: str = "text") -> str | dict:
    """Extract all messages for a specific month.

    Args:
        channel: Channel name
        month: Month in YYYY-MM format
        format: "text" for readable format, "json" for structured
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Parse month to get date range
    year, mon = month.split("-")
    start = f"{year}-{mon}-01"
    # Handle month overflow
    next_mon = int(mon) + 1
    if next_mon > 12:
        next_mon = 1
        year = str(int(year) + 1)
    end = f"{year}-{next_mon:02d}-01"

    cursor.execute("""
        SELECT
            id,
            timestamp,
            author_name,
            content,
            is_reply,
            reply_to_id
        FROM messages
        WHERE channel_name = ?
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY timestamp
    """, (channel, start, end))

    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if format == "json":
        return {
            "channel": channel,
            "month": month,
            "message_count": len(messages),
            "messages": messages
        }

    # Text format for agent consumption
    lines = [
        f"# Discord Archive: #{channel} - {month}",
        f"# {len(messages)} messages",
        "",
    ]

    current_date = None
    for msg in messages:
        # Add date separator
        msg_date = msg["timestamp"][:10]
        if msg_date != current_date:
            current_date = msg_date
            lines.append(f"\n--- {current_date} ---\n")

        time = msg["timestamp"][11:16]  # HH:MM
        author = msg["author_name"]
        content = msg["content"]

        # Mark replies
        prefix = "↳ " if msg["is_reply"] else ""

        lines.append(f"[{time}] {prefix}{author}: {content}")

    return "\n".join(lines)


def get_stats(channel: str) -> dict:
    """Get statistics for a channel."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) as total_messages,
            COUNT(DISTINCT author_name) as unique_authors,
            MIN(timestamp) as first_message,
            MAX(timestamp) as last_message,
            AVG(length(content)) as avg_content_length,
            SUM(length(content)) as total_chars
        FROM messages
        WHERE channel_name = ?
    """, (channel,))

    stats = dict(cursor.fetchone())

    # Get top authors
    cursor.execute("""
        SELECT author_name, COUNT(*) as msg_count
        FROM messages
        WHERE channel_name = ?
        GROUP BY author_name
        ORDER BY msg_count DESC
        LIMIT 10
    """, (channel,))

    stats["top_authors"] = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract Discord archive data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list-months command
    list_parser = subparsers.add_parser("list-months", help="List months with message counts")
    list_parser.add_argument("channel", help="Channel name")

    # extract command
    extract_parser = subparsers.add_parser("extract", help="Extract messages for a month")
    extract_parser.add_argument("channel", help="Channel name")
    extract_parser.add_argument("month", help="Month in YYYY-MM format")
    extract_parser.add_argument("--format", choices=["text", "json"], default="text")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Get channel statistics")
    stats_parser.add_argument("channel", help="Channel name")

    args = parser.parse_args()

    if args.command == "list-months":
        result = list_months(args.channel)
        print(json.dumps(result, indent=2))

    elif args.command == "extract":
        result = extract_month(args.channel, args.month, args.format)
        if isinstance(result, dict):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result)

    elif args.command == "stats":
        result = get_stats(args.channel)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
