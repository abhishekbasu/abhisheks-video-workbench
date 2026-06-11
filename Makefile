.PHONY: help dashboard video dry-run deploy-upscaler upscale
.DEFAULT_GOAL := help

# Usage:
#   make dashboard
#   make video PROMPT="a calico cat on a skateboard, neon city"          # text-to-video
#   make video PROMPT="a slow push-in" IMAGE=path/to/img.png             # image-to-video
#   make video PROMPT="..." IMAGE=img.png MODEL=sora-2-pro SIZE=1024x1792 SECONDS=12
#   make video PROMPT="..." IMAGE=img.png ARGS=--mute                    # strip audio
#   make dry-run PROMPT="..." IMAGE=img.png                              # no API spend
#   make deploy-upscaler                                                 # one-time Modal GPU deploy
#   make upscale INPUT=output/clip.mp4                                   # → output/clip_2x.mp4
#   make upscale INPUT=output/clip.mp4 SCALE=4 UPSCALE_MODEL=realesrgan-x4plus
#
# For extend / remix / edit / character creation, use the dashboard.

MODEL         ?= sora-2
SIZE          ?= 720x1280
SECONDS       ?= 8
SCALE         ?= 2
UPSCALE_MODEL ?= realesr-general-x4v3
ARGS          ?=

help:
	@echo "Targets:"
	@echo "  dashboard        Launch the web dashboard (generate, extend, remix, characters, upscale)."
	@echo "  video            Generate a video from PROMPT (+ optional IMAGE) via Sora."
	@echo "  dry-run          Prepare and print the request; no API call."
	@echo "  deploy-upscaler  Deploy the Real-ESRGAN GPU app to Modal (one-time, and after edits)."
	@echo "  upscale          Upscale INPUT on Modal → output/<stem>_<scale>x.mp4."
	@echo ""
	@echo "Variables (override on the command line):"
	@echo "  PROMPT=<text>    motion/scene prompt (required for video/dry-run)"
	@echo "  IMAGE=<path>     optional seed image (omit for text-to-video)"
	@echo "  MODEL=$(MODEL)    SIZE=$(SIZE)    SECONDS=$(SECONDS)"
	@echo "  INPUT=<path>     clip to upscale (required for upscale)"
	@echo "  SCALE=$(SCALE)    UPSCALE_MODEL=$(UPSCALE_MODEL)"
	@echo "  ARGS=<extra>     e.g. ARGS=--mute, ARGS=--clean, ARGS='--character char_abc'"
	@echo ""
	@echo "Examples:"
	@echo "  make dashboard"
	@echo "  make video PROMPT=\"a calico cat on a skateboard, neon city at night\""
	@echo "  make video PROMPT=\"the cat looks up slowly\" IMAGE=cat.png"
	@echo "  make upscale INPUT=output/clip.mp4 SCALE=4"
	@echo "  UPSCALER_GPU=A10G make deploy-upscaler   # pick the GPU at deploy time"

dashboard:
	uv run python dashboard.py

video:
	@test -n "$(PROMPT)" || { echo "PROMPT is required (PROMPT=\"...\")"; exit 1; }
	uv run python pipeline.py "$(PROMPT)" $(if $(IMAGE),--image "$(IMAGE)") \
		--model $(MODEL) --size $(SIZE) --seconds $(SECONDS) $(ARGS)

dry-run:
	@test -n "$(PROMPT)" || { echo "PROMPT is required (PROMPT=\"...\")"; exit 1; }
	uv run python pipeline.py "$(PROMPT)" $(if $(IMAGE),--image "$(IMAGE)") \
		--model $(MODEL) --size $(SIZE) --seconds $(SECONDS) --dry-run $(ARGS)

deploy-upscaler:
	uv run modal deploy modal_upscaler.py

upscale:
	@test -n "$(INPUT)" || { echo "INPUT is required (INPUT=output/clip.mp4)"; exit 1; }
	uv run python upscale.py --input "$(INPUT)" --scale $(SCALE) --model $(UPSCALE_MODEL) $(ARGS)
