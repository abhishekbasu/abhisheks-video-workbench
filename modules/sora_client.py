"""Stage 2: Generate the video with OpenAI Sora (Videos API).

Generation is asynchronous and *paid*, so this module is built around two
ideas: surface failures clearly, and never pay twice for the same request.

Flow:
  1. Compute a request fingerprint (model, size, seconds, prompt, image bytes).
  2. If a finished clip is cached for an identical request → return it.
  3. If a job for an identical request is still cached → resume polling it
     (a crash mid-poll shouldn't re-bill a new generation).
  4. Otherwise create a new job, persisting its id immediately.
  5. Poll until completed / failed / timeout, then download the MP4.

The whole OpenAI surface is confined to this file. The Videos API + sora-2 /
sora-2-pro are slated for shutdown on 2026-09-24; when a successor lands,
this is the only module that should need to change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from config import SoraSpec


logger = logging.getLogger(__name__)

_JOB_FILE_NAME = "sora_job.json"
# Terminal job states reported by the Videos API.
_DONE = "completed"
_FAILED = "failed"


class SoraError(RuntimeError):
    """Raised when Sora generation fails, times out, or the API errors."""


@dataclass(frozen=True)
class SoraResult:
    """Paths to the generated assets."""

    video_path: Path
    thumbnail_path: Path | None = None


def generate_video(
    *,
    prompt: str,
    image_path: Path,
    output_path: Path,
    thumbnail_path: Path | None,
    spec: SoraSpec,
    tmp_dir: Path,
    on_progress=None,
) -> SoraResult:
    """Create (or resume/reuse) a Sora image-to-video job and download the MP4.

    ``image_path`` is the already-prepared seed frame (exact ``spec.size``).
    ``output_path`` is where the raw downloaded clip lands. ``on_progress`` is
    an optional ``callable(status: str, progress: int | None)`` invoked on each
    poll (used by the dashboard for a live progress bar).
    """
    params = _fingerprint(prompt=prompt, image_path=image_path, spec=spec)
    job_file = tmp_dir / _JOB_FILE_NAME
    saved = _read_json(job_file)
    same_request = saved.get("params") == params

    # 2. Finished clip already on disk for this exact request.
    if output_path.exists() and same_request:
        logger.info(
            "Sora clip cached for identical request → %s (skipping generation)",
            output_path.name,
        )
        cached_thumb = (
            thumbnail_path if thumbnail_path and thumbnail_path.exists() else None
        )
        return SoraResult(output_path, cached_thumb)

    client = OpenAI()

    # 3. Resume an in-flight job for the same request, else 4. create one.
    if saved.get("id") and same_request:
        video_id = saved["id"]
        logger.info("Resuming existing Sora job %s for identical request", video_id)
    else:
        video_id = _create_job(
            client, prompt=prompt, image_path=image_path, spec=spec
        )
        _write_json(job_file, {"id": video_id, "params": params})

    # 5. Poll to completion, then download.
    final = _poll(client, video_id, spec, on_progress=on_progress)
    if getattr(final, "status", None) == _FAILED:
        raise SoraError(
            f"Sora job {video_id} failed: {_error_text(final)}. "
            f"Re-run with --clean to start a fresh generation."
        )

    _download(client, video_id, output_path, variant="video")
    logger.info("Downloaded Sora clip → %s", output_path.name)

    thumb: Path | None = None
    if thumbnail_path is not None and spec.download_thumbnail:
        try:
            _download(client, video_id, thumbnail_path, variant="thumbnail")
            thumb = thumbnail_path
        except Exception as exc:  # noqa: BLE001 — thumbnail is best-effort
            logger.warning("Thumbnail download failed (non-fatal): %s", exc)

    return SoraResult(output_path, thumb)


# ────────────────────────────────────────────────────────────────────────────
# OpenAI calls
# ────────────────────────────────────────────────────────────────────────────


def _create_job(
    client: OpenAI, *, prompt: str, image_path: Path, spec: SoraSpec
) -> str:
    """Create a Sora image-to-video job; return its id.

    The seed image is passed as a file handle (multipart upload). The API
    requires the image's resolution to equal ``spec.size`` — image_prep
    guarantees that upstream.
    """
    logger.info(
        "Creating Sora job: model=%s size=%s seconds=%s",
        spec.model,
        spec.size,
        spec.seconds,
    )
    try:
        with open(image_path, "rb") as image_file:
            video = client.videos.create(
                model=spec.model,
                prompt=prompt,
                size=spec.size,
                seconds=spec.seconds,
                input_reference=image_file,
            )
    except Exception as exc:  # noqa: BLE001 — wrap any SDK/transport error
        raise SoraError(f"Failed to create Sora job: {exc}") from exc

    logger.info("Created Sora job %s (status=%s)", video.id, getattr(video, "status", "?"))
    return video.id


def _poll(client: OpenAI, video_id: str, spec: SoraSpec, *, on_progress=None):
    """Poll ``retrieve`` until the job is terminal or times out."""
    start = time.monotonic()
    last_logged: object = None
    while True:
        try:
            video = client.videos.retrieve(video_id)
        except Exception as exc:  # noqa: BLE001
            raise SoraError(f"Failed to poll Sora job {video_id}: {exc}") from exc

        status = getattr(video, "status", None)
        progress = getattr(video, "progress", None)
        marker = (status, progress)
        if marker != last_logged:
            pct = f" ({progress}%)" if progress is not None else ""
            logger.info("Sora job %s: %s%s", video_id, status, pct)
            last_logged = marker
        if on_progress is not None:
            try:
                on_progress(status, progress)
            except Exception:  # noqa: BLE001 — never let a UI callback break generation
                pass

        if status in (_DONE, _FAILED):
            return video

        if time.monotonic() - start > spec.timeout_seconds:
            raise SoraError(
                f"Sora job {video_id} timed out after "
                f"{spec.timeout_seconds:.0f}s (last status: {status}). "
                f"The job may still finish — re-run to resume polling it."
            )
        time.sleep(spec.poll_interval_seconds)


def _download(
    client: OpenAI, video_id: str, output_path: Path, *, variant: str
) -> None:
    """Download a job asset (``video`` or ``thumbnail``) to disk."""
    content = client.videos.download_content(video_id, variant=variant)
    content.write_to_file(str(output_path))


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────


def _fingerprint(*, prompt: str, image_path: Path, spec: SoraSpec) -> dict:
    """Identify a request so an unrelated change invalidates the cache.

    Hashing the prepared image's bytes (not just its name — the prepared file
    always has the same name) means swapping the source image forces a fresh
    generation instead of silently reusing the previous clip.
    """
    image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
    return {
        "model": spec.model,
        "size": spec.size,
        "seconds": spec.seconds,
        "prompt": prompt,
        "image_sha": image_sha,
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _error_text(video) -> str:
    """Extract a human-readable message from a failed job's ``error`` field."""
    err = getattr(video, "error", None)
    if err is None:
        return "unknown error"
    message = getattr(err, "message", None)
    if message:
        return str(message)
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)
