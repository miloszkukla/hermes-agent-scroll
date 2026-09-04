"""Make the unmodified upstream tests import the vendored package tree."""

from __future__ import annotations

import sys
from pathlib import Path


_VENDOR_ROOT = Path(__file__).resolve().parents[1]
if str(_VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_VENDOR_ROOT))
