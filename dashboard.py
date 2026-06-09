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
# Visual system — theme + CSS
# ────────────────────────────────────────────────────────────────────────────

# A custom Gradio theme tuned for a cinematic, restrained dark UI.
# One accent (warm amber) carries focus; everything else stays neutral.
THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.amber,
    secondary_hue=gr.themes.colors.amber,
    neutral_hue=gr.themes.colors.stone,
    font=[
        gr.themes.GoogleFont("Hanken Grotesk"),
        "ui-sans-serif", "system-ui", "sans-serif",
    ],
    font_mono=[
        gr.themes.GoogleFont("JetBrains Mono"),
        "ui-monospace", "SFMono-Regular", "monospace",
    ],
    radius_size=gr.themes.sizes.radius_md,
    spacing_size=gr.themes.sizes.spacing_md,
    text_size=gr.themes.sizes.text_md,
).set(
    # ── canvas ───────────────────────────────────────────────────────────
    body_background_fill="#0D0D10",
    body_background_fill_dark="#0D0D10",
    body_text_color="#E8E8EC",
    body_text_color_dark="#E8E8EC",
    body_text_color_subdued="#8C8C94",
    body_text_color_subdued_dark="#8C8C94",
    body_text_size="14px",
    # ── surfaces ─────────────────────────────────────────────────────────
    background_fill_primary="#15151A",
    background_fill_primary_dark="#15151A",
    background_fill_secondary="#101015",
    background_fill_secondary_dark="#101015",
    # ── panels / blocks ──────────────────────────────────────────────────
    block_background_fill="#15151A",
    block_background_fill_dark="#15151A",
    block_label_background_fill="transparent",
    block_label_background_fill_dark="transparent",
    block_label_text_color="#9C9CA4",
    block_label_text_color_dark="#9C9CA4",
    block_label_text_size="11px",
    block_label_text_weight="500",
    block_title_text_color="#E8E8EC",
    block_title_text_color_dark="#E8E8EC",
    block_title_text_weight="500",
    block_border_color="#222228",
    block_border_color_dark="#222228",
    block_border_width="1px",
    block_radius="10px",
    block_shadow="none",
    block_label_padding="2px 0",
    # ── inputs ───────────────────────────────────────────────────────────
    input_background_fill="#1A1A20",
    input_background_fill_dark="#1A1A20",
    input_background_fill_focus="#1F1F26",
    input_background_fill_focus_dark="#1F1F26",
    input_border_color="#26262E",
    input_border_color_dark="#26262E",
    input_border_color_focus="#E8A33D",
    input_border_color_focus_dark="#E8A33D",
    input_placeholder_color="#5C5C64",
    input_placeholder_color_dark="#5C5C64",
    input_radius="8px",
    input_padding="10px 12px",
    input_text_size="14px",
    # ── buttons (large) ──────────────────────────────────────────────────
    button_large_radius="8px",
    button_large_padding="14px 22px",
    button_large_text_size="14px",
    button_large_text_weight="600",
    # primary — the warm amber CTA
    button_primary_background_fill="#E8A33D",
    button_primary_background_fill_dark="#E8A33D",
    button_primary_background_fill_hover="#F0B055",
    button_primary_background_fill_hover_dark="#F0B055",
    button_primary_text_color="#1A1208",
    button_primary_text_color_dark="#1A1208",
    button_primary_border_color="#C68820",
    button_primary_border_color_dark="#C68820",
    # secondary — quiet, neutral
    button_secondary_background_fill="#1F1F26",
    button_secondary_background_fill_dark="#1F1F26",
    button_secondary_background_fill_hover="#26262E",
    button_secondary_background_fill_hover_dark="#26262E",
    button_secondary_text_color="#E8E8EC",
    button_secondary_text_color_dark="#E8E8EC",
    button_secondary_border_color="#2A2A32",
    button_secondary_border_color_dark="#2A2A32",
    # ── accent / borders ─────────────────────────────────────────────────
    border_color_accent="#E8A33D",
    border_color_accent_dark="#E8A33D",
    border_color_primary="#222228",
    border_color_primary_dark="#222228",
    color_accent="#E8A33D",
    color_accent_soft="#241B0E",
    color_accent_soft_dark="#241B0E",
    # ── checkbox / radio ─────────────────────────────────────────────────
    checkbox_background_color="#1A1A20",
    checkbox_background_color_dark="#1A1A20",
    checkbox_background_color_selected="#E8A33D",
    checkbox_background_color_selected_dark="#E8A33D",
    checkbox_border_color="#33333C",
    checkbox_border_color_dark="#33333C",
    checkbox_border_color_focus="#E8A33D",
    checkbox_border_color_focus_dark="#E8A33D",
    checkbox_border_color_selected="#E8A33D",
    checkbox_border_color_selected_dark="#E8A33D",
    checkbox_label_text_color="#C5C5CC",
    checkbox_label_text_color_dark="#C5C5CC",
    checkbox_label_background_fill="transparent",
    checkbox_label_background_fill_dark="transparent",
    checkbox_label_background_fill_selected="#241B0E",
    checkbox_label_background_fill_selected_dark="#241B0E",
    checkbox_label_border_color="transparent",
    checkbox_label_border_color_dark="transparent",
    checkbox_label_border_color_selected="#5A4014",
    checkbox_label_border_color_selected_dark="#5A4014",
    radio_circle="#E8A33D",
    # ── panels behind tabs ───────────────────────────────────────────────
    panel_background_fill="transparent",
    panel_background_fill_dark="transparent",
    panel_border_color="transparent",
    panel_border_color_dark="transparent",
)


