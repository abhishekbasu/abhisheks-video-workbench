.PHONY: help dashboard video dry-run
.DEFAULT_GOAL := help

# Usage:
#   make dashboard
#   make video IMAGE=path/to/img.png PROMPT="a slow push-in"
#   make video IMAGE=img.png PROMPT="..." MODEL=sora-2-pro SIZE=1024x1792 SECONDS=12
#   make dry-run IMAGE=img.png PROMPT="..."   # no API spend

MODEL   ?= sora-2
SIZE    ?= 720x1280
SECONDS ?= 8
ARGS    ?=

help:
	@echo "Targets:"
	@echo "  dashboard Launch the local web dashboard (image + prompt + levers)."
	@echo "  video     Generate a video from IMAGE + PROMPT via Sora."
	@echo "  dry-run   Prepare the image and print the request; no API call."
	@echo ""
	@echo "Variables (override on the command line):"
	@echo "  IMAGE=<path>     seed image (required for video/dry-run)"
	@echo "  PROMPT=<text>    motion/scene prompt (required for video/dry-run)"
	@echo "  MODEL=$(MODEL)    SIZE=$(SIZE)    SECONDS=$(SECONDS)"
	@echo "  ARGS=<extra>     e.g. ARGS=--clean"
	@echo ""
	@echo "Examples:"
	@echo "  make dashboard"
	@echo "  make video IMAGE=cat.png PROMPT=\"the cat looks up slowly as rain falls\""
	@echo "  make dry-run IMAGE=cat.png PROMPT=\"...\""

dashboard:
	uv run python dashboard.py

video:
	@test -n "$(IMAGE)"  || { echo "IMAGE is required (IMAGE=path/to/img.png)"; exit 1; }
	@test -n "$(PROMPT)" || { echo "PROMPT is required (PROMPT=\"...\")"; exit 1; }
	uv run python pipeline.py "$(IMAGE)" "$(PROMPT)" \
		--model $(MODEL) --size $(SIZE) --seconds $(SECONDS) $(ARGS)

dry-run:
	@test -n "$(IMAGE)"  || { echo "IMAGE is required (IMAGE=path/to/img.png)"; exit 1; }
	@test -n "$(PROMPT)" || { echo "PROMPT is required (PROMPT=\"...\")"; exit 1; }
	uv run python pipeline.py "$(IMAGE)" "$(PROMPT)" \
		--model $(MODEL) --size $(SIZE) --seconds $(SECONDS) --dry-run $(ARGS)
