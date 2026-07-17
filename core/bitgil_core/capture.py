"""Screen capture → PNG bytes.

Reusable and screen-reader-agnostic (no NVDA dependency), but desktop-only:
`mss` is an optional extra (`pip install bitgil-core[capture]`) and is imported
lazily so the rest of the core works in headless CI.

Privacy note: captured frames are personal content — never log or persist them;
pass the bytes straight to the change detector / provider and drop them.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple


def capture_screen(monitor: int = 1, region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
	"""Capture the screen (or a region) and return PNG-encoded bytes.

	Parameters
	----------
	monitor:
		mss monitor index (1 = primary; 0 = all monitors combined).
	region:
		Optional ``(left, top, width, height)`` in pixels to crop to a window or
		a profile's region-of-interest.
	"""
	import mss
	from PIL import Image

	with mss.mss() as sct:
		if region is not None:
			left, top, width, height = region
			bbox = {"left": left, "top": top, "width": width, "height": height}
		else:
			bbox = sct.monitors[monitor]
		shot = sct.grab(bbox)
		img = Image.frombytes("RGB", shot.size, shot.rgb)

	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()
