"""Per-category prompt fragments injected into the main classify prompt."""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent / "templates"


def load_template(name: str) -> str:
    p = _HERE / f"{name}.txt"
    return p.read_text() if p.exists() else ""
