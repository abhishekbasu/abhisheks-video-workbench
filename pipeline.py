#!/usr/bin/env python3
"""Image/text + prompt → video (OpenAI Sora) — CLI entry point.

Usage:
    # image-to-video
    python pipeline.py "a slow cinematic push-in" --image path/to/image.png
    # text-to-video (no seed image)
    python pipeline.py "a calico cat on a skateboard, neon city, night"
    # levers
    python pipeline.py "..." --image cat.jpg --model sora-2-pro --size 1024x1792 --seconds 12
    python pipeline.py "..." --image cat.jpg --mute            # strip audio (needs ffmpeg)
    python pipeline.py "..." --character char_abc --character char_def
    python pipeline.py "..." --image cat.jpg --dry-run         # no API call / no spend

Stages: (1) optional image prep (cover-crop to Sora's size) → (2) Sora generate
(create → poll → download) → output/<prompt-slug>.mp4 (+ .webp thumbnail,
.jpg spritesheet). For remix / extend / edit / character creation, use the
web app (`make serve`).

Idempotency: the *paid* job is resumed (not re-billed) for an identical request;
an already-downloaded clip is reused. Use --clean to reset.
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
from modules.postprocess import strip_audio
from modules.sora_client import SoraResult, generate_video
from modules.utils import ensure_dir, safe_slug


logger = logging.getLogger("pipeline")


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)
    load_dotenv()

    allowed_sizes = MODEL_SIZES[args.model]
    if args.size not in allowed_sizes:
        logger.error(
            "Size %s isn't supported by %s. Allowed: %s",
            args.size, args.model, ", ".join(allowed_sizes),
        )
        return 2

    config = PipelineConfig(
        sora=SoraSpec(model=args.model, size=args.size, seconds=args.seconds)
    )
    if args.clean:
        _wipe_tmp(config.tmp_dir)
    ensure_dir(config.tmp_dir)
    ensure_dir(config.output_dir)

    image_path = Path(args.image).expanduser() if args.image else None

    try:
        prepared = None
        if image_path is not None:
            video = VideoSpec.from_size(config.sora.size)
            logger.info(
                "[1/2] Preparing input image → %dx%d (cover-crop)",
                video.width, video.height,
            )
            prepared = prepare_input_image(
                image_path, output_path=config.tmp_dir / "input_prepared.png", video=video
            )
        else:
            logger.info("[1/2] Text-to-video (no seed image)")

        if args.dry_run:
            _print_dry_run(prepared, args=args)
            return 0

        if not os.getenv("OPENAI_API_KEY"):
            logger.error(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
            return 1

        logger.info(
            "[2/2] Generating video with Sora (model=%s, %ss) — this can take a few minutes",
            config.sora.model, config.sora.seconds,
        )
        result = generate_video(
            prompt=args.prompt,
            image_path=prepared,
            output_path=config.tmp_dir / "sora_raw.mp4",
            spec=config.sora,
            tmp_dir=config.tmp_dir,
            character_ids=args.character or None,
        )

        final_path = _finalize(result, prompt=args.prompt, config=config, mute=args.mute)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 1

    print(f"\nDone! Output: {final_path}")
    return 0


def _finalize(
    result: SoraResult, *, prompt: str, config: PipelineConfig, mute: bool
) -> Path:
    """Place the final mp4 (muted or copied) in output/, alongside thumb/spritesheet."""
    stem = safe_slug(prompt)
    final_path = config.output_dir / f"{stem}.mp4"
    if mute:
        strip_audio(result.video_path, final_path)
        logger.info("Muted (audio stripped) → %s", final_path.name)
    else:
        shutil.copy2(result.video_path, final_path)
        logger.info("Saved → %s", final_path.name)
    # Carry the thumbnail + spritesheet over too, when present.
    if result.thumbnail_path and result.thumbnail_path.exists():
        shutil.copy2(result.thumbnail_path, final_path.with_suffix(".webp"))
    if result.spritesheet_path and result.spritesheet_path.exists():
        shutil.copy2(result.spritesheet_path, final_path.with_suffix(".jpg"))
    return final_path


def _print_dry_run(prepared: Path | None, *, args: argparse.Namespace) -> None:
    print("\n--- DRY RUN (no API call, no spend) ---")
    print(f"  mode           : {'image-to-video' if prepared else 'text-to-video'}")
    if prepared:
        print(f"  prepared image : {prepared}  (resized to {args.size})")
    print(f"  model          : {args.model}")
    print(f"  size           : {args.size}")
    print(f"  seconds        : {args.seconds}")
    print(f"  characters     : {args.character or '(none)'}")
    print(f"  mute           : {args.mute}")
    print(f"  prompt         : {args.prompt}")
    print("---------------------------------------")


def _parse_args() -> argparse.Namespace:
    all_sizes = sorted({size for sizes in MODEL_SIZES.values() for size in sizes})
    parser = argparse.ArgumentParser(
        description="Generate a video from a prompt (and optional seed image) using OpenAI Sora.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", help="Text prompt describing the motion/scene.")
    parser.add_argument(
        "--image",
        default=None,
        help="Optional seed image (.jpg/.png/.webp). Omit for text-to-video.",
    )
    parser.add_argument(
        "--model", default="sora-2", choices=sorted(MODEL_SIZES),
        help="Sora model (default: sora-2). sora-2-pro is higher quality and pricier.",
    )
    parser.add_argument(
        "--size", default="720x1280", choices=all_sizes,
        help="Frame size; must be supported by the model (default: 720x1280, 9:16).",
    )
    parser.add_argument(
        "--seconds", default="8", choices=VALID_SECONDS,
        help="Clip duration in seconds (default: 8).",
    )
    parser.add_argument(
        "--character", action="append", metavar="CHAR_ID",
        help="Reference a reusable character by id (repeatable; ≤2 recommended).",
    )
    parser.add_argument(
        "--mute", action="store_true",
        help="Strip the audio track from the result (requires ffmpeg).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Prepare the image and print the request; skip the Sora call (no spend).",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Wipe tmp/ before starting (forces a fresh generation).",
    )
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG logs.")
    return parser.parse_args()


def _wipe_tmp(tmp_dir: Path) -> None:
    if tmp_dir.exists():
        logger.info("Wiping %s for a clean run", tmp_dir)
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    sys.exit(main())
