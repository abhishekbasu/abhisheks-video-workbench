#!/usr/bin/env python3
"""Modal GPU upscaler — Real-ESRGAN video super-resolution as a deployed app.

Self-contained by design: this file is deployed to and runs on Modal, so it
must not import anything else from this repo. The local side
(``modules/upscale_client.py``) looks the deployed app up by name — keep
``APP_NAME``/``WEIGHTS`` in sync with ``UpscaleSpec``/``UPSCALE_MODELS`` in
``config.py``.

Deploy (one-time, and again after any edit to this file):
    uv run modal deploy modal_upscaler.py            # default GPU: L4
    UPSCALER_GPU=A10G uv run modal deploy modal_upscaler.py
    UPSCALER_GPU=L4,A10G uv run modal deploy modal_upscaler.py   # with fallback

Smoke test without the app frontend:
    uv run modal run modal_upscaler.py --input output/clip.mp4 --outscale 2

Per request: input mp4 bytes → decode frames with OpenCV → Real-ESRGAN per
frame (tiled, fp16) → pipe raw BGR frames into a single ffmpeg process that
re-encodes the video and stream-copies the original audio → mp4 bytes back.
The method is a generator so progress streams to the caller; payloads over
2 MiB (the result, typically) ride Modal's blob store automatically.

Assumes constant-frame-rate input (true for Sora clips); a variable-rate
source would be retimed to its nominal rate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import modal


APP_NAME = "sora-upscaler"
MODELS_DIR = "/models"
_PROGRESS_EVERY = 10  # frames between progress events

# GPU is fixed at deploy time. A comma-separated value becomes a fallback
# list (Modal tries each in order when capacity is tight).
GPU = [g.strip() for g in os.environ.get("UPSCALER_GPU", "L4").split(",") if g.strip()]

# Model name → (weight filename, official release URL). Names must match
# UPSCALE_MODELS in config.py (which this file can't import — see docstring).
WEIGHTS: dict[str, tuple[str, str]] = {
    "realesrgan-x4plus": (
        "RealESRGAN_x4plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    ),
    "realesr-general-x4v3": (
        "realesr-general-x4v3.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
    ),
    "realesr-animevideov3": (
        "realesr-animevideov3.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
    ),
}

app = modal.App(APP_NAME)


def _download_weights() -> None:
    """Image build step: bake the pretrained weights into the image (~75 MB)."""
    import urllib.request

    Path(MODELS_DIR).mkdir(exist_ok=True)
    for filename, url in WEIGHTS.values():
        urllib.request.urlretrieve(url, f"{MODELS_DIR}/{filename}")


# Pins are deliberate: basicsr 1.4.2 imports torchvision.transforms.functional_tensor
# (removed in torchvision 0.17) and breaks on numpy>=2, so torch 2.1.2 /
# torchvision 0.16.2 / numpy 1.26.4 is the known-good combo. basicsr and
# realesrgan install with --no-deps to skip their gfpgan→facexlib→numba chain
# (face enhance, unused here) and the GUI opencv build; their actual runtime
# deps are supplied explicitly, with opencv-python-headless.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libgl1", "libglib2.0-0")
    .pip_install("torch==2.1.2", "torchvision==0.16.2", "numpy==1.26.4")
    .pip_install(
        "opencv-python-headless==4.10.0.84",
        "addict",
        "future",
        "lmdb",
        "pyyaml",
        "requests",
        "scipy",
        "scikit-image",
        "tqdm",
        "yapf",
        "Pillow",
    )
    .pip_install("basicsr==1.4.2", "realesrgan==0.3.0", extra_options="--no-deps")
    .run_function(_download_weights)
)


def _probe(path: str) -> dict[str, Any]:
    """Return the exact fps fraction and best-effort frame count of ``path``.

    The fps comes back as ffprobe's verbatim fraction string (e.g. "30000/1001")
    so it can be handed straight to ffmpeg's ``-r`` — raw pipes carry no
    timestamps, and a rounded float rate would slowly drift against the
    stream-copied audio.
    """
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValueError(
            f"Could not read the input video (ffprobe exit {proc.returncode}): "
            f"{proc.stderr.strip()[:500]}"
        )
    info = json.loads(proc.stdout or "{}")
    video = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if video is None:
        raise ValueError("Input has no video stream")

    fps = video.get("r_frame_rate") or ""
    if not fps or fps.startswith("0"):
        fps = video.get("avg_frame_rate") or ""
    if not fps or fps.startswith("0"):
        raise ValueError("Could not determine the input frame rate")

    total: int | None = None
    if str(video.get("nb_frames", "")).isdigit():
        total = int(video["nb_frames"])
    else:
        try:
            num, _, den = fps.partition("/")
            duration = float(info.get("format", {}).get("duration", 0.0))
            if duration > 0:
                total = round(duration * float(num) / float(den or 1))
        except (TypeError, ValueError, ZeroDivisionError):
            total = None
    return {"fps": fps, "total": total}


def _tail(log_path: Path, limit: int = 2000) -> str:
    try:
        return log_path.read_text(errors="replace")[-limit:].strip()
    except OSError:
        return "(no ffmpeg log captured)"


@app.cls(image=image, gpu=GPU, cpu=4.0, memory=8192, timeout=3600, scaledown_window=300)
class Upscaler:
    """Per-container Real-ESRGAN runner — models load lazily and stay cached."""

    @modal.enter()
    def setup(self) -> None:
        self._upsamplers: dict[str, Any] = {}

    def _get_upsampler(self, model_name: str) -> Any:
        """Build (once per container) the RealESRGANer for ``model_name``."""
        if model_name in self._upsamplers:
            return self._upsamplers[model_name]

        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
        from realesrgan.archs.srvgg_arch import SRVGGNetCompact

        if model_name == "realesrgan-x4plus":
            arch = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23,
                num_grow_ch=32, scale=4,
            )
        elif model_name == "realesr-general-x4v3":
            arch = SRVGGNetCompact(
                num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32,
                upscale=4, act_type="prelu",
            )
        else:  # realesr-animevideov3
            arch = SRVGGNetCompact(
                num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=16,
                upscale=4, act_type="prelu",
            )

        filename, _ = WEIGHTS[model_name]
        # tile=512 keeps even the big RRDB model at ~4-6 GB VRAM on a 720x1280
        # frame — far inside L4's 24 GB, and flat regardless of input size.
        upsampler = RealESRGANer(
            scale=4,
            model_path=f"{MODELS_DIR}/{filename}",
            model=arch,
            tile=512,
            tile_pad=10,
            pre_pad=0,
            half=True,
        )
        self._upsamplers[model_name] = upsampler
        return upsampler

    def _enhance(self, upsampler: Any, frame: Any, outscale: float) -> Any:
        try:
            output, _ = upsampler.enhance(frame, outscale=outscale)
            return output
        except RuntimeError as exc:  # torch.cuda.OutOfMemoryError subclasses RuntimeError
            if "out of memory" in str(exc).lower():
                raise RuntimeError(
                    "GPU ran out of memory — try the lighter realesr-general-x4v3 "
                    "model or a lower scale"
                ) from exc
            raise

    @modal.method()
    def upscale(self, data: bytes, model_name: str, outscale: float) -> Iterator[dict]:
        """Upscale an mp4, streaming progress.

        Yields ``{"kind": "start", "total", "fps", "width", "height"}`` once,
        ``{"kind": "progress", "done", "total"}`` every few frames, and finally
        ``{"kind": "result", "data": <mp4 bytes>, "frames", "width", "height"}``.
        Raises only builtins (ValueError for bad input, RuntimeError for
        GPU/encoder failures) so errors deserialize cleanly on the client.
        """
        import cv2
        import numpy as np

        if model_name not in WEIGHTS:
            raise ValueError(
                f"Unknown model {model_name!r} — choose from: {', '.join(WEIGHTS)}"
            )
        outscale = float(outscale)
        if not 1.0 < outscale <= 4.0:
            raise ValueError(f"outscale must be in (1.0, 4.0], got {outscale:g}")

        workdir = Path(tempfile.mkdtemp(prefix="upscale-"))
        cap = None
        proc = None
        try:
            src = workdir / "in.mp4"
            src.write_bytes(data)
            probed = _probe(str(src))
            fps: str = probed["fps"]
            total: int | None = probed["total"]

            cap = cv2.VideoCapture(str(src))
            if not cap.isOpened():
                raise ValueError("Could not decode the input video (corrupt or unsupported format)")
            if total is None:
                cv2_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                total = cv2_total if cv2_total > 0 else None
            ok, frame = cap.read()
            if not ok or frame is None:
                raise ValueError("Input video has no decodable frames")

            upsampler = self._get_upsampler(model_name)
            out = self._enhance(upsampler, frame, outscale)
            # libx264 + yuv420p need even dimensions; crop at most 1px.
            out_h = out.shape[0] - out.shape[0] % 2
            out_w = out.shape[1] - out.shape[1] % 2

            yield {"kind": "start", "total": total, "fps": fps, "width": out_w, "height": out_h}

            dst = workdir / "out.mp4"
            log_path = workdir / "ffmpeg.log"
            # Single pass: encode the piped frames, stream-copy audio from the
            # original (second input). `-map 1:a?` makes audio optional so a
            # muted source still works.
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", f"{out_w}x{out_h}", "-r", fps, "-i", "pipe:0",
                "-i", str(src),
                "-map", "0:v:0", "-map", "1:a?",
                "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(dst),
            ]
            # stderr to a file, not PIPE — an unread pipe would deadlock ffmpeg.
            with open(log_path, "wb") as log:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log
                )

            done = 0
            while True:
                try:
                    proc.stdin.write(np.ascontiguousarray(out[:out_h, :out_w]).tobytes())
                except BrokenPipeError as exc:
                    proc.wait()
                    raise RuntimeError(f"ffmpeg died mid-encode: {_tail(log_path)}") from exc
                done += 1
                if done % _PROGRESS_EVERY == 0:
                    yield {"kind": "progress", "done": done, "total": total}
                ok, frame = cap.read()
                if not ok:
                    break
                out = self._enhance(upsampler, frame, outscale)

            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError(
                    f"ffmpeg encode failed (exit {proc.returncode}): {_tail(log_path)}"
                )
            yield {
                "kind": "result",
                "data": dst.read_bytes(),
                "frames": done,
                "width": out_w,
                "height": out_h,
            }
        finally:
            if cap is not None:
                cap.release()
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
            shutil.rmtree(workdir, ignore_errors=True)


@app.local_entrypoint()
def main(
    input: str,
    outscale: float = 2.0,
    model: str = "realesr-general-x4v3",
    output: str = "tmp/upscale_smoke.mp4",
) -> None:
    """Smoke test: run one clip through the container, bypassing the app UI."""
    src = Path(input)
    data = src.read_bytes()
    dst = Path(output)
    dst.parent.mkdir(parents=True, exist_ok=True)

    print(f"Upscaling {src.name} ({len(data) / 1e6:.1f} MB) with {model} at {outscale:g}x …")
    for event in Upscaler().upscale.remote_gen(data, model, outscale):
        if event["kind"] == "start":
            print(
                f"  {event['total'] or '?'} frames @ {event['fps']} fps "
                f"→ {event['width']}x{event['height']}"
            )
        elif event["kind"] == "progress":
            print(f"  frame {event['done']}/{event['total'] or '?'}")
        elif event["kind"] == "result":
            dst.write_bytes(event["data"])
            print(
                f"Done → {dst} ({event['frames']} frames, "
                f"{event['width']}x{event['height']}, {len(event['data']) / 1e6:.1f} MB)"
            )
            print(
                "Verify: ffprobe -v error -show_entries "
                f"stream=codec_type,width,height,r_frame_rate '{dst}'"
            )
