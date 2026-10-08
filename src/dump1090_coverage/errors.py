"""Exceptions raised by dump1090-coverage.

Everything the CLI can fail on derives from :class:`CoverageError`, so the
command line has exactly one place to catch and format errors.
"""

from __future__ import annotations

__all__ = ["CoverageError", "InputError"]


class CoverageError(Exception):
    """Base class for every expected, user-facing failure."""


class InputError(CoverageError):
    """The input recording is missing, unreadable, malformed or empty."""
