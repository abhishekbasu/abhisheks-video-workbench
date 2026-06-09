.PHONY: help dashboard video dry-run
.DEFAULT_GOAL := help

# Usage:
#   make dashboard
#   make video PROMPT="a calico cat on a skateboard, neon city"          # text-to-video
#   make video PROMPT="a slow push-in" IMAGE=path/to/img.png             # image-to-video
#   make video PROMPT="..." IMAGE=img.png MODEL=sora-2-pro SIZE=1024x1792 SECONDS=12
#   make video PROMPT="..." IMAGE=img.png ARGS=--mute                    # strip audio
#   make dry-run PROMPT="..." IMAGE=img.png                              # no API spend
#
# For extend / remix / edit / character creation, use the dashboard.

MODEL   ?= sora-2
SIZE    ?= 720x1280
SECONDS ?= 8
ARGS    ?=

help:
	@echo "Targets:"
	@echo "  dashboard Launch the web dashboard (generate, extend, remix, characters)."
	@echo "  video     Generate a video from PROMPT (+ optional IMAGE) via Sora."
	@echo "  dry-run   Prepare and print the request; no API call."
	@echo ""
	@echo "Variables (override on the command line):"
	@echo "  PROMPT=<text>    motion/scene prompt (required for video/dry-run)"
	@echo "  IMAGE=<path>     optional seed image (omit for text-to-video)"
	@echo "  MODEL=$(MODEL)    SIZE=$(SIZE)    SECONDS=$(SECONDS)"
	@echo "  ARGS=<extra>     e.g. ARGS=--mute, ARGS=--clean, ARGS='--character char_abc'"
	@echo ""
	@echo "Examples:"
	@echo "  make dashboard"
	@echo "  make video PROMPT=\"a calico cat on a skateboard, neon city at night\""
	@echo "  make video PROMPT=\"the cat looks up slowly\" IMAGE=cat.png"

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
