"""HTTP layer for the Sora app — a FastAPI backend for the Vue frontend.

This package is the web layer for the Vue SPA: it exposes the operations in
``modules/*`` over a small JSON/multipart API, runs the long, blocking, async
Sora/upscale jobs on background threads, and streams their progress to the
browser over Server-Sent Events. All real logic still lives in ``modules/*`` —
this layer only bridges it to HTTP.
"""
