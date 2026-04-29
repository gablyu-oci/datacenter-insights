"""Pytest config: ensure the backend package root is on sys.path so
`agents`, `db`, `schemas`, etc. are importable when running tests from
inside backend/."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
