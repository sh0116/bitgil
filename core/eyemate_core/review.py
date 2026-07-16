"""Review notes (F4) — turn a session's narration history into study material.

As EyeMate narrates a lecture or game, each line is appended here with a
timestamp. At the end of the session the log exports to Markdown so a blind
student can re-read what happened — restoring the review affordance that sighted
students get from slides and notes.

The clock is injected (a ``() -> str`` returning a timestamp label) so exports
are deterministic under test and free of a hard datetime dependency in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class ReviewEntry:
	text: str
	timestamp: str = ""


@dataclass
class ReviewLog:
	title: str = "EyeMate 세션 노트"
	clock: Optional[Callable[[], str]] = None
	entries: List[ReviewEntry] = field(default_factory=list)

	def record(self, text: str) -> None:
		text = text.strip()
		if not text:
			return
		ts = self.clock() if self.clock is not None else ""
		self.entries.append(ReviewEntry(text=text, timestamp=ts))

	def to_markdown(self) -> str:
		lines = [f"# {self.title}", ""]
		if not self.entries:
			lines.append("_해설 기록이 없습니다._")
			return "\n".join(lines) + "\n"
		for e in self.entries:
			prefix = f"- **{e.timestamp}** — " if e.timestamp else "- "
			lines.append(f"{prefix}{e.text}")
		return "\n".join(lines) + "\n"

	def __len__(self) -> int:
		return len(self.entries)
