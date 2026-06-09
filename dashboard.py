#!/usr/bin/env python3
"""Local web dashboard — a frontend for the OpenAI Sora Videos API.

Three tabs:
  * Generate            — text- or image-to-video, with every create-time
                          dial (model, size, seconds), optional reusable
                          characters, and an optional mute (strip audio).
  * Extend / Remix / Edit — operate on any finished clip by its video id.
  * Characters          — build a reusable character from an uploaded clip.

Runs the Sora operations in-process via ``modules/sora_client`` (the single
OpenAI surface), with a live progress bar driven by the poll callback. The
Generate tab keeps the same request-fingerprint resume cache as the CLI.

Run it:
    make dashboard          # → http://127.0.0.1:7860
    # or: uv run python dashboard.py
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from config import MODEL_SIZES, OUTPUT_DIR, TMP_DIR, VALID_SECONDS, SoraSpec, VideoSpec
from modules.image_prep import prepare_input_image
from modules.logging_setup import configure_logging
from modules.postprocess import ffmpeg_available, strip_audio
from modules.sora_client import (
    create_character,
    edit_video,
    extend_video,
    generate_video,
    remix_video,
)
from modules.utils import ensure_dir, safe_slug


configure_logging()
load_dotenv()


def _sizes_for(model: str) -> list[str]:
    """Allowed Sora sizes for the chosen model (sora-2 is 720p-only)."""
    return list(MODEL_SIZES[model])


def _require_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise gr.Error("OPENAI_API_KEY is not set. Add it to .env (cp .env.example .env).")


def _progress_cb(progress):
    """Build an on_progress(status, pct) that drives the Gradio progress bar."""
    def cb(status, pct):
        frac = min((pct or 0) / 100.0, 0.99)
        progress(frac, desc=f"Sora: {status}" + (f" {pct}%" if pct is not None else ""))
    return cb


def _char_ids(text: str) -> list[str]:
    return [c.strip() for c in (text or "").replace(",", " ").split() if c.strip()]


# ────────────────────────────────────────────────────────────────────────────
# Handlers
# ────────────────────────────────────────────────────────────────────────────


def do_generate(image, prompt, model, size, seconds, characters, mute, clean, progress=gr.Progress()):
    if not (prompt or "").strip():
        raise gr.Error("Enter a prompt.")
    if size not in MODEL_SIZES[model]:
        raise gr.Error(f"{model} doesn't support {size}. Allowed: {', '.join(MODEL_SIZES[model])}")
    if mute and not ffmpeg_available():
        raise gr.Error("Mute needs ffmpeg on PATH (brew install ffmpeg). Uncheck Mute to skip.")
    _require_key()

    spec = SoraSpec(model=model, size=size, seconds=seconds)
    if clean:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    ensure_dir(TMP_DIR)
    ensure_dir(OUTPUT_DIR)

    progress(0.0, desc="Preparing…")
    prepared = None
    if image:
        prepared = prepare_input_image(
            Path(image), output_path=TMP_DIR / "input_prepared.png",
            video=VideoSpec.from_size(size),
        )

    try:
        result = generate_video(
            prompt=prompt, image_path=prepared,
            output_path=TMP_DIR / "sora_raw.mp4", spec=spec, tmp_dir=TMP_DIR,
            character_ids=_char_ids(characters) or None,
            on_progress=_progress_cb(progress),
        )
    except Exception as exc:  # noqa: BLE001 — surface SoraError/moderation cleanly
        raise gr.Error(str(exc))

    progress(0.99, desc="Finalizing…")
    final = OUTPUT_DIR / f"{safe_slug(prompt)}.mp4"
    if mute:
        strip_audio(result.video_path, final)
    else:
        shutil.copy2(result.video_path, final)

    thumb = str(result.thumbnail_path) if result.thumbnail_path else None
    sprite = str(result.spritesheet_path) if result.spritesheet_path else None
    status = f"✅ Saved `{final.name}` · video id `{result.video_id}`" + (
        " · 🔇 muted" if mute else ""
    )
    return str(final), thumb, sprite, status, result.video_id


def do_op(op, source_id, prompt, seconds, progress=gr.Progress()):
    if not (source_id or "").strip():
        raise gr.Error("Enter a source video id (from the Generate tab's 'Video id').")
    if not (prompt or "").strip():
        raise gr.Error("Enter a prompt.")
    _require_key()

    source_id = source_id.strip()
    spec = SoraSpec()  # only the poll interval/timeout are used here
    ensure_dir(OUTPUT_DIR)
    out = OUTPUT_DIR / f"{op}_{source_id[:14]}_{safe_slug(prompt, max_length=24)}.mp4"
    cb = _progress_cb(progress)

    try:
        if op == "extend":
            result = extend_video(
                video_id=source_id, prompt=prompt, seconds=seconds,
                output_path=out, spec=spec, on_progress=cb,
            )
        elif op == "remix":
            result = remix_video(
                video_id=source_id, prompt=prompt, output_path=out, spec=spec, on_progress=cb
            )
        else:  # edit
            result = edit_video(
                video_id=source_id, prompt=prompt, output_path=out, spec=spec, on_progress=cb
            )
    except Exception as exc:  # noqa: BLE001
        raise gr.Error(str(exc))

    status = f"✅ {op} → `{out.name}` · new video id `{result.video_id}`"
    return str(result.video_path), status, result.video_id


def do_create_character(clip, name, progress=gr.Progress()):
    if not clip:
        raise gr.Error("Upload a short clip (mp4) of the subject to build the character from.")
    if not (name or "").strip():
        raise gr.Error("Give the character a name.")
    _require_key()

    progress(0.3, desc="Uploading clip & creating character…")
    try:
        data = create_character(name=name.strip(), video_path=Path(clip))
    except Exception as exc:  # noqa: BLE001
        raise gr.Error(str(exc))

    cid = data.get("id", "?")
    msg = (
        f"✅ Character **{data.get('name')}** created.\n\n"
        f"Use this id in the **Generate** tab's *Character ids* field:\n\n`{cid}`"
    )
    return msg, cid


# ────────────────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Sora · Image → Video") as demo:
    gr.Markdown(
        "# 🎬 Sora · Image → Video\n"
        "A frontend for the OpenAI **Sora** Videos API — generate (text- or "
        "image-to-video), extend, remix, edit, and reuse characters. "
        "Sora is paid & async; a clip takes a few minutes (longer for "
        "`sora-2-pro`)."
    )

    with gr.Tabs():
        # ---- Generate ----
        with gr.Tab("Generate"):
            with gr.Row():
                with gr.Column(scale=1):
                    g_image = gr.Image(
                        label="Seed image (optional — leave empty for text-to-video)",
                        type="filepath", height=240,
                    )
                    g_prompt = gr.Textbox(
                        label="Prompt", lines=6,
                        placeholder="Describe the motion/scene. One clear action; subtle motion.",
                    )
                    with gr.Row():
                        g_model = gr.Radio(list(MODEL_SIZES), value="sora-2", label="Model")
                        g_seconds = gr.Radio(list(VALID_SECONDS), value="8", label="Seconds")
                    g_size = gr.Dropdown(
                        _sizes_for("sora-2"), value="720x1280",
                        label="Size (must be supported by the model)",
                    )
                    g_chars = gr.Textbox(
                        label="Character ids (optional, comma-separated)",
                        placeholder="char_abc, char_def  — created in the Characters tab",
                    )
                    with gr.Row():
                        g_mute = gr.Checkbox(False, label="Mute (strip audio — needs ffmpeg)")
                        g_clean = gr.Checkbox(False, label="Force fresh (ignore cache)")
                    g_btn = gr.Button("🎬 Generate", variant="primary")
                with gr.Column(scale=1):
                    g_status = gr.Markdown("Idle.")
                    g_video = gr.Video(label="Result", height=360)
                    g_id = gr.Textbox(
                        label="Video id (paste into Extend / Remix / Edit)", interactive=False
                    )
                    with gr.Row():
                        g_thumb = gr.Image(label="Thumbnail", height=150)
                        g_sprite = gr.Image(label="Spritesheet", height=150)

        # ---- Extend / Remix / Edit ----
        with gr.Tab("Extend / Remix / Edit"):
            with gr.Row():
                with gr.Column(scale=1):
                    o_op = gr.Radio(
                        ["extend", "remix", "edit"], value="extend", label="Operation",
                        info="extend = +seconds continuation · remix = variation · edit = prompt-edit",
                    )
                    o_src = gr.Textbox(label="Source video id", placeholder="video_…")
                    o_prompt = gr.Textbox(label="Prompt", lines=5)
                    o_seconds = gr.Radio(
                        list(VALID_SECONDS), value="8", label="Seconds (extend only)"
                    )
                    o_btn = gr.Button("Run", variant="primary")
                with gr.Column(scale=1):
                    o_status = gr.Markdown("Idle.")
                    o_video = gr.Video(label="Result", height=360)
                    o_id = gr.Textbox(label="New video id", interactive=False)

        # ---- Characters ----
        with gr.Tab("Characters"):
            with gr.Row():
                with gr.Column(scale=1):
                    c_clip = gr.File(
                        label="Clip to build the character from (mp4/mov/webm)",
                        file_types=[".mp4", ".mov", ".webm"], type="filepath",
                    )
                    c_name = gr.Textbox(label="Character name", placeholder="e.g. Alfie")
                    c_btn = gr.Button("Create character", variant="primary")
                with gr.Column(scale=1):
                    c_status = gr.Markdown(
                        "Upload a short clip of the subject; you'll get a reusable "
                        "character id to reference in the Generate tab.\n\n"
                        "<sub>Note: character support in the create API is newer and may "
                        "be gated on your account — if it errors, the message will say so.</sub>"
                    )
                    c_id = gr.Textbox(label="Character id", interactive=False)

    # ---- wiring ----
    g_model.change(
        lambda m: gr.update(choices=_sizes_for(m), value=_sizes_for(m)[0]),
        inputs=g_model, outputs=g_size,
    )
    g_btn.click(
        do_generate,
        inputs=[g_image, g_prompt, g_model, g_size, g_seconds, g_chars, g_mute, g_clean],
        outputs=[g_video, g_thumb, g_sprite, g_status, g_id],
    )
    o_btn.click(
        do_op, inputs=[o_op, o_src, o_prompt, o_seconds], outputs=[o_video, o_status, o_id]
    )
    c_btn.click(do_create_character, inputs=[c_clip, c_name], outputs=[c_status, c_id])


if __name__ == "__main__":
    demo.queue().launch(inbrowser=True, theme=gr.themes.Soft())
