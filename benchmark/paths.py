from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_data_path(path: Path | str) -> Path:
    """Resolve study inputs from a checkout or an installed wheel."""
    candidate = Path(path)
    if candidate.exists() or candidate.is_absolute():
        return candidate
    checkout = PROJECT_ROOT / candidate
    if checkout.exists():
        return checkout
    installed = Path(sys.prefix) / "share" / "depfailbench" / candidate
    if installed.exists():
        return installed
    return candidate
