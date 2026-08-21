"""Response post-processing.

Between the raw LLM output and NVDA's voice we apply, in order:
  1. sentence aggregation for streaming (buffer fragments into whole phrases),
  2. length capping (keep narration terse — configurable density),
  3. glossary substitution (game/subject terms -> Korean reading),
  4. importance filtering (drop low-signal chatter in live mode).
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Iterator

# --- sentence aggregation ---------------------------------------------------

# Characters that always close a spoken unit (CJK + ASCII bang/question + newline).
_HARD_ENDS = frozenset("。！？!?\n")
# A period is a *soft* ender: it also delimits decimals ("3.5") and ellipses
# ("...") where breaking would make NVDA read broken fragments ("3점" … "5입니다").
# It only counts as a boundary once the following character disambiguates it.


def iter_sentences(chunks: Iterable[str]) -> Iterator[str]:
	"""Aggregate streamed text chunks into whole sentences.

	Provider streams arrive in arbitrary fragments; speaking each fragment makes
	NVDA stutter. This buffers until a sentence boundary, then flushes — so the
	user hears complete phrases as they form. Any trailing text without a
	terminator is flushed at the end.

	A period is not treated as a boundary when it sits between digits (a decimal
	like ``3.5``) or inside an ellipsis (``...``) — important for math/chart
	narration where numbers must stay intact. When a period is the last buffered
	character we defer the decision until the next chunk reveals what follows;
	whatever remains at end-of-stream is flushed as-is.
	"""
	buffer = ""
	for chunk in chunks:
		buffer += chunk
		while True:
			idx = _first_end(buffer)
			if idx == -1:
				break
			sentence = buffer[: idx + 1].strip()
			buffer = buffer[idx + 1 :]
			if sentence:
				yield sentence
	tail = buffer.strip()
	if tail:
		yield tail


def _first_end(text: str) -> int:
	"""Index of the first confident sentence-ending char in ``text``, else -1.

	Returns -1 both when no ender is present and when the only candidate is a
	trailing period whose role can't yet be decided (needs the next char) — the
	caller then waits for more chunks.
	"""
	n = len(text)
	for i, c in enumerate(text):
		if c in _HARD_ENDS:
			return i
		if c == ".":
			nxt = text[i + 1] if i + 1 < n else ""
			prev = text[i - 1] if i > 0 else ""
			if nxt == "":
				return -1  # trailing period — wait for the next char to disambiguate
			if nxt.isdigit() and prev.isdigit():
				continue   # decimal point, e.g. 3.5
			if nxt == ".":
				continue   # ellipsis — the boundary falls on the run's last dot
			return i
	return -1


# --- glossary + length ------------------------------------------------------


def apply_glossary(text: str, glossary: Dict[str, str]) -> str:
	"""Replace terms with their profile-defined readings.

	e.g. {"HP": "체력", "Strength": "힘"} so the voice speaks natural Korean.

	Done in a SINGLE left-to-right pass (regex alternation, longest key first) so
	that a replacement's output is never re-scanned by a later key. The naive
	per-term ``str.replace`` loop cascaded: glossary {"HP":"체력바","바":"BAR"} on
	"HP" produced "체력BAR" because the injected "바" got rewritten again. Longest
	key first also lets a multi-char term win over a substring of it at the same
	position. Substring matching (no word boundaries) is intentional — CJK terms
	attach to adjacent characters with no spaces.
	"""
	if not glossary:
		return text
	keys = sorted(glossary, key=len, reverse=True)
	pattern = re.compile("|".join(re.escape(k) for k in keys))
	return pattern.sub(lambda m: glossary[m.group(0)], text)


def cap_length(text: str, max_chars: int) -> str:
	"""Trim to a sentence boundary at or before `max_chars`."""
	if len(text) <= max_chars:
		return text
	cut = text[:max_chars]
	for sep in ("。", ". ", "! ", "? ", "\n"):
		idx = cut.rfind(sep)
		if idx != -1:
			return cut[: idx + len(sep)].strip()
	return cut.strip()
