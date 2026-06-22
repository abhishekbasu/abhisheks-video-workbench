"""Optional post-processing — requires ffmpeg on PATH.

The Sora API has no parameter to disable audio, so "mute" is done here by
stripping the audio track from the downloaded clip. Video is copied losslessly
(no re-encode), so it's fast. This module also overlays a branding logo as a
corner watermark (which does re-encode the video). ffmpeg is only needed if you
actually use these — the rest of the app has no ffmpeg dependency.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)

# Where a watermark sits, and the ffmpeg overlay x/y for each (M = margin px).
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")


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


def _video_dimensions(src: Path) -> tuple[int, int]:
    """Return (width, height) of ``src``'s first video stream via ffprobe."""
    if shutil.which("ffprobe") is None:
        raise PostProcessError("ffprobe not found on PATH (ships with ffmpeg).")
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PostProcessError(f"ffprobe failed to read {src.name}:\n{result.stderr.strip()}")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError) as exc:
        raise PostProcessError(f"Couldn't read video dimensions from {src.name}.") from exc


def overlay_logo(
    src: Path,
    logo: Path,
    dst: Path,
    *,
    corner: str = "bottom-right",
    opacity: float = 0.9,
    scale: float = 0.18,
    margin: float = 0.04,
) -> Path:
    """Overlay ``logo`` onto ``src`` as a corner watermark; write ``dst``.

    ``corner`` is one of :data:`CORNERS`. ``scale`` and ``margin`` are fractions
    of the *video width* (logo target width and inset, respectively). ``opacity``
    (0–1) multiplies the logo's own alpha — a transparent PNG stays transparent.
    The video is re-encoded (overlay can't be stream-copied); audio is copied.
    """
    if not ffmpeg_available():
        raise PostProcessError("ffmpeg not found on PATH — needed to overlay a logo.")
    if not src.exists():
        raise PostProcessError(f"Video not found: {src}")
    if not logo.exists():
        raise PostProcessError(f"Logo not found: {logo}")
    if corner not in CORNERS:
        raise PostProcessError(f"corner must be one of {', '.join(CORNERS)} (got {corner!r}).")

    vw, vh = _video_dimensions(src)
    # Logo's native aspect (Pillow) → target pixel size from the video width.
    try:
        from PIL import Image

        with Image.open(logo) as im:
            lw0, lh0 = im.size
    except Exception as exc:  # noqa: BLE001
        raise PostProcessError(f"Couldn't read logo image {logo.name}: {exc}") from exc

    target_w = max(1, round(vw * scale))
    target_h = max(1, round(target_w * lh0 / lw0))
    m = round(vw * margin)

    x = m if corner in ("top-left", "bottom-left") else vw - target_w - m
    y = m if corner in ("top-left", "top-right") else vh - target_h - m

    opacity = max(0.0, min(1.0, opacity))
    filter_complex = (
        f"[1:v]scale={target_w}:{target_h},format=rgba,"
        f"colorchannelmixer=aa={opacity:.3f}[wm];"
        f"[0:v][wm]overlay={x}:{y}:format=auto"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-i", str(logo),
        "-filter_complex", filter_complex,
        "-c:a", "copy",                # keep audio untouched
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast",
        "-movflags", "+faststart",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PostProcessError(
            f"ffmpeg failed to overlay logo: exit={result.returncode}\n{result.stderr.strip()}"
        )
    logger.info("Overlaid %s on %s (%s) → %s", logo.name, src.name, corner, dst.name)
    return dst
