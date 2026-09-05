"""Lifetime/layout pressure attribution for source-shape probes."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ..colorgraph_parser import find_function, parse_hook_events
from ..parser import Function, Pass, parse_pcdump
from ..simplify_search import baseline_signature
from ..source_spans import StatementSpan, list_statement_spans
from ..virtual_attribution import explain_virtuals

__all__ = [name for name in globals() if not name.startswith("__")]
