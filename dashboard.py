#!/usr/bin/env python3
"""A small local web dashboard for the Sora image-to-video app.

Upload a seed image, type the prompt, toggle the Sora levers (model, size,
duration), hit Generate, watch live progress, and get the finished video
inline.

Design: this is a *thin GUI over the CLI*. It shells out to `pipeline.py`
(same machine, same venv) and streams its log, so the dashboard inherits the
pipeline's exact behavior — including the resume cache and moderation
handling — and can't drift from or regress the tested code path.

Run it:
    make dashboard          # → http://127.0.0.1:7860
    # or: uv run python dashboard.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import gradio as gr

from config import MODEL_SIZES, VALID_SECONDS


HERE = Path(__file__).resolve().parent
_PCT_RE = re.compile(r"\((\d+)%\)")
_DONE_RE = re.compile(r"Done! Output:\s*(.+)$")
_MAX_LOG_LINES = 200


def _sizes_for(model: str) -> list[str]:
    """Allowed Sora sizes for the chosen model (sora-2 is 720p-only)."""
    return list(MODEL_SIZES[model])


def _friendly_status(line: str) -> str | None:
    """Map a raw pipeline log line to a short human status, or None to ignore."""
    if "Preparing input image" in line:
        return "🖼️ Preparing image…"
    if "Creating Sora job" in line:
        return "🎬 Submitting to Sora…"
    if "in_progress" in line:
        m = _PCT_RE.search(line)
        return f"🎬 Generating… {m.group(1)}%" if m else "🎬 Generating…"
    if "completed (100%)" in line:
        return "⬇️ Downloading clip…"
    if "blocked by our moderation" in line:
        return (
            "🚫 Blocked by Sora moderation — reword to describe the subjects "
            "accurately (e.g. adult characters / stylised figures, not realistic "
            "minors)."
        )
    return None


def generate(image_path, prompt, model, size, seconds, clean):
    """Run the pipeline as a subprocess, streaming (status, log, video)."""
    # ---- upfront validation (cheap, before any spend) ----
    if not image_path:
        raise gr.Error("Add a seed image first.")
    if not (prompt or "").strip():
        raise gr.Error("Enter a prompt.")
    if size not in MODEL_SIZES[model]:
        raise gr.Error(
            f"{model} doesn't support {size}. Allowed: {', '.join(MODEL_SIZES[model])}"
        )

    cmd = [
        sys.executable, "pipeline.py", str(image_path), prompt,
        "--model", model, "--size", size, "--seconds", str(seconds),
    ]
    if clean:
        cmd.append("--clean")

    log: list[str] = []
    status = "⏳ Starting…"
    yield status, "", None

    proc = subprocess.Popen(
        cmd, cwd=str(HERE),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    final_path: str | None = None
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        log.append(line)
        new_status = _friendly_status(line)
        if new_status:
            status = new_status
        done = _DONE_RE.search(line)
        if done:
            final_path = done.group(1).strip()
        yield status, "\n".join(log[-_MAX_LOG_LINES:]), gr.update()

    proc.wait()
    tail = "\n".join(log[-_MAX_LOG_LINES:])
    if proc.returncode != 0 or not final_path or not Path(final_path).exists():
        last = next((ln for ln in reversed(log) if "failed" in ln.lower()), "")
        yield f"❌ Generation failed. {last}", tail, None
        return

    yield f"✅ Saved: {final_path}", tail, final_path


# ────────────────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="Sora · Image → Video") as demo:
    gr.Markdown(
        "# 🎬 Sora · Image → Video\n"
        "Turn an **image + prompt** into a short video with OpenAI Sora. "
        "Set the levers, hit **Generate**, watch it render."
    )
    with gr.Row():
        with gr.Column(scale=1):
            image = gr.Image(label="Seed image", type="filepath", height=300)
            prompt = gr.Textbox(
                label="Prompt",
                lines=8,
                placeholder=(
                    "Describe the motion and scene. Be specific about what should "
                    "(and shouldn't) move. Tip: for stylised art, say so explicitly "
                    "and 'avoid realistic humans' if faces could read as minors."
                ),
            )
            with gr.Row():
                model = gr.Radio(list(MODEL_SIZES), value="sora-2", label="Model")
                seconds = gr.Radio(list(VALID_SECONDS), value="8", label="Seconds")
            size = gr.Dropdown(
                _sizes_for("sora-2"), value="720x1280",
                label="Size (must be supported by the model)",
            )
            clean = gr.Checkbox(value=False, label="Force fresh (ignore cache)")
            btn = gr.Button("🎬 Generate video", variant="primary")
            gr.Markdown(
                "<sub>Sora is paid &amp; async — a clip takes a few minutes "
                "(longer for <code>sora-2-pro</code>). An identical re-run resumes "
                "the cached job instead of re-billing.</sub>"
            )
        with gr.Column(scale=1):
            status = gr.Markdown("Idle.")
            video = gr.Video(label="Result", height=420)
            with gr.Accordion("Log", open=False):
                log = gr.Textbox(label="", lines=14, max_lines=14)

    # sora-2 is 720p-only; sora-2-pro unlocks the larger sizes. Keep the size
    # dropdown in sync with the chosen model.
    model.change(
        lambda m: gr.update(choices=_sizes_for(m), value=_sizes_for(m)[0]),
        inputs=model, outputs=size,
    )
    btn.click(
        generate,
        inputs=[image, prompt, model, size, seconds, clean],
        outputs=[status, log, video],
    )


if __name__ == "__main__":
    demo.queue().launch(inbrowser=True, theme=gr.themes.Soft())
