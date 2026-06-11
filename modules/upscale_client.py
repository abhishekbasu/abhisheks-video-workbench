"""Remote video upscaling — Real-ESRGAN running on Modal.

The GPU side lives in ``modal_upscaler.py`` (repo root) and is deployed once
with ``make deploy-upscaler``. This module is the thin local client: it looks
the deployed app up by name, streams the clip's bytes through the remote
generator, relays progress events, and writes the upscaled result atomically.

Needs Modal credentials (one-time ``uv run modal setup``) — no local GPU,
torch, or ffmpeg required for this path.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import modal

from config import DEFAULT_UPSCALE, UPSCALE_MODELS, UpscaleSpec
from modules.utils import ensure_dir


logger = logging.getLogger(__name__)

# Same shape as the Sora client's callback: (status, percent-or-None).
ProgressCallback = Callable[[str, float | None], None]


class UpscaleError(RuntimeError):
    """Raised when the remote upscale fails or Modal isn't set up/deployed."""


def modal_configured() -> bool:
    """True if Modal credentials exist (env token or ~/.modal.toml)."""
    return bool(os.environ.get("MODAL_TOKEN_ID")) or (Path.home() / ".modal.toml").exists()


def upscale_video(
    src: Path,
    dst: Path,
    *,
    model: str = DEFAULT_UPSCALE.model,
    outscale: float = DEFAULT_UPSCALE.outscale,
    spec: UpscaleSpec = DEFAULT_UPSCALE,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Upscale ``src`` to ``dst`` via the deployed Modal Real-ESRGAN app.

    Blocks until done (an 8s clip takes ~1-2 min on the fast models, plus a
    cold start after idle). Progress arrives through ``on_progress`` as the
    remote generator yields. The result is written to ``dst`` atomically
    (``.part`` then rename), so an interrupted run never leaves a truncated mp4.
    """
    if not src.exists():
        raise UpscaleError(f"Input video not found: {src}")
    if model not in UPSCALE_MODELS:
        raise UpscaleError(
            f"Unknown model {model!r} — choose from: {', '.join(UPSCALE_MODELS)}"
        )
    if not modal_configured():
        raise UpscaleError(
            "Modal isn't set up — run `uv run modal setup` once (a free account works)."
        )

    def _notify(status: str, pct: float | None) -> None:
        if on_progress is None:
            return
        try:
            on_progress(status, pct)
        except Exception:  # noqa: BLE001 — a UI callback must never kill the job
            logger.debug("on_progress callback raised", exc_info=True)

    logger.info(
        "Upscaling %s with %s at %sx on Modal app %r",
        src.name, model, f"{outscale:g}", spec.app_name,
    )
    _notify("contacting Modal", None)

    result: bytes | None = None
    try:
        upscaler_cls = modal.Cls.from_name(spec.app_name, spec.class_name)
        events = upscaler_cls().upscale.remote_gen(src.read_bytes(), model, outscale)
        for event in events:
            kind = event.get("kind")
            if kind == "start":
                logger.info(
                    "Remote: %s frames @ %s fps → %sx%s",
                    event.get("total") or "?", event.get("fps"),
                    event.get("width"), event.get("height"),
                )
                _notify("upscaling", 0.0)
            elif kind == "progress":
                total = event.get("total")
                pct = round(event["done"] / total * 100.0) if total else None
                _notify("upscaling", pct)
            elif kind == "result":
                result = event["data"]
                _notify("saving", 99.0)
    except modal.exception.NotFoundError as exc:
        raise UpscaleError(
            f"Upscaler app {spec.app_name!r} isn't deployed — run `make deploy-upscaler` once."
        ) from exc
    except modal.exception.AuthError as exc:
        raise UpscaleError(
            "Modal auth failed — run `uv run modal setup` to (re)authenticate."
        ) from exc
    except modal.exception.FunctionTimeoutError as exc:
        raise UpscaleError(
            "Remote upscale timed out (>1h) — try a shorter clip or a faster model."
        ) from exc
    except (ValueError, RuntimeError) as exc:
        # The remote raises builtins by design: ValueError for bad input
        # (corrupt video, unknown model), RuntimeError for GPU OOM / encoder
        # failures — both arrive with actionable messages.
        raise UpscaleError(str(exc)) from exc

    if result is None:
        raise UpscaleError("Remote upscaler returned no result.")

    ensure_dir(dst.parent)
    part = dst.with_suffix(".part")
    part.write_bytes(result)
    os.replace(part, dst)
    logger.info(
        "Upscaled (%s, %sx) → %s (%.1f MB)",
        model, f"{outscale:g}", dst.name, len(result) / 1e6,
    )
    return dst
