"""Response post-processing.

Between the raw LLM output and NVDA's voice we apply, in order:
  1. length capping (keep narration terse — configurable density),
  2. glossary substitution (game/subject terms -> Korean reading),
  3. importance filtering (drop low-signal chatter in live mode).
"""

from __future__ import annotations

from typing import Dict


def apply_glossary(text: str, glossary: Dict[str, str]) -> str:
	"""Replace terms with their profile-defined readings.

	e.g. {"HP": "체력", "Strength": "힘"} so the voice speaks natural Korean.
	Longest keys first to avoid partial-overlap surprises.
	"""
	for term in sorted(glossary, key=len, reverse=True):
		text = text.replace(term, glossary[term])
	return text


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
