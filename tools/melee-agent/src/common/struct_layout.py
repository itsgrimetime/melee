# src/common/struct_layout.py
"""Reusable MWCC offsetof-probe layout resolver.

Resolves struct field offsets by compiling a probe TU with the same
MWCC flags as the real build, then reading the .data symbol back from the
ELF object file.
"""
from __future__ import annotations

import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CflagsSpec:
    mw_version: str
    cflags: list[str]


def _read_ninja(repo: Path) -> str:
    return (repo / "build.ninja").read_text()


def _join_continuations(block: str) -> str:
    # ninja line continuation is "$\n" + leading whitespace
    return re.sub(r"\$\n\s*", " ", block)


def parse_tu_cflags(repo: Path, tu_src: str) -> CflagsSpec:
    """Extract mw_version + cflags for the build edge that compiles `tu_src`."""
    text = _read_ninja(repo)
    # find the build edge whose inputs include tu_src
    # edges look like: "build <out>: mwcc_sjis $\n    <src> ...\n  mw_version = ...\n  cflags = ... $\n      ...\n  basedir = ..."
    edges = re.split(r"\nbuild ", text)
    for edge in edges:
        if tu_src not in edge:
            continue
        joined = _join_continuations(edge)
        mw = re.search(r"mw_version = (\S+)", joined)
        cf = re.search(r"cflags = (.*?)(?:\n  \w+ =|\Z)", joined, re.S)
        if mw and cf:
            return CflagsSpec(mw.group(1).strip(), cf.group(1).split())
    raise ValueError(f"no build edge found for {tu_src}")
