"""Hand-built PDF fixtures shared by the document and web-server tests.

Written by hand (correct xref offsets) rather than with a generator dependency, so
the offline test suite stays dependency-light. `scanned_pdf` is genuinely text-less —
Pillow renders glyphs as pixels — so it exercises the real rejection path in
`load_pdf`, not a mocked one.
"""

import io

from PIL import Image


def pdf_with_text(lines) -> bytes:
	"""Minimal single-page PDF carrying a real text layer (latin-1 glyphs)."""
	drawn = "".join(f"({line}) Tj T*\n" for line in lines)
	content = "BT /F1 12 Tf 72 720 Td 14 TL\n" + drawn + "ET"
	objs = [
		"<</Type/Catalog/Pages 2 0 R>>",
		"<</Type/Pages/Kids[3 0 R]/Count 1>>",
		"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
		"/Resources<</Font<</F1 5 0 R>>>>>>",
		f"<</Length {len(content)}>>\nstream\n{content}\nendstream",
		"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
	]
	out = "%PDF-1.4\n"
	offsets = []
	for i, body in enumerate(objs, start=1):
		offsets.append(len(out))
		out += f"{i} 0 obj\n{body}\nendobj\n"
	xref = len(out)
	out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
	out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
	out += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n"
	return out.encode("latin-1")


def scanned_pdf() -> bytes:
	"""A PDF whose glyphs are pixels — i.e. no text layer at all."""
	buf = io.BytesIO()
	Image.new("RGB", (300, 400), "white").save(buf, format="PDF")
	return buf.getvalue()