# Custom CSS for layout polish that the theme variables can't reach:
# the hero, the section eyebrows, the styled idle cards, and a couple of
# small refinements on tabs, inputs, and the primary button.
CSS = """
/* ── canvas & shell ───────────────────────────────────────────────── */
.gradio-container {
  max-width: 1180px;
  margin: 0 auto;
  padding: 56px 32px 96px;
}

/* ── hero ─────────────────────────────────────────────────────────── */
.so-hero {
  margin: 0 0 36px;
  padding: 0;
}
.so-hero .eyebrow {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 11px;
  font-weight: 500;
  color: #E8A33D;
  text-transform: uppercase;
  letter-spacing: 0.22em;
  margin: 0 0 18px;
}
.so-hero h1 {
  font-family: "Instrument Serif", "Times New Roman", serif;
  font-style: italic;
  font-weight: 400;
  font-size: 56px;
  line-height: 1.02;
  color: #EDEDF0;
  letter-spacing: -0.01em;
  margin: 0 0 16px;
}
.so-hero h1 .so-dash {
  color: #5C5C64;
  font-style: normal;
  margin: 0 10px;
  font-size: 0.78em;
}
.so-hero .tagline {
  font-size: 14.5px;
  line-height: 1.6;
  color: #9C9CA4;
  max-width: 640px;
  margin: 0;
}
.so-hero .tagline code,
.so-hero .tagline .mono {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: #1A1A20;
  border: 1px solid #26262E;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
  color: #E8E8EC;
}
.so-rule {
  height: 1px;
  background: linear-gradient(to right, #26262E 0%, transparent 65%);
  margin: 0 0 24px;
}

/* ── tabs ─────────────────────────────────────────────────────────── */
.tab-nav {
  border-bottom: 1px solid #222228;
  gap: 4px;
  padding: 0;
}
.tab-nav button {
  background: transparent;
  color: #8C8C94;
  font-weight: 500;
  font-size: 13px;
  padding: 14px 22px 13px;
  border-radius: 0;
  border: none;
  border-bottom: 1px solid transparent;
  margin: 0;
  transition: color 120ms ease, border-color 120ms ease;
}
.tab-nav button:hover {
  color: #E8E8EC;
}
.tab-nav button.selected {
  color: #EDEDF0;
  border-bottom-color: #E8A33D;
  background: transparent;
}

/* ── section eyebrows ────────────────────────────────────────────── */
.so-section {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 10.5px;
  font-weight: 500;
  color: #6E6E78;
  text-transform: uppercase;
  letter-spacing: 0.20em;
  margin: 26px 0 12px;
}
.so-section:first-of-type {
  margin-top: 6px;
}
.so-section .so-section-rule {
  height: 1px;
  background: #1F1F26;
  margin-top: 8px;
}

/* ── markdown bodies inside the dashboard ────────────────────────── */
.markdown,
.markdown p {
  color: #C5C5CC;
}
.markdown code {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: #1A1A20;
  border: 1px solid #26262E;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
  color: #EDEDF0;
}
.markdown strong { color: #EDEDF0; }

/* ── idle / empty-state cards ────────────────────────────────────── */
.so-idle {
  border: 1px solid #222228;
  border-radius: 10px;
  background:
    linear-gradient(180deg, rgba(232,163,61,0.04) 0%, rgba(232,163,61,0) 60%),
    #131318;
  padding: 22px 24px;
  color: #9C9CA4;
}
.so-idle .so-idle-eyebrow {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 10.5px;
  font-weight: 500;
  color: #E8A33D;
  letter-spacing: 0.20em;
  text-transform: uppercase;
  margin: 0 0 10px;
}
.so-idle .so-idle-title {
  font-family: "Instrument Serif", serif;
  font-style: italic;
  font-weight: 400;
  font-size: 22px;
  line-height: 1.25;
  color: #EDEDF0;
  margin: 0 0 8px;
}
.so-idle .so-idle-body {
  font-size: 13.5px;
  line-height: 1.6;
  color: #9C9CA4;
  margin: 0;
}
.so-idle .so-idle-body + .so-idle-body { margin-top: 8px; }
.so-idle .so-idle-note {
  font-size: 12px;
  line-height: 1.55;
  color: #6E6E78;
  margin: 12px 0 0;
  padding-top: 12px;
  border-top: 1px dashed #26262E;
}
.so-idle code {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: #1A1A20;
  border: 1px solid #2A2A32;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
  color: #EDEDF0;
}

/* ── refine block label typography ──────────────────────────────── */
.block .label,
.block label > span:first-child {
  letter-spacing: 0.04em;
  text-transform: none;
}

/* ── refine the primary button (Generate / Run / Create) ────────── */
button.primary {
  background: linear-gradient(180deg, #F0B355 0%, #E29A30 100%);
  border: 1px solid #C68820;
  color: #1A1208;
  font-weight: 600;
  letter-spacing: 0.005em;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.18) inset,
    0 1px 2px rgba(0, 0, 0, 0.45);
  transition: background 120ms ease, transform 80ms ease;
}
button.primary:hover {
  background: linear-gradient(180deg, #F5BD63 0%, #ECA53B 100%);
}
button.primary:active {
  transform: translateY(1px);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.10) inset,
    0 0 0 rgba(0, 0, 0, 0);
}

/* ── status messages: keep them quiet & elegant ─────────────────── */
.result-status .markdown {
  color: #C5C5CC;
  line-height: 1.55;
}

/* ── footer ─────────────────────────────────────────────────────── */
footer {
  color: #5C5C64;
  font-size: 12px;
}
footer a, footer button { color: #8C8C94; }

/* ── video / image rounding ─────────────────────────────────────── */
.video-container video,
.image-container img { border-radius: 8px; }

/* ── small: tighten dropdown chrome ─────────────────────────────── */
.wrap.svelte-1ipelgc { background: #1A1A20; }
"""


