"""Optional post-processing — requires ffmpeg on PATH.

The Sora API has no parameter to disable audio, so "mute" is done here by
stripping the audio track from the downloaded clip. Video is copied losslessly
(no re-encode), so it's fast. ffmpeg is only needed if you actually use this —
the rest of the app has no ffmpeg dependency.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


class PostProcessError(RuntimeError):
    """Raised when a post-processing step fails or ffmpeg is unavailable."""


def ffmpeg_available() -> bool:
    """True if ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def strip_audio(src: Path, dst: Path) -> Path:
    """Write ``dst`` = ``src`` with the audio track removed (video stream copied)."""
    if not ffmpeg_available():
        raise PostProcessError(
            "ffmpeg not found on PATH — needed to mute (strip audio).\n"
            "  macOS:        brew install ffmpeg\n"
            "  Ubuntu/Debian: sudo apt install ffmpeg"
        )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-an",                 # drop audio
        "-c:v", "copy",        # copy video losslessly
        "-movflags", "+faststart",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PostProcessError(
            f"ffmpeg failed to strip audio: exit={result.returncode}\n{result.stderr.strip()}"
        )
    logger.info("Stripped audio → %s", dst.name)
    return dst
