"""All OpenAI Sora (Videos API) operations — the single OpenAI surface.

Capabilities:
  * generate   — text-to-video (prompt only) or image-to-video (seed image),
                 optionally referencing reusable characters.
  * remix      — a variation of a finished clip from a new prompt.
  * extend     — continue a finished clip by +4/8/12s.
  * edit       — prompt-based edit of a finished clip.
  * characters — create_character (from an uploaded clip) + get_character.
  * downloads  — the mp4 plus its thumbnail and spritesheet.

Generation is async and *paid*, so ``generate_video`` keeps a request
fingerprint in ``tmp/sora_job.json``: an identical re-run resumes the cached
job (or reuses the downloaded clip) instead of paying twice. remix/extend/edit
are explicit one-offs and aren't cached.

Deprecation: the Videos API + sora-2/sora-2-pro shut down 2026-09-24; when a
successor lands, this is the only module that should need to change.
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
_DONE = "completed"
_FAILED = "failed"


class SoraError(RuntimeError):
    """Raised when a Sora operation fails, times out, or the API errors."""


@dataclass(frozen=True)
class SoraResult:
    """Paths to the assets produced by a generation/remix/extend/edit."""

    video_id: str
    video_path: Path
    thumbnail_path: Path | None = None
    spritesheet_path: Path | None = None


# ────────────────────────────────────────────────────────────────────────────
# Generate (create) — text- or image-to-video, optional characters
# ────────────────────────────────────────────────────────────────────────────


def generate_video(
    *,
    prompt: str,
    image_path: Path | None = None,
    output_path: Path,
    spec: SoraSpec,
    tmp_dir: Path,
    character_ids: list[str] | None = None,
    on_progress=None,
    download_variants: bool = True,
) -> SoraResult:
    """Create (or resume/reuse) a Sora job and download the result.

    ``image_path=None`` → text-to-video (prompt only). ``character_ids`` are
    passed in the create request's ``characters`` array (via ``extra_body``,
    since the SDK has no named param) so a created character recurs in the clip.
    """
    params = _fingerprint(
        prompt=prompt, image_path=image_path, spec=spec, character_ids=character_ids
    )
    job_file = tmp_dir / _JOB_FILE_NAME
    saved = _read_json(job_file)
    same_request = saved.get("params") == params

    if output_path.exists() and same_request:
        logger.info(
            "Sora clip cached for identical request → %s (skipping generation)",
            output_path.name,
        )
        return _result_from_existing(saved.get("id", ""), output_path, download_variants)

    client = OpenAI()

    if saved.get("id") and same_request:
        video_id = saved["id"]
        logger.info("Resuming existing Sora job %s for identical request", video_id)
    else:
        video_id = _create(
            client, prompt=prompt, image_path=image_path, spec=spec,
            character_ids=character_ids,
        )
        _write_json(job_file, {"id": video_id, "params": params})

    return _finish(client, video_id, output_path, spec, on_progress, download_variants)


def _create(
    client: OpenAI, *, prompt, image_path, spec: SoraSpec, character_ids
) -> str:
    """POST /videos. Seed image (if any) is a multipart file; characters go in extra_body."""
    kwargs: dict = {
        "model": spec.model,
        "prompt": prompt,
        "size": spec.size,
        "seconds": spec.seconds,
    }
    if character_ids:
        kwargs["extra_body"] = {"characters": [{"id": c} for c in character_ids]}

    mode = "image-to-video" if image_path is not None else "text-to-video"
    logger.info(
        "Creating Sora job: %s, model=%s size=%s seconds=%s%s",
        mode, spec.model, spec.size, spec.seconds,
        f", characters={character_ids}" if character_ids else "",
    )
    try:
        if image_path is not None:
            with open(image_path, "rb") as image_file:
                video = client.videos.create(input_reference=image_file, **kwargs)
        else:
            video = client.videos.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 — wrap any SDK/transport error
        raise SoraError(f"Failed to create Sora job: {exc}") from exc

    logger.info("Created Sora job %s (status=%s)", video.id, getattr(video, "status", "?"))
    return video.id


# ────────────────────────────────────────────────────────────────────────────
# Remix / extend / edit — operate on a finished clip by id
# ────────────────────────────────────────────────────────────────────────────


def remix_video(
    *, video_id, prompt, output_path, spec, on_progress=None, download_variants=True
) -> SoraResult:
    """Generate a variation of ``video_id`` from a new prompt."""
    client = OpenAI()
    try:
        new = client.videos.remix(video_id=video_id, prompt=prompt)
    except Exception as exc:  # noqa: BLE001
        raise SoraError(f"Failed to remix {video_id}: {exc}") from exc
    logger.info("Remix job %s (from %s)", new.id, video_id)
    return _finish(client, new.id, output_path, spec, on_progress, download_variants)


def extend_video(
    *, video_id, prompt, seconds, output_path, spec, on_progress=None,
    download_variants=True,
) -> SoraResult:
    """Continue ``video_id`` with a +``seconds`` segment guided by ``prompt``."""
    client = OpenAI()
    try:
        new = client.videos.extend(
            video={"id": video_id}, prompt=prompt, seconds=seconds
        )
    except Exception as exc:  # noqa: BLE001
        raise SoraError(f"Failed to extend {video_id}: {exc}") from exc
    logger.info("Extend job %s (from %s, +%ss)", new.id, video_id, seconds)
    return _finish(client, new.id, output_path, spec, on_progress, download_variants)


def edit_video(
    *, video_id, prompt, output_path, spec, on_progress=None, download_variants=True
) -> SoraResult:
    """Apply a prompt-based edit to ``video_id``."""
    client = OpenAI()
    try:
        new = client.videos.edit(video={"id": video_id}, prompt=prompt)
    except Exception as exc:  # noqa: BLE001
        raise SoraError(f"Failed to edit {video_id}: {exc}") from exc
    logger.info("Edit job %s (from %s)", new.id, video_id)
    return _finish(client, new.id, output_path, spec, on_progress, download_variants)


# ────────────────────────────────────────────────────────────────────────────
# Characters (reusable, consistent subjects)
# ────────────────────────────────────────────────────────────────────────────


def create_character(*, name: str, video_path: Path) -> dict:
    """Create a reusable character from an uploaded clip; return its record (has ``id``)."""
    client = OpenAI()
    try:
        with open(video_path, "rb") as clip:
            resp = client.videos.create_character(name=name, video=clip)
    except Exception as exc:  # noqa: BLE001
        raise SoraError(f"Failed to create character {name!r}: {exc}") from exc
    data = resp.model_dump()
    logger.info("Created character %r → id=%s", name, data.get("id"))
    return data


def get_character(character_id: str) -> dict:
    """Look up a character by id."""
    client = OpenAI()
    try:
        return client.videos.get_character(character_id).model_dump()
    except Exception as exc:  # noqa: BLE001
        raise SoraError(f"Failed to get character {character_id}: {exc}") from exc


# ────────────────────────────────────────────────────────────────────────────
# Shared: poll + download
# ────────────────────────────────────────────────────────────────────────────


def _finish(
    client, video_id, output_path: Path, spec: SoraSpec, on_progress, download_variants
) -> SoraResult:
    """Poll a job to completion, download the mp4 (+ optional thumb/spritesheet)."""
    final = _poll(client, video_id, spec, on_progress=on_progress)
    if getattr(final, "status", None) == _FAILED:
        raise SoraError(
            f"Sora job {video_id} failed: {_error_text(final)}. "
            f"Re-run with a fresh request (or --clean) to retry."
        )
    _download(client, video_id, output_path, variant="video")
    logger.info("Downloaded Sora clip → %s", output_path.name)

    thumb = sprite = None
    if download_variants:
        thumb = _try_download(client, video_id, output_path.with_suffix(".webp"), "thumbnail")
        sprite = _try_download(client, video_id, output_path.with_suffix(".jpg"), "spritesheet")
    return SoraResult(video_id, output_path, thumb, sprite)


def _result_from_existing(
    video_id: str, output_path: Path, download_variants: bool
) -> SoraResult:
    """Build a result for an already-downloaded (cached) clip."""
    thumb = output_path.with_suffix(".webp") if download_variants else None
    sprite = output_path.with_suffix(".jpg") if download_variants else None
    return SoraResult(
        video_id,
        output_path,
        thumb if thumb and thumb.exists() else None,
        sprite if sprite and sprite.exists() else None,
    )


def _poll(client, video_id: str, spec: SoraSpec, *, on_progress=None):
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
                f"Sora job {video_id} timed out after {spec.timeout_seconds:.0f}s "
                f"(last status: {status}). The job may still finish — re-run to resume."
            )
        time.sleep(spec.poll_interval_seconds)


def _download(client, video_id: str, output_path: Path, *, variant: str) -> None:
    client.videos.download_content(video_id, variant=variant).write_to_file(str(output_path))


def _try_download(client, video_id, output_path: Path, variant: str) -> Path | None:
    """Download a non-essential variant (thumbnail/spritesheet); None on failure."""
    try:
        _download(client, video_id, output_path, variant=variant)
        return output_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s download failed (non-fatal): %s", variant, exc)
        return None


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────


def _fingerprint(*, prompt, image_path: Path | None, spec: SoraSpec, character_ids) -> dict:
    """Identify a generation request so an unrelated change invalidates the cache."""
    return {
        "model": spec.model,
        "size": spec.size,
        "seconds": spec.seconds,
        "prompt": prompt,
        "characters": sorted(character_ids or []),
        "image_sha": hashlib.sha256(image_path.read_bytes()).hexdigest()
        if image_path is not None
        else None,
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
    err = getattr(video, "error", None)
    if err is None:
        return "unknown error"
    message = getattr(err, "message", None)
    if message:
        return str(message)
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)