HERO_HTML = """
<div class="so-hero">
  <div class="eyebrow">OpenAI Videos API · Sora</div>
  <h1>Sora<span class="so-dash">—</span><span style="font-style:normal;font-size:0.62em;color:#9C9CA4;letter-spacing:0;">image &amp; prompt → video</span></h1>
  <p class="tagline">
    A focused frontend for generating, extending, remixing, and editing short Sora clips —
    with reusable characters across them. Sora is paid and async; a clip usually takes a
    few minutes (longer for <code>sora-2-pro</code>).
  </p>
</div>
<div class="so-rule"></div>
"""

IDLE_GENERATE_HTML = """
<div class="so-idle">
  <div class="so-idle-eyebrow">Result</div>
  <div class="so-idle-title">Your clip will appear here.</div>
  <p class="so-idle-body">
    Write a prompt — optionally seed it with an image — and press <strong>Generate</strong>.
    The finished clip, its thumbnail, spritesheet, and a <code>video id</code> for follow-up
    operations land in this column.
  </p>
  <p class="so-idle-note">
    Typical wait: 2–4 minutes for <code>sora-2</code>, longer for <code>sora-2-pro</code>.
    Re-runs of the same request resume the in-flight job instead of paying again.
  </p>
</div>
"""

IDLE_OP_HTML = """
<div class="so-idle">
  <div class="so-idle-eyebrow">Result</div>
  <div class="so-idle-title">Operate on an existing clip.</div>
  <p class="so-idle-body">
    Paste a <code>video id</code> from the Generate tab, choose <em>extend</em>, <em>remix</em>,
    or <em>edit</em>, and describe the change. The new clip lands here with its own id —
    chain operations as far as you like.
  </p>
</div>
"""

IDLE_CHAR_HTML = """
<div class="so-idle">
  <div class="so-idle-eyebrow">Reusable character</div>
  <div class="so-idle-title">Build a character once, reuse it everywhere.</div>
  <p class="so-idle-body">
    Upload a short clip of your subject and give them a name. You'll get a
    <code>character id</code> to drop into the Generate tab's <em>Character ids</em> field.
  </p>
  <p class="so-idle-note">
    Character support in the create API is newer and may be gated on your account —
    if it errors, the message will say so.
  </p>
</div>
"""


