#!/usr/bin/env python3
"""Upscale an existing video with Real-ESRGAN on Modal — CLI entry point.

Usage:
    # 2x by default → output/<stem>_2x.mp4
    python upscale.py --input output/clip.mp4
    # levers
    python upscale.py --input output/clip.mp4 --scale 4 --model realesrgan-x4plus
    python upscale.py --input any/video.mp4 --output /tmp/big.mp4

Standalone post-processing: this never touches the Sora generation flow — it
takes any local mp4 (typically something from output/) and runs it through the
deployed Modal GPU app (see modal_upscaler.py). One-time setup:

    uv run modal setup          # Modal account/token
    make deploy-upscaler        # deploy the GPU app (rebuilds image on change)

An 8s 720x1280 clip takes ~1-2 min on the default model (a few cents of GPU
time), plus a ~30-60s cold start if the container has gone idle.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from config import DEFAULT_UPSCALE, OUTPUT_DIR, UPSCALE_MODELS
from modules.logging_setup import configure_logging
from modules.upscale_client import upscale_video
from modules.utils import ensure_dir


logger = logging.getLogger("upscale")


def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)
    load_dotenv()

    if not 1.0 < args.scale <= 4.0:
        logger.error("--scale must be in (1.0, 4.0], got %s", args.scale)
        return 2

    src = Path(args.input).expanduser()
    if not src.exists():
        logger.error("Input video not found: %s", src)
        return 2

    if args.output:
        dst = Path(args.output).expanduser()
    else:
        dst = OUTPUT_DIR / f"{src.stem}_{args.scale:g}x.mp4"
    ensure_dir(dst.parent)

    logger.info(
        "Upscaling %s at %sx with %s — a few minutes of GPU time on Modal",
        src.name, f"{args.scale:g}", args.model,
    )

    last_logged = -10.0

    def _on_progress(status: str, pct: float | None) -> None:
        nonlocal last_logged
        if pct is None:
            logger.info("Upscale: %s", status)
        elif pct - last_logged >= 10.0 or pct >= 99.0:
            last_logged = pct
            logger.info("Upscale: %s %3.0f%%", status, pct)

    try:
        upscale_video(
            src, dst,
            model=args.model,
            outscale=args.scale,
            on_progress=_on_progress,
        )
    except Exception as exc:
        logger.exception("Upscale failed: %s", exc)
        return 1

    print(f"\nDone! Output: {dst}")
    return 0


def _parse_args() -> argparse.Namespace:
    model_help = " · ".join(f"{name}: {desc}" for name, desc in UPSCALE_MODELS.items())
    parser = argparse.ArgumentParser(
        description="Upscale a local video with Real-ESRGAN running on a Modal GPU.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", required=True,
        help="Video to upscale (e.g. output/clip.mp4 — any local mp4 works).",
    )
    parser.add_argument(
        "--scale", type=float, default=DEFAULT_UPSCALE.outscale,
        help="Output size multiplier, up to 4 (default: %(default)s). "
        "720x1280 → 2x = 1440x2560, 4x = 2880x5120.",
    )
    parser.add_argument(
        "--model", default=DEFAULT_UPSCALE.model, choices=sorted(UPSCALE_MODELS),
        help=f"Real-ESRGAN model (default: %(default)s). {model_help}.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Where to write the result (default: output/<input-stem>_<scale>x.mp4).",
    )
    parser.add_argument("--verbose", action="store_true", help="Show DEBUG logs.")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
