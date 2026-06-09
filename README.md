# sora-i2v

A small, standalone app that turns **an image + a prompt** into a short
**video** with OpenAI **Sora** (image-to-video). Comes with a CLI and a local
web dashboard. No external services beyond the OpenAI API — no ffmpeg, no
branding, nothing project-specific.

> [!WARNING]
> **API runway:** OpenAI has announced the Videos API and the `sora-2` /
> `sora-2-pro` models are **deprecated, shutting down 2026-09-24**. All Sora
> calls are isolated in `modules/sora_client.py`, so swapping to a successor
> API later is a single-file change. Verify the model is still available before
> a run.

## Quick start

```bash
# Install dependencies (uses uv: https://docs.astral.sh/uv/)
uv sync

# Configure your key
cp .env.example .env        # then edit .env and add OPENAI_API_KEY

# Dashboard (easiest)
make dashboard              # → http://127.0.0.1:7860

# …or the CLI
uv run python pipeline.py path/to/image.png "a slow cinematic push-in, rain on the glass"
# → output/a_slow_cinematic_push_in_rain_on_the_glass.mp4
```

## Prerequisites

- **Python 3.10+** via [uv](https://docs.astral.sh/uv/)
- An **`OPENAI_API_KEY`** whose account/project has **Sora / Videos API** access

## Dashboard

```bash
make dashboard          # → http://127.0.0.1:7860
# or: uv run python dashboard.py
```

Upload a seed image, type the prompt, toggle the levers (model, size, duration,
force-fresh), hit **Generate**, and watch live progress — the finished video
appears inline. It's a thin GUI over `pipeline.py` (runs it as a subprocess and
streams its log), so it behaves exactly like the CLI, including the resume
cache. The size options auto-filter to whatever the chosen model supports.

## CLI

```
uv run python pipeline.py <image_path> "<prompt>" [options]

  --model {sora-2, sora-2-pro}                         default: sora-2
  --size  {720x1280, 1280x720, 1024x1792, 1792x1024}   default: 720x1280 (9:16)
  --seconds {4, 8, 12}                                 default: 8
  --dry-run      Prepare the image and print the request; no API call / no spend
  --clean        Wipe tmp/ before starting (forces a fresh generation)
  --verbose      DEBUG logs
```

`sora-2` only supports the 720p sizes (`720x1280`, `1280x720`). The larger sizes
(`1024x1792`, `1792x1024`) require `--model sora-2-pro`; the app validates this
before calling the API.

There's also a Makefile wrapper:

```bash
make video IMAGE=cat.png PROMPT="the cat looks up as rain streaks the window"
make dry-run IMAGE=cat.png PROMPT="..."
make video IMAGE=cat.png PROMPT="..." MODEL=sora-2-pro SIZE=1024x1792 SECONDS=12
```

## How it works

```
image + prompt
    │
    ▼
 1. Image prep      Pillow cover-crops the image to Sora's exact size
 2. Sora generate   Videos API: create job → poll → download MP4 (with audio)
    │
    ▼
 output/<prompt-slug>.mp4
```

The seed image must match the video resolution exactly (a Sora requirement), so
stage 1 cover-crops it. Sora returns the clip **with synchronized audio**.

## Idempotency & cost control

Sora is paid and async, so re-runs are designed not to re-bill:

- The created job's id + a request fingerprint are saved to `tmp/sora_job.json`
  **before** polling. If the process dies mid-generation, re-running the same
  command **resumes** that job (via `retrieve`) instead of paying again.
- A downloaded clip is reused only when the request fingerprint (model, size,
  seconds, prompt, **and the image's content hash**) is identical — change any
  of them and it regenerates.
- `--dry-run` prepares the image and prints the request with **no API call**.
- `--clean` wipes `tmp/` to force everything fresh.

## A note on moderation

Sora moderates inputs and outputs. The most common false-positive: a seed image
whose faces read as **young/child-like** combined with **realistic or romantic**
prompt language trips the minor-safety filter. If you hit
`moderation_blocked`, either use a seed whose characters clearly read as adults,
or describe stylised subjects accurately (e.g. "felt figurines / illustration,
not realistic humans"). This isn't about evading safety — it's about matching
the prompt to what's actually in the frame.

## Directory layout

```
sora-i2v/
├── pipeline.py            # entry point + 2-stage orchestration
├── dashboard.py           # local Gradio web dashboard
├── config.py             # SoraSpec / VideoSpec (frozen dataclasses), model/size table
├── modules/
│   ├── image_prep.py     # cover-crop the seed image to Sora's size
│   ├── sora_client.py    # the only OpenAI/Sora surface (create → poll → download)
│   ├── logging_setup.py  # logging config
│   └── utils.py          # slug + dir helpers
├── tmp/                  # intermediates + job cache (gitignored)
├── output/               # final videos (gitignored)
├── Makefile
└── .env.example
```
