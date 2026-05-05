from __future__ import annotations

import yaml
from pathlib import Path
from .schemas import BookProfile


def load_profile(path: Path) -> BookProfile:
    return BookProfile(**yaml.safe_load(path.open()))
