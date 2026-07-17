"""OCR adapter — extract on-screen text for the change-detection gate.

Optional (`pip install bitgil-core[ocr]`). `build_ocr()` returns a
``bytes -> str`` callable suitable for `ChangeDetector(ocr=...)`, or raises if
the engine isn't available. The heavy dependency (rapidocr) is imported lazily
so the rest of the core stays light and headless-safe.

The callable is intentionally the same shape the detector already accepts, so
OCR is injected, not hard-wired — keeping the detector unit-testable with a
fake.
"""

from __future__ import annotations

import io
from typing import Callable


def build_ocr(engine: str = "rapidocr") -> Callable[[bytes], str]:
	"""Return an OCR callable. Currently backs onto rapidocr-onnxruntime."""
	if engine != "rapidocr":
		raise ValueError(f"unknown OCR engine '{engine}'")

	import numpy as np
	from PIL import Image
	from rapidocr_onnxruntime import RapidOCR

	reader = RapidOCR()

	def ocr(frame: bytes) -> str:
		with Image.open(io.BytesIO(frame)) as img:
			arr = np.array(img.convert("RGB"))
		result, _ = reader(arr)
		if not result:
			return ""
		# result rows are [box, text, score]; join the recognised text.
		return "\n".join(row[1] for row in result)

	return ocr
