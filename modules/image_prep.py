"""Stage 1: Prepare the input image for Sora.

Sora's ``input_reference`` (the image that seeds image-to-video) must match
the generated video's ``size`` *exactly* — same width and height in pixels.
Arbitrary user images won't, so we cover-and-center crop the source to the
target resolution before handing it to the API.

"Cover" (not "fit") is deliberate: it scales so the image fills the whole
frame, then crops the overflow from the center. This never letterboxes — the
seed frame is edge-to-edge, which is what a video wants.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from config import VideoSpec


logger = logging.getLogger(__name__)

# Composite transparent images onto this neutral dark background rather than
# letting alpha go black/white unpredictably.
_ALPHA_BG = (16, 16, 16)


class ImagePrepError(RuntimeError):
    """Raised when the input image is missing or can't be processed."""


def prepare_input_image(
    src: Path, *, output_path: Path, video: VideoSpec
) -> Path:
    """Cover-crop ``src`` to the video's exact resolution; write a PNG.

    Always re-derived from ``src`` (a sub-second Pillow resize) rather than
    cached on ``output_path`` — otherwise a later run with a *different* source
    image would silently reuse the previous prep. Deduplication happens
    downstream instead: the Sora stage fingerprints the prepared image's bytes,
    so re-preparing an identical image still avoids a re-billed generation.

    Raises ``ImagePrepError`` for a missing file or an unreadable/corrupt image
    rather than letting a cryptic PIL error surface deep in the pipeline.
    """
    if not src.exists():
        raise ImagePrepError(
            f"Input image not found: {src}. Pass a path to a real .jpg/.png/.webp file."
        )

    target_w, target_h = video.width, video.height
    try:
        with Image.open(src) as img:
            img = _to_opaque_rgb(img)

            scale = max(target_w / img.width, target_h / img.height)
            new_size = (
                max(1, round(img.width * scale)),
                max(1, round(img.height * scale)),
            )
            scaled = img.resize(new_size, Image.LANCZOS)

            left = (scaled.width - target_w) // 2
            top = (scaled.height - target_h) // 2
            cropped = scaled.crop((left, top, left + target_w, top + target_h))
            cropped.save(output_path, format="PNG")
    except (OSError, ValueError) as exc:
        raise ImagePrepError(f"Could not process image {src}: {exc}") from exc

    logger.info(
        "Prepared %s → %dx%d %s", src.name, target_w, target_h, output_path.name
    )
    return output_path


def _to_opaque_rgb(img: Image.Image) -> Image.Image:
    """Convert to RGB, compositing transparent images onto a dark background."""
    if img.mode in ("RGBA", "LA", "PA"):
        background = Image.new("RGB", img.size, _ALPHA_BG)
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")
