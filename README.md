# sora-i2v

A standalone frontend for the OpenAI **Sora** Videos API. Turn a **prompt**
(with an optional **seed image**) into a short video, then **extend**, **remix**,
or **edit** it, and reuse **characters** across clips. Comes with a CLI and a
local web dashboard. No project-specific dependencies.

> [!WARNING]
> **API runway:** OpenAI has announced the Videos API and the `sora-2` /
> `sora-2-pro` models are **deprecated, shutting down 2026-09-24**. All Sora
> calls are isolated in `modules/sora_client.py`, so swapping to a successor
> API later is a single-file change.

## Quick start

```bash
uv sync                      # install deps (uses uv: https://docs.astral.sh/uv/)
cp .env.example .env         # add OPENAI_API_KEY (Sora-enabled account)

make dashboard               # → http://127.0.0.1:7860  (easiest)
# …or the CLI:
uv run python pipeline.py "a slow cinematic push-in, rain on the glass" --image photo.png
uv run python pipeline.py "a calico cat on a skateboard, neon city at night"   # text-to-video
```

## What the API exposes (and what it doesn't)

`videos.create` accepts exactly: **prompt, seed image, model, size, seconds**.
There is **no audio toggle, no seed, no fps, no quality, no variant-count** — so
those aren't offered (they don't exist). To get a silent clip, use `--mute` /
the Mute toggle, which strips the audio track in post with ffmpeg.

Beyond create, the app surfaces the other Videos-API operations:

| Capability | Where | Notes |
|---|---|---|
| **text-to-video** | Generate | omit the seed image |
| **image-to-video** | Generate | provide a seed image (cover-cropped to size) |
| **model / size / seconds** | Generate | `sora-2` is 720p-only; `sora-2-pro` adds 1024×1792 / 1792×1024 |
| **characters** | Characters → Generate | build a reusable subject from a clip, reference it by id |
| **mute** | Generate | post-process audio strip (needs ffmpeg) |
| **extend** | Extend/Remix/Edit | continue a finished clip by +4/8/12s |
| **remix** | Extend/Remix/Edit | a variation of a finished clip from a new prompt |
| **edit** | Extend/Remix/Edit | prompt-based edit of a finished clip |
| **outputs** | everywhere | downloads the mp4 + a `.webp` thumbnail + a `.jpg` spritesheet |

## Dashboard

```bash
make dashboard          # → http://127.0.0.1:7860
```

- **Generate** — seed image (optional), prompt, model/size/seconds, character ids,
  mute, force-fresh. Live progress; the result video, thumbnail, spritesheet, and
  the **video id** appear on the right (copy the id to extend/remix it).
- **Extend / Remix / Edit** — paste a source video id, pick the operation, prompt
  (and seconds for extend), run.
- **Characters** — upload a short clip + a name → get a reusable **character id**
  to drop into the Generate tab.

It calls the Sora operations in-process via `modules/sora_client.py`.

## CLI

```
uv run python pipeline.py "<prompt>" [options]

  --image PATH                                  optional seed image (omit → text-to-video)
  --model {sora-2, sora-2-pro}                  default: sora-2
  --size  {720x1280,1280x720,1024x1792,1792x1024}   default: 720x1280 (9:16)
  --seconds {4, 8, 12}                          default: 8
  --character CHAR_ID                           reference a character (repeatable, ≤2)
  --mute                                        strip audio from the result (needs ffmpeg)
  --dry-run                                     prep + print the request; no API call / no spend
  --clean                                       wipe tmp/ (forces a fresh generation)
  --verbose                                     DEBUG logs
```

`sora-2` only supports the 720p sizes; the larger sizes require `--model sora-2-pro`
(validated before calling the API). The CLI covers generate; extend/remix/edit/
characters live in the dashboard.

Makefile wrapper:

```bash
make video PROMPT="a calico cat on a skateboard, neon city"          # text-to-video
make video PROMPT="the cat looks up slowly" IMAGE=cat.png            # image-to-video
make video PROMPT="..." IMAGE=cat.png ARGS=--mute MODEL=sora-2-pro SIZE=1024x1792
```

## Prerequisites

- **Python 3.10+** via [uv](https://docs.astral.sh/uv/)
- An **`OPENAI_API_KEY`** whose account/project has **Sora / Videos API** access
- **ffmpeg** — *only* if you use `--mute` / the Mute toggle (`brew install ffmpeg`)

## Idempotency & cost control

Sora is paid and async, so re-runs are designed not to re-bill:

- The job id + a request fingerprint are saved to `tmp/sora_job.json` **before**
  polling. A crash mid-generation → re-running the same request **resumes** the
  job instead of paying again.
- A downloaded clip is reused only when the fingerprint (model, size, seconds,
  prompt, characters, **and the image's content hash**) is identical.
- `--dry-run` prints the request with **no API call**; `--clean` forces fresh.
- extend / remix / edit are explicit one-offs and are not cached.

## A note on moderation

Sora moderates inputs and outputs. The most common false-positive: a seed image
whose faces read as **young/child-like** combined with **realistic or romantic**
prompt language trips the minor-safety filter (`moderation_blocked`). Fix by
using a seed whose characters clearly read as adults, or by describing stylised
subjects accurately ("felt figurines / illustration, not realistic humans").

## Directory layout

```
sora-i2v/
├── pipeline.py            # CLI: prompt (+ optional image) → video
├── dashboard.py           # Gradio web dashboard (generate / extend·remix·edit / characters)
├── config.py             # SoraSpec / VideoSpec, model↔size table
├── modules/
│   ├── sora_client.py    # the only OpenAI surface: generate, remix, extend, edit, characters
│   ├── image_prep.py     # cover-crop the seed image to Sora's size
│   ├── postprocess.py    # optional ffmpeg mute (strip audio)
│   ├── logging_setup.py  # logging config
│   └── utils.py          # slug + dir helpers
├── tmp/                  # intermediates + job cache (gitignored)
├── output/               # final videos + thumbnails + spritesheets (gitignored)
├── Makefile
└── .env.example
```
