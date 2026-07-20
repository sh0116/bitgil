"""Image helpers shared across the pipeline.

Screen-reader-agnostic and dependency-light (Pillow only). Kept separate from
`capture` because capture is desktop-only (`mss`) while these operate on raw
image bytes from any source — a saved screenshot, the CLI, or a live frame.
"""

from __future__ import annotations

import io


def downscale_png(data: bytes, max_dim: int) -> bytes:
	"""Downscale an image so its longest edge is at most `max_dim` px.

	Returns PNG bytes. The vision LLM round-trip dominates live-mode latency, and
	both upload size and vision-token count scale with resolution — so shrinking
	oversized screenshots is the cheapest latency/cost win available, with little
	quality loss for on-screen text and UI. Images already within the bound (and
	`max_dim <= 0`) are returned unchanged, so this is safe to call unconditionally.
	"""
	if max_dim <= 0:
		return data

	from PIL import Image

	with Image.open(io.BytesIO(data)) as img:
		longest = max(img.size)
		if longest <= max_dim:
			return data
		scale = max_dim / longest
		new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
		resized = img.resize(new_size, Image.LANCZOS)
		buf = io.BytesIO()
		resized.save(buf, format="PNG")
		return buf.getvalue()
