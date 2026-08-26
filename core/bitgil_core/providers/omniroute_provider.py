"""OmniRoute (self-hosted AI gateway) vision provider adapter.

OmniRoute (https://github.com/diegosouzapw/OmniRoute, MIT) is a local gateway that
exposes many upstream providers behind one OpenAI-compatible endpoint, keyless by
default. For Bitgil it fills a specific gap: **real vision narration with no vendor
API key and no extra SDK.** It speaks plain HTTP, so this adapter uses `requests`
(already a core dependency) instead of the `openai` SDK — which also means it works
inside the NVDA add-on without vendoring a platform wheel.

Model ids are OmniRoute's own: concrete (`aug/haiku4.5`) or a virtual "combo"
channel that auto-routes with fallback (`auto/vision`). Every Bitgil call carries a
screenshot, so the speed tiers map to **vision** channels — a text-only channel
would silently drop the image.

Run the gateway first (default port 20128), then:
    python scripts/bitgil_demo.py --image slide.png --provider omniroute
"""

from __future__ import annotations

import json
from typing import Iterator, Sequence

import requests

from . import endpoint_errors
from .base import Message, VisionProvider, VisionResponse
from .openai_provider import _to_openai  # identical wire format (OpenAI-compatible)

DEFAULT_MODEL = "auto/best-vision"
DEFAULT_BASE_URL = "http://localhost:20128/v1"

# Speed tier → model. These are combo channels, not fixed models: OmniRoute picks a
# healthy upstream per call and falls back when one is exhausted, so a tier is a
# *policy* ("cheap and quick" vs "best available") rather than one model id.
#
# Measured against a live gateway (v16, 2026-08-26): the plain `auto/vision` and
# `auto/multimodal` channels reject a screenshot outright — "every auto-strategy
# candidate has a smaller known context limit" for a ~1.2k-token image — because
# their pools hold small free models. Only the `best-`/`pro-` vision channels carry
# candidates that can hold a frame, so both ends of the tier map point there.
SPEED_MODELS = {
	"fast": "auto/best-vision",
	"balanced": "auto/best-vision",
	"quality": "auto/pro-vision",
}

_TIMEOUT = 120


class OmniRouteProvider(VisionProvider):
	name = "omniroute"
	SPEED_MODELS = SPEED_MODELS

	def __init__(
		self,
		model: str = DEFAULT_MODEL,
		base_url: str = DEFAULT_BASE_URL,
		api_key: str | None = None,
	):
		self.model = model
		self.base_url = base_url.rstrip("/")
		# Keyless is the normal case; a key is only needed when the gateway is
		# remote or has scoped tokens enabled.
		self._api_key = api_key

	def _headers(self) -> dict:
		headers = {"Content-Type": "application/json"}
		if self._api_key:
			headers["Authorization"] = f"Bearer {self._api_key}"
		return headers

	def _body(self, messages: Sequence[Message], max_tokens: int, stream: bool) -> dict:
		body = {
			"model": self.model,
			"max_tokens": max_tokens,
			"messages": _to_openai(messages),
		}
		if stream:
			body["stream"] = True
		return body

	def _readable(self):
		return endpoint_errors.readable(
			"OmniRoute 게이트웨이", self.base_url,
			"게이트웨이가 실행 중인지, 포트가 맞는지 확인하세요(--base-url).",
		)

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		with self._readable():
			resp = requests.post(
				f"{self.base_url}/chat/completions",
				json=self._body(messages, max_tokens, stream=False),
				headers=self._headers(),
				timeout=_TIMEOUT,
			)
		_raise_for_gateway_error(resp)
		try:
			data = resp.json()
		except ValueError:
			# A 2xx with a non-JSON body (proxy page, truncated reply) would otherwise
			# surface as a bare "Expecting value: line 1 column 1" to a blind user.
			raise requests.HTTPError(
				f"OmniRoute returned a non-JSON body ({resp.status_code}): "
				f"{(resp.text or '')[:200]}",
				response=resp,
			) from None
		choices = data.get("choices") or [{}]
		usage = data.get("usage") or {}
		return VisionResponse(
			text=(choices[0].get("message") or {}).get("content") or "",
			prompt_tokens=usage.get("prompt_tokens", 0) or 0,
			completion_tokens=usage.get("completion_tokens", 0) or 0,
			# Which upstream actually served the call — a combo channel can differ
			# from the requested id, and the review-note provenance should say so.
			extra={"served_model": data.get("model", "")},
		)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		# _readable() also covers the iteration below: a stream can drop mid-flight.
		with self._readable(), requests.post(
			f"{self.base_url}/chat/completions",
			json=self._body(messages, max_tokens, stream=True),
			headers=self._headers(),
			timeout=_TIMEOUT,
			stream=True,
		) as resp:
			_raise_for_gateway_error(resp)
			for raw in resp.iter_lines():
				if not raw:
					continue
				line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
				if not line.startswith("data:"):
					continue          # SSE comments / keep-alive pings
				payload = line[len("data:"):].strip()
				if not payload or payload == "[DONE]":
					continue
				try:
					chunk = json.loads(payload)
				except ValueError:
					continue          # a truncated frame must not kill the narration
				choices = chunk.get("choices") or []
				if not choices:
					continue          # usage-only trailing chunk
				piece = (choices[0].get("delta") or {}).get("content")
				if piece:
					yield piece


def _raise_for_gateway_error(resp) -> None:
	"""Surface the gateway's own error text, not just the HTTP status.

	OmniRoute answers an exhausted free pool with a structured body naming the
	failed upstreams ("insufficient_quota", "[403] oc/mimo-v2.5-free ..."). The CLI
	and web UI print this string to the user, so the cause has to survive.
	"""
	if resp.status_code < 400:
		return
	detail = ""
	try:
		body = resp.json()
		if isinstance(body, dict):
			err = body.get("error")
			detail = (err or {}).get("message", "") if isinstance(err, dict) else str(err or "")
	except ValueError:
		detail = (resp.text or "")[:200]
	raise requests.HTTPError(
		f"OmniRoute {resp.status_code}: {detail or 'request failed'}", response=resp
	)
