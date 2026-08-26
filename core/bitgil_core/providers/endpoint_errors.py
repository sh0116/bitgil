"""Readable failures for the endpoint-based providers (Ollama, OmniRoute).

Whatever a provider raises gets **read aloud**: the web backend answers a failed
frame with ``{"text": "오류: <exception>"}`` and the client speaks it. So a bare
requests exception becomes a paragraph of URL-encoded noise in the user's ear —
"HTTPConnectionPool(host='localhost', port=20128): Max retries exceeded with url:
/v1/chat/completions (Caused by NewConnectionError(...))" — which says nothing
actionable. These wrappers replace the two failures a local endpoint actually hits
with one spoken sentence naming the cause and the fix.

Kept out of `base.py` on purpose: `base` is imported on every provider path,
including inside the NVDA add-on, and must not pull in `requests`.
"""

from __future__ import annotations

import contextlib
from typing import Iterator

import requests


@contextlib.contextmanager
def readable(label: str, base_url: str, hint: str) -> Iterator[None]:
	"""Translate connection/timeout failures against `base_url` into one sentence.

	`label` names the service ("Ollama"), `hint` says what to do about it. Other
	exceptions pass through untouched — an HTTP error already carries the
	endpoint's own message, which is more specific than anything we'd add.
	"""
	try:
		yield
	except requests.ConnectionError:
		raise requests.ConnectionError(
			f"{label}에 연결할 수 없습니다 ({base_url}). {hint}"
		) from None
	except requests.Timeout:
		raise requests.Timeout(
			f"{label}이(가) 제때 응답하지 않았습니다 ({base_url}). "
			f"모델이 너무 크거나 서버가 바쁠 수 있습니다."
		) from None