# ────────────────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Sora · Image → Video") as demo:
    gr.HTML(HERO_HTML)

    with gr.Tabs():
        # ---- Generate ----
        with gr.Tab("Generate"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1, min_width=420):
                    gr.HTML("<div class='so-section'>Source<div class='so-section-rule'></div></div>")
                    g_image = gr.Image(
                        label="Seed image — optional, leave empty for text-to-video",
                        type="filepath", height=220,
                    )
                    g_prompt = gr.Textbox(
                        label="Prompt",
                        lines=5,
                        placeholder="Describe the motion or scene. One clear action; subtle motion reads best.",
                        info="Plain English. Avoid moderation triggers — see README.",
                    )

                    gr.HTML("<div class='so-section'>Generation<div class='so-section-rule'></div></div>")
                    with gr.Row():
                        g_model = gr.Radio(list(MODEL_SIZES), value="sora-2", label="Model")
                        g_seconds = gr.Radio(list(VALID_SECONDS), value="8", label="Seconds")
                    g_size = gr.Dropdown(
                        _sizes_for("sora-2"), value="720x1280",
                        label="Size",
                        info="Must be supported by the chosen model — sora-2 is 720p-only.",
                    )

                    gr.HTML("<div class='so-section'>Advanced<div class='so-section-rule'></div></div>")
                    g_chars = gr.Textbox(
                        label="Character ids — optional",
                        placeholder="char_abc, char_def",
                        info="Comma-separated. Build characters in the Characters tab.",
                    )
                    with gr.Row():
                        g_mute = gr.Checkbox(
                            False, label="Mute output",
                            info="Strip audio — needs ffmpeg on PATH.",
                        )
                        g_clean = gr.Checkbox(
                            False, label="Force fresh",
                            info="Ignore the resume cache.",
                        )

                    g_btn = gr.Button("Generate", variant="primary", size="lg")

                with gr.Column(scale=1, min_width=420):
                    g_status = gr.Markdown(IDLE_GENERATE_HTML, elem_classes="result-status")
                    g_video = gr.Video(label="Result", height=380)
                    g_id = gr.Textbox(
                        label="Video id — paste into Extend / Remix / Edit",
                        interactive=False,
                    )
                    with gr.Row():
                        g_thumb = gr.Image(label="Thumbnail", height=150)
                        g_sprite = gr.Image(label="Spritesheet", height=150)

        # ---- Extend / Remix / Edit ----
        with gr.Tab("Extend / Remix / Edit"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1, min_width=420):
                    gr.HTML("<div class='so-section'>Operation<div class='so-section-rule'></div></div>")
                    o_op = gr.Radio(
                        ["extend", "remix", "edit"], value="extend", label="Mode",
                        info="extend = +seconds continuation · remix = variation · edit = prompt-edit",
                    )

                    gr.HTML("<div class='so-section'>Source<div class='so-section-rule'></div></div>")
                    o_src = gr.Textbox(label="Source video id", placeholder="video_…")
                    o_prompt = gr.Textbox(
                        label="Prompt", lines=5,
                        placeholder="What should change, continue, or be reinterpreted?",
                    )
                    o_seconds = gr.Radio(
                        list(VALID_SECONDS), value="8", label="Seconds — extend only",
                    )

                    o_btn = gr.Button("Run", variant="primary", size="lg")

                with gr.Column(scale=1, min_width=420):
                    o_status = gr.Markdown(IDLE_OP_HTML, elem_classes="result-status")
                    o_video = gr.Video(label="Result", height=380)
                    o_id = gr.Textbox(label="New video id", interactive=False)

        # ---- Characters ----
        with gr.Tab("Characters"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1, min_width=420):
                    gr.HTML("<div class='so-section'>Source clip<div class='so-section-rule'></div></div>")
                    c_clip = gr.File(
                        label="Short clip of the subject (mp4 / mov / webm)",
                        file_types=[".mp4", ".mov", ".webm"], type="filepath",
                    )
                    c_name = gr.Textbox(
                        label="Character name", placeholder="e.g. Alfie",
                        info="A short label — the API returns a character id you reference later.",
                    )
                    c_btn = gr.Button("Create character", variant="primary", size="lg")

                with gr.Column(scale=1, min_width=420):
                    c_status = gr.Markdown(IDLE_CHAR_HTML, elem_classes="result-status")
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
    demo.queue().launch(inbrowser=False, theme=THEME, css=CSS)
