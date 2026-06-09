"""Small shared helpers — file paths and slug generation.

Keep this module dependency-free. Anything that needs the API or Pillow lives
in its own module so this stays cheap to import.
"""

from __future__ import annotations

import re
from pathlib import Path


def safe_slug(text: str, *, max_length: int = 60) -> str:
    """Convert arbitrary text to a filesystem-safe slug.

    Strips characters that misbehave in shell or filesystems on macOS/Linux,
    collapses whitespace to underscores, then truncates. Used to turn the
    prompt into an output filename.
    """
    cleaned = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned[:max_length] or "video"


def ensure_dir(path: Path) -> Path:
    """Create the directory if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
