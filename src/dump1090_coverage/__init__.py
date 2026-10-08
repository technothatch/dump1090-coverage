"""dump1090-coverage — coverage and range analysis for recorded ADS-B traffic."""

from __future__ import annotations

from dump1090_coverage.analysis import Report, build_report, percentile
from dump1090_coverage.models import Observation

__version__ = "0.1.0"

__all__ = ["Observation", "Report", "__version__", "build_report", "percentile"]
