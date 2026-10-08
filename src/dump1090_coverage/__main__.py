"""Allow ``python -m dump1090_coverage`` as a synonym for the console script."""

from __future__ import annotations

import sys

from dump1090_coverage.cli import main

if __name__ == "__main__":
    sys.exit(main())
