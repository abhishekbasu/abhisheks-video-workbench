"""Centralized configuration for the Sora image-to-video app.

All tunable knobs live here so future tweaks have one obvious place to land.
Every other module reads from this — never hardcode specs in stage modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
TMP_DIR = PROJECT_ROOT / "tmp"
OUTPUT_DIR = PROJECT_ROOT / "output"


# OpenAI's Sora requires the ``input_reference`` image to exactly match the
# generated video's ``size``. Each model also gates which sizes it accepts:
# the base model is limited to 720p; the pro model unlocks the larger frames.
# Keys are the user-selectable model aliases; values are the allowed sizes.
MODEL_SIZES: dict[str, tuple[str, ...]] = {
    "sora-2": ("720x1280", "1280x720"),
    "sora-2-pro": ("720x1280", "1280x720", "1024x1792", "1792x1024"),
}

# Sora clip durations, in seconds, expressed as strings (the API takes a
# string here). The API default is "4"; we default to "8" as a more usable
# length while keeping all three documented values valid.
VALID_SECONDS: tuple[str, ...] = ("4", "8", "12")


@dataclass(frozen=True)
class SoraSpec:
    """OpenAI Sora (Videos API) generation settings.

    ``model`` defaults to the cheaper/faster ``sora-2`` for iterating on
    prompts; pass ``sora-2-pro`` for higher-fidelity renders. ``size`` must be
    one of the model's allowed sizes (see ``MODEL_SIZES``) and must match the
    prepared input image's resolution exactly.

    Generation is asynchronous: we create a job, then poll ``retrieve`` every
    ``poll_interval_seconds`` until it completes, giving up after
    ``timeout_seconds`` so a stuck job doesn't hang forever.
    """

    model: str = "sora-2"
    size: str = "720x1280"  # 9:16 vertical
    seconds: str = "8"
    poll_interval_seconds: float = 5.0
    timeout_seconds: float = 900.0
    download_thumbnail: bool = True


@dataclass(frozen=True)
class VideoSpec:
    """Target frame size, derived from the chosen Sora ``size`` string.

    Used by the image-prep stage to cover-crop the seed image to Sora's exact
    required resolution.
    """

    width: int = 720
    height: int = 1280

    @property
    def size_str(self) -> str:
        return f"{self.width}x{self.height}"

    @classmethod
    def from_size(cls, size: str) -> "VideoSpec":
        """Build a VideoSpec from a Sora size string like ``"720x1280"``."""
        width_str, _, height_str = size.lower().partition("x")
        return cls(width=int(width_str), height=int(height_str))


@dataclass(frozen=True)
class PipelineConfig:
    """Top-level config — composed of the sub-specs and output paths."""

    sora: SoraSpec = field(default_factory=SoraSpec)
    tmp_dir: Path = field(default_factory=lambda: TMP_DIR)
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)


DEFAULT_CONFIG = PipelineConfig()
