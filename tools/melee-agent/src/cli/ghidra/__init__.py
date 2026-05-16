"""Ghidra integration package.

Temporary shim: re-exports ``ghidra_app`` from the pre-package legacy module
(``cli/_ghidra_legacy.py``) so that ``from .ghidra import ghidra_app`` in
``cli/__init__.py`` keeps working while this package is being built out.

Task 3 of the ghidra-skill-revival plan moves the legacy module's contents
into ``cli/ghidra/cli.py`` and replaces this re-export with
``from .cli import ghidra_app``.
"""
from .._ghidra_legacy import ghidra_app

__all__ = ["ghidra_app"]
