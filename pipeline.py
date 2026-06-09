#!/usr/bin/env python3
"""Image + prompt → video (OpenAI Sora) — main entry point.

Usage:
    python pipeline.py path/to/image.png "a slow cinematic push-in, rain on the glass"
    python pipeline.py cat.jpg "the cat turns and looks at the camera" --model sora-2-pro --size 1024x1792
    python pipeline.py cat.jpg "..." --seconds 12
    python pipeline.py cat.jpg "..." --dry-run        # prep + print request, no API spend

Stages:
    1. Image prep      (Pillow → cover-crop to Sora's exact size)
    2. Sora generation (Videos API: create → poll → download)
    → output/<prompt-slug>.mp4

Idempotency: the *paid* Sora job is resumed (not re-billed) when the request is
unchanged, and an already-downloaded clip is reused. Image prep always
re-derives from the current source. Use --clean to reset everything.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from config import MODEL_SIZES, VALID_SECONDS, PipelineConfig, SoraSpec, VideoSpec
from modules.image_prep import prepare_input_image
from modules.logging_setup import configure_logging
from modules.sora_client import generate_video
from modules.utils import ensure_dir, safe_slug


logger = logging.getLogger("pipeline")


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)
    load_dotenv()

    # Validate the model/size pairing up front — Sora rejects unsupported
    # sizes per model, and we'd rather fail before spending anything.
    allowed_sizes = MODEL_SIZES[args.model]
    if args.size not in allowed_sizes:
        logger.error(
            "Size %s isn't supported by %s. Allowed: %s",
            args.size,
            args.model,
            ", ".join(allowed_sizes),
        )
        return 2

    config = PipelineConfig(
        sora=SoraSpec(model=args.model, size=args.size, seconds=args.seconds)
    )
    if args.clean:
        _wipe_tmp(config.tmp_dir)
    ensure_dir(config.tmp_dir)
    ensure_dir(config.output_dir)

    video = VideoSpec.from_size(config.sora.size)
    image_path = Path(args.image).expanduser()

    try:
        prepared = _stage_image_prep(image_path, config=config, video=video)

        if args.dry_run:
            _print_dry_run(prepared, prompt=args.prompt, sora=config.sora)
            return 0

        if not os.getenv("OPENAI_API_KEY"):
            logger.error(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add "
                "your key (or export it in the shell)."
            )
            return 1

        raw_clip = _stage_sora(prepared, prompt=args.prompt, config=config)

        final_path = config.output_dir / f"{safe_slug(args.prompt)}.mp4"
        shutil.copy2(raw_clip, final_path)
        logger.info("Saved → %s", final_path.name)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 1

    print(f"\nDone! Output: {final_path}")
    return 0


# ────────────────────────────────────────────────────────────────────────────
# Stage runners
# ────────────────────────────────────────────────────────────────────────────


def _stage_image_prep(
    image_path: Path, *, config: PipelineConfig, video: VideoSpec
) -> Path:
    logger.info(
        "[1/2] Preparing input image → %dx%d (cover-crop)", video.width, video.height
    )
    return prepare_input_image(
        image_path, output_path=config.tmp_dir / "input_prepared.png", video=video
    )


def _stage_sora(prepared: Path, *, prompt: str, config: PipelineConfig) -> Path:
    logger.info(
        "[2/2] Generating video with Sora (model=%s, %ss) — this can take a few minutes",
        config.sora.model,
        config.sora.seconds,
    )
    thumb = config.tmp_dir / "sora_thumb.webp" if config.sora.download_thumbnail else None
    result = generate_video(
        prompt=prompt,
        image_path=prepared,
        output_path=config.tmp_dir / "sora_raw.mp4",
        thumbnail_path=thumb,
        spec=config.sora,
        tmp_dir=config.tmp_dir,
    )
    return result.video_path


def _print_dry_run(prepared: Path, *, prompt: str, sora: SoraSpec) -> None:
    """Report exactly what would be sent to Sora — without calling it."""
    print("\n--- DRY RUN (no API call, no spend) ---")
    print(f"  prepared image : {prepared}  (resized to {sora.size})")
    print(f"  model          : {sora.model}")
    print(f"  size           : {sora.size}")
    print(f"  seconds        : {sora.seconds}")
    print(f"  prompt         : {prompt}")
    print("---------------------------------------")


# ────────────────────────────────────────────────────────────────────────────
# CLI plumbing
# ────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    all_sizes = sorted({size for sizes in MODEL_SIZES.values() for size in sizes})
    parser = argparse.ArgumentParser(
        description="Generate a video from an image + prompt using OpenAI Sora.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="Path to the seed image (.jpg/.png/.webp).")
    parser.add_argument("prompt", help="Text prompt describing the motion/scene.")
    parser.add_argument(
        "--model",
        default="sora-2",
        choices=sorted(MODEL_SIZES),
        help="Sora model (default: sora-2). sora-2-pro is higher quality and pricier.",
    )
    parser.add_argument(
        "--size",
        default="720x1280",
        choices=all_sizes,
        help="Frame size; must be supported by the model (default: 720x1280, 9:16).",
    )
    parser.add_argument(
        "--seconds",
        default="8",
        choices=VALID_SECONDS,
        help="Clip duration in seconds (default: 8).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare the image and print the request; skip the Sora call (no spend).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe tmp/ before starting (forces a fresh generation).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show DEBUG logs.",
    )
    return parser.parse_args()


def _wipe_tmp(tmp_dir: Path) -> None:
    if tmp_dir.exists():
        logger.info("Wiping %s for a clean run", tmp_dir)
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    sys.exit(main())
