"""Request bodies for the JSON endpoints.

The multipart endpoints (generate, characters, upscale) take their fields via
FastAPI ``Form``/``File`` params instead — only the pure-JSON operations need a
model here.
"""

from __future__ import annotations

from pydantic import BaseModel


class OperateRequest(BaseModel):
    """Extend / remix / edit a finished clip by id."""

    op: str  # "extend" | "remix" | "edit"
    source_id: str
    prompt: str
    seconds: str = "8"  # extend only; ignored by remix/edit
