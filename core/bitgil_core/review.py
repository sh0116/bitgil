"""Review notes (F4) — turn a session's narration history into study material.

As Bitgil narrates a lecture or game, each line is appended here with a
timestamp. At the end of the session the log exports to Markdown so a blind
student can re-read what happened — restoring the review affordance that sighted
students get from slides and notes.

The clock is injected (a ``() -> str`` returning a timestamp label) so exports
are deterministic under test and free of a hard datetime dependency in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

# Every export carries this so the note can never be mistaken for human-authored,
# reviewed study material. BLV users detect only ~half of AI errors (Hong &
# Kacorri, ASSETS 2024), and this is the one artifact that outlives the session
# as permanent study material — so it must announce that it needs human review.
_DISCLAIMER = (
	"이 노트는 AI가 화면을 보고 자동 생성한 것으로, 사실과 다른 내용이 있을 수 "
	"있습니다. 학습에 사용하기 전 반드시 사람이 원본과 대조해 검토하세요."
)


@dataclass
class ReviewEntry:
	text: str
	timestamp: str = ""


@dataclass
class ReviewLog:
	title: str = "Bitgil 세션 노트"
	clock: Optional[Callable[[], str]] = None
	entries: List[ReviewEntry] = field(default_factory=list)
	# Provenance — surfaced in the export header so a reader knows what produced
	# the note. Left blank when the caller doesn't know them.
	provider: str = ""
	model: str = ""

	def record(self, text: str) -> None:
		# Collapse ALL runs of whitespace (incl. internal newlines/tabs) to single
		# spaces so each entry stays one Markdown bullet — a raw "\n" mid-text would
		# otherwise split the line and break the list rendering.
		text = " ".join(text.split())
		if not text:
			return
		ts = self.clock() if self.clock is not None else ""
		self.entries.append(ReviewEntry(text=text, timestamp=ts))

	def _provenance_line(self) -> str:
		"""Human-readable provider/model/generated-at attribution, or "" if none."""
		parts: List[str] = []
		if self.provider:
			parts.append(f"제공자: {self.provider}")
		if self.model:
			parts.append(f"모델: {self.model}")
		generated_at = self.clock() if self.clock is not None else ""
		if generated_at:
			parts.append(f"생성: {generated_at}")
		return " · ".join(parts)

	def to_markdown(self) -> str:
		lines = [f"# {self.title}", ""]
		# Machine-generated marker + provenance always lead the document.
		lines.append(f"> ⚠️ {_DISCLAIMER}")
		provenance = self._provenance_line()
		if provenance:
			lines.append(">")
			lines.append(f"> {provenance}")
		lines.append("")
		if not self.entries:
			lines.append("_해설 기록이 없습니다._")
			return "\n".join(lines) + "\n"
		for e in self.entries:
			prefix = f"- **{e.timestamp}** — " if e.timestamp else "- "
			lines.append(f"{prefix}{e.text}")
		return "\n".join(lines) + "\n"

	def __len__(self) -> int:
		return len(self.entries)
