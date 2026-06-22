"""FastAPI backend — the single HTTP surface for the Sora app.

Exposes the ``modules/*`` operations as a JSON/multipart API consumed by the Vue
SPA in ``frontend/``:

  * GET  /api/config            — models, sizes, seconds, upscale models + caps
  * GET  /api/outputs           — finished clips in output/ (newest first)
  * POST /api/generate          — text-/image-to-video (multipart, optional image)
  * POST /api/operate           — extend / remix / edit a clip by id (JSON)
  * POST /api/characters        — build a reusable character from a clip (multipart)
  * POST /api/upscale           — Real-ESRGAN super-resolution (multipart)
  * GET  /api/jobs/{id}         — job snapshot (polling fallback)
  * GET  /api/jobs/{id}/events  — live job progress over SSE

Long operations run on background threads (see ``server.jobs``); endpoints that
start one return ``{"job_id": ...}`` immediately and the client follows progress
on the SSE stream. Result mp4s/thumbnails are served read-only from ``output/``
and ``tmp/`` under ``/files``. In production the built SPA (``frontend/dist``) is
served at ``/`` so the whole app is one server on one port.

Run it:
    uvicorn server.main:app --port 8000            # serves API (+ built SPA)
    uvicorn server.main:app --reload --port 8000   # dev API; run Vite separately
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import (
    DEFAULT_UPSCALE,
    MODEL_SIZES,
    OUTPUT_DIR,
    PROJECT_ROOT,
    TMP_DIR,
    UPSCALE_MODELS,
    VALID_SECONDS,
    SoraSpec,
    VideoSpec,
)
from modules.image_prep import prepare_input_image
from modules.logging_setup import configure_logging
from modules.postprocess import CORNERS, ffmpeg_available, overlay_logo, strip_audio
from modules.sora_client import (
    create_character,
    edit_video,
    extend_video,
    generate_video,
    remix_video,
)
from modules.upscale_client import modal_configured, upscale_video
from modules.utils import ensure_dir, safe_slug
from server.jobs import JobManager
from server.schemas import OperateRequest


configure_logging()
load_dotenv()

# Uploaded seed images / clips land here — deliberately *outside* TMP_DIR so the
# Generate tab's "Force fresh" (which wipes tmp/) can't delete the upload it's
# about to use. Not served to the browser.
UPLOADS_DIR = PROJECT_ROOT / ".uploads"
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

app = FastAPI(title="Sora Studio")

# Permissive CORS: this is a single-user local tool. In dev the Vite server
# proxies /api anyway; this only matters if the SPA is served from another origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_dir(OUTPUT_DIR)
ensure_dir(TMP_DIR)
app.mount("/files/output", StaticFiles(directory=str(OUTPUT_DIR)), name="files-output")
app.mount("/files/tmp", StaticFiles(directory=str(TMP_DIR)), name="files-tmp")

jobs = JobManager()


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────


def _require_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            400, "OPENAI_API_KEY is not set. Add it to .env (cp .env.example .env)."
        )


def _char_ids(text: str) -> list[str]:
    return [c.strip() for c in (text or "").replace(",", " ").split() if c.strip()]


async def _save_upload(upload: UploadFile) -> Path:
    """Persist an uploaded file under .uploads/ and return its path."""
    ensure_dir(UPLOADS_DIR)
    suffix = Path(upload.filename or "").suffix or ".bin"
    dest = UPLOADS_DIR / f"upload_{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(await upload.read())
    return dest


def _url_for(path: Optional[Path]) -> Optional[str]:
    """Map a result Path under output/ or tmp/ to its /files URL."""
    if path is None:
        return None
    resolved = Path(path).resolve()
    for base, prefix in (
        (OUTPUT_DIR.resolve(), "/files/output"),
        (TMP_DIR.resolve(), "/files/tmp"),
    ):
        try:
            rel = resolved.relative_to(base)
        except ValueError:
            continue
        return f"{prefix}/{rel.as_posix()}"
    return None


# ────────────────────────────────────────────────────────────────────────────
# Metadata
# ────────────────────────────────────────────────────────────────────────────


@app.get("/api/config")
def get_config() -> dict:
    """Everything the frontend needs to build its controls — from config.py."""
    return {
        "models": {model: list(sizes) for model, sizes in MODEL_SIZES.items()},
        "valid_seconds": list(VALID_SECONDS),
        "upscale_models": [
            {"name": name, "desc": desc} for name, desc in UPSCALE_MODELS.items()
        ],
        "default_upscale_model": DEFAULT_UPSCALE.model,
        "upscale_scales": [2, 3, 4],
        "corners": list(CORNERS),
        "capabilities": {
            "ffmpeg": ffmpeg_available(),
            "modal": modal_configured(),
            "api_key": bool(os.getenv("OPENAI_API_KEY")),
        },
    }


@app.get("/api/outputs")
def list_outputs() -> list[dict]:
    """Finished clips in output/, newest first (for the Upscale tab picker)."""
    items = []
    for p in sorted(
        OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        items.append({"name": p.name, "url": _url_for(p), "mtime": p.stat().st_mtime})
    return items


# ────────────────────────────────────────────────────────────────────────────
# Operations — each starts a background job and returns its id
# ────────────────────────────────────────────────────────────────────────────


@app.post("/api/generate")
async def generate(
    prompt: str = Form(...),
    model: str = Form("sora-2"),
    size: str = Form("720x1280"),
    seconds: str = Form("8"),
    characters: str = Form(""),
    mute: bool = Form(False),
    clean: bool = Form(False),
    image: Optional[UploadFile] = File(None),
) -> dict:
    _require_key()
    if not prompt.strip():
        raise HTTPException(400, "Enter a prompt.")
    if model not in MODEL_SIZES:
        raise HTTPException(400, f"Unknown model {model!r}.")
    if size not in MODEL_SIZES[model]:
        raise HTTPException(
            400,
            f"{model} doesn't support {size}. Allowed: {', '.join(MODEL_SIZES[model])}",
        )
    if mute and not ffmpeg_available():
        raise HTTPException(
            400, "Mute needs ffmpeg on PATH (brew install ffmpeg). Uncheck Mute to skip."
        )

    image_path = await _save_upload(image) if image is not None else None
    spec = SoraSpec(model=model, size=size, seconds=seconds)

    def task(on_progress):
        if clean:
            shutil.rmtree(TMP_DIR, ignore_errors=True)
        ensure_dir(TMP_DIR)
        ensure_dir(OUTPUT_DIR)

        prepared = None
        if image_path is not None:
            prepared = prepare_input_image(
                image_path,
                output_path=TMP_DIR / "input_prepared.png",
                video=VideoSpec.from_size(size),
            )

        result = generate_video(
            prompt=prompt,
            image_path=prepared,
            output_path=TMP_DIR / "sora_raw.mp4",
            spec=spec,
            tmp_dir=TMP_DIR,
            character_ids=_char_ids(characters) or None,
            on_progress=on_progress,
        )

        final = OUTPUT_DIR / f"{safe_slug(prompt)}.mp4"
        if mute:
            strip_audio(result.video_path, final)
        else:
            shutil.copy2(result.video_path, final)

        return {
            "video_url": _url_for(final),
            "thumb_url": _url_for(result.thumbnail_path),
            "sprite_url": _url_for(result.spritesheet_path),
            "video_id": result.video_id,
            "message": f"Saved {final.name} · video id {result.video_id}"
            + (" · muted" if mute else ""),
        }

    job = jobs.create()
    jobs.run(job, task)
    return {"job_id": job.id}


@app.post("/api/operate")
def operate(req: OperateRequest) -> dict:
    _require_key()
    if req.op not in ("extend", "remix", "edit"):
        raise HTTPException(400, f"Unknown operation {req.op!r}.")
    if not req.source_id.strip():
        raise HTTPException(400, "Enter a source video id.")
    if not req.prompt.strip():
        raise HTTPException(400, "Enter a prompt.")

    source_id = req.source_id.strip()
    spec = SoraSpec()  # only the poll interval/timeout matter here

    def task(on_progress):
        ensure_dir(OUTPUT_DIR)
        out = (
            OUTPUT_DIR
            / f"{req.op}_{source_id[:14]}_{safe_slug(req.prompt, max_length=24)}.mp4"
        )
        if req.op == "extend":
            result = extend_video(
                video_id=source_id,
                prompt=req.prompt,
                seconds=req.seconds,
                output_path=out,
                spec=spec,
                on_progress=on_progress,
            )
        elif req.op == "remix":
            result = remix_video(
                video_id=source_id,
                prompt=req.prompt,
                output_path=out,
                spec=spec,
                on_progress=on_progress,
            )
        else:  # edit
            result = edit_video(
                video_id=source_id,
                prompt=req.prompt,
                output_path=out,
                spec=spec,
                on_progress=on_progress,
            )
        return {
            "video_url": _url_for(result.video_path),
            "video_id": result.video_id,
            "message": f"{req.op} → {out.name} · new video id {result.video_id}",
        }

    job = jobs.create()
    jobs.run(job, task)
    return {"job_id": job.id}


@app.post("/api/characters")
async def characters(
    name: str = Form(...),
    clip: UploadFile = File(...),
) -> dict:
    _require_key()
    if not name.strip():
        raise HTTPException(400, "Give the character a name.")

    clip_path = await _save_upload(clip)

    def task(on_progress):
        on_progress("Uploading clip & creating character…", 30)
        data = create_character(name=name.strip(), video_path=clip_path)
        cid = data.get("id", "?")
        return {
            "character_id": cid,
            "name": data.get("name"),
            "message": f"Character {data.get('name')} created · id {cid}",
        }

    job = jobs.create()
    jobs.run(job, task)
    return {"job_id": job.id}


@app.post("/api/upscale")
async def upscale(
    model: str = Form(...),
    scale: str = Form("2"),
    source_name: str = Form(""),
    upload: Optional[UploadFile] = File(None),
) -> dict:
    if upload is not None:
        src = await _save_upload(upload)
    elif source_name.strip():
        # Constrain to a file in output/ — never trust a client-supplied path.
        src = OUTPUT_DIR / Path(source_name).name
    else:
        raise HTTPException(400, "Pick a clip from output/ or upload a video.")

    if not src.exists():
        raise HTTPException(400, f"File not found: {src.name}.")
    if not modal_configured():
        raise HTTPException(
            400,
            "Modal isn't set up — run `uv run modal setup` once, then `make deploy-upscaler`.",
        )

    outscale = float(scale)

    def task(on_progress):
        ensure_dir(OUTPUT_DIR)
        dst = OUTPUT_DIR / f"{src.stem}_{outscale:g}x.mp4"
        upscale_video(src, dst, model=model, outscale=outscale, on_progress=on_progress)
        return {
            "video_url": _url_for(dst),
            "message": f"Upscaled {src.name} → {dst.name} · {model} · {outscale:g}x",
        }

    job = jobs.create()
    jobs.run(job, task)
    return {"job_id": job.id}


@app.post("/api/brand")
async def brand(
    logo: UploadFile = File(...),
    corner: str = Form("bottom-right"),
    opacity: float = Form(0.9),
    size: float = Form(0.18),
    source_name: str = Form(""),
    upload: Optional[UploadFile] = File(None),
) -> dict:
    if corner not in CORNERS:
        raise HTTPException(400, f"corner must be one of {', '.join(CORNERS)}.")
    if not ffmpeg_available():
        raise HTTPException(
            400, "Overlaying a logo needs ffmpeg on PATH (brew install ffmpeg)."
        )

    if upload is not None:
        src = await _save_upload(upload)
    elif source_name.strip():
        # Constrain to a file in output/ — never trust a client-supplied path.
        src = OUTPUT_DIR / Path(source_name).name
    else:
        raise HTTPException(400, "Pick a clip from output/ or upload a video.")
    if not src.exists():
        raise HTTPException(400, f"File not found: {src.name}.")

    logo_path = await _save_upload(logo)

    def task(on_progress):
        ensure_dir(OUTPUT_DIR)
        dst = OUTPUT_DIR / f"{src.stem}_branded.mp4"
        on_progress("Overlaying logo (ffmpeg)…", 20)
        overlay_logo(
            src, logo_path, dst,
            corner=corner, opacity=opacity, scale=size,
        )
        return {
            "video_url": _url_for(dst),
            "message": f"Branded {src.name} → {dst.name} · {corner}",
        }

    job = jobs.create()
    jobs.run(job, task)
    return {"job_id": job.id}


# ────────────────────────────────────────────────────────────────────────────
# Job status — snapshot + SSE stream
# ────────────────────────────────────────────────────────────────────────────


@app.get("/api/jobs/{job_id}")
def job_snapshot(job_id: str) -> dict:
    snap = jobs.snapshot(job_id)
    if snap is None:
        raise HTTPException(404, "Unknown job.")
    return snap


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    if jobs.get(job_id) is None:
        raise HTTPException(404, "Unknown job.")

    async def event_stream():
        last_version = -1
        while True:
            if await request.is_disconnected():
                break
            snap = jobs.snapshot(job_id)
            if snap is None:
                break
            if snap["version"] != last_version:
                last_version = snap["version"]
                yield f"data: {json.dumps(snap)}\n\n"
            if snap["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering for live progress
            "Connection": "keep-alive",
        },
    )


# ────────────────────────────────────────────────────────────────────────────
# SPA — serve the built Vue app at / in production (no-op during dev)
# ────────────────────────────────────────────────────────────────────────────

# Mounted last so it acts as the catch-all *after* the /api and /files routes.
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="spa")
