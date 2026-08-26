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

import contextlib
import json
import os
from typing import Iterator, Sequence

import requests

from . import endpoint_errors
from .base import Message, VisionProvider, VisionResponse
from .openai_provider import _to_openai  # identical wire format (OpenAI-compatible)

DEFAULT_MODEL = "auto/best-vision"
DEFAULT_BASE_URL = "http://localhost:20128/v1"

# Where to look for the gateway's own token when the caller didn't pass one. The
# other adapters delegate this to their vendor SDK; OmniRoute has no SDK, so the
# lookup lives here. `OMNIROUTE_API_KEY` is the gateway CLI's own variable name,
# so a user who already exported it for `omniroute` gets authenticated with no
# extra setup — the point being that nobody should have to retype a token to
# start narrating.
_API_KEY_ENV = ("OMNIROUTE_API_KEY", "BITGIL_API_KEY")


def _api_key_from_env() -> str | None:
	for var in _API_KEY_ENV:
		value = os.environ.get(var, "").strip()
		if value:
			return value
	return None


# Speed tier → model. These are combo channels, not fixed models: OmniRoute picks a
# healthy upstream per call and falls back when one is exhausted, so a tier is a
# *policy* ("cheap and quick" vs "best available") rather than one model id.
#
# Measured against live gateways (v16, 2026-08-26) — a combo is a *starting point*,
# never a guarantee, because what it resolves to depends on which providers that
# install has connected:
#   - `auto/vision` / `auto/multimodal` reject a screenshot outright ("every
#     auto-strategy candidate has a smaller known context limit" for a ~1.2k-token
#     image); their pools hold small free models. Never map a tier there.
#   - `auto/best-vision` / `auto/pro-vision` clear that bar, so they stay the
#     defaults — but on an install whose connected providers expose no image-capable
#     target they answer 400 "No target in combo ... has confirmed vision support".
#   - No `auto/*` channel declares `capabilities.vision` in /v1/models at all; only
#     concrete models do. That is what `_discover_vision_model` leans on, and why a
#     hard-coded id would be right only for its author's install.
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
		# remote or has scoped tokens enabled. Falling back to the environment
		# keeps the token out of argv (and out of shell history).
		self._api_key = api_key or _api_key_from_env()
		self._vision_model_discovered = False

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

	def _post(self, messages: Sequence[Message], max_tokens: int, stream: bool):
		with self._readable():
			return requests.post(
				f"{self.base_url}/chat/completions",
				json=self._body(messages, max_tokens, stream),
				headers=self._headers(),
				timeout=_TIMEOUT,
				stream=stream,
			)

	def _open(self, messages: Sequence[Message], max_tokens: int, stream: bool):
		"""POST, and once recover from "this route can't see images" by finding one that can.

		Which upstreams a combo channel resolves to depends on what the user connected
		to their gateway, so no hard-coded id is right for everyone: a fresh install
		answers `auto/pro-vision` with 400 "No target in combo ... has confirmed vision
		support". Bitgil's whole payload is a screenshot, so that verdict is fatal —
		and it arrives *spoken aloud*, mid-narration, to someone who cannot go read a
		model list. So ask the gateway which of its models declares vision support and
		retry on that one, remembering it for the rest of the session.
		"""
		resp = self._post(messages, max_tokens, stream)
		if self._vision_route_rejected(resp):
			resp.close()
			self.model = self._discover_vision_model()
			self._vision_model_discovered = True
			resp = self._post(messages, max_tokens, stream)
		return resp

	def _vision_route_rejected(self, resp) -> bool:
		# Narrow on purpose: only a 400 that actually blames vision support, and only
		# once per instance — a second such 400 means discovery picked a route that
		# can't serve us either, and retrying forever would just delay the error.
		if resp.status_code != 400 or self._vision_model_discovered:
			return False
		return "vision" in _error_message(resp).lower()

	def _discover_vision_model(self) -> str:
		"""Return a model id the gateway says can accept an image."""
		with self._readable():
			resp = requests.get(
				f"{self.base_url}/models", headers=self._headers(), timeout=_TIMEOUT
			)
		_raise_for_gateway_error(resp)
		try:
			data = resp.json()
		except ValueError:
			data = {}
		for entry in data.get("data") or []:
			model_id = entry.get("id") or ""
			# Skip the auto/* combos: they never declare vision themselves, which is
			# exactly how we got here.
			if model_id.startswith("auto/"):
				continue
			if (entry.get("capabilities") or {}).get("vision"):
				return model_id
		raise requests.HTTPError(
			"OmniRoute 게이트웨이에 이미지를 읽을 수 있는 모델이 없습니다. "
			f"대시보드({self.base_url.rsplit('/', 1)[0]})에서 비전 지원 프로바이더를 "
			"연결하세요.",
			response=resp,
		)

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		resp = self._open(messages, max_tokens, stream=False)
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
		with self._readable(), contextlib.closing(
			self._open(messages, max_tokens, stream=True)
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


def _error_message(resp) -> str:
	"""The gateway's own explanation for a failed call, or its raw body."""
	try:
		body = resp.json()
	except ValueError:
		return (resp.text or "")[:200]
	if not isinstance(body, dict):
		return ""
	err = body.get("error")
	return (err or {}).get("message", "") if isinstance(err, dict) else str(err or "")


def _raise_for_gateway_error(resp) -> None:
	"""Surface the gateway's own error text, not just the HTTP status.

	OmniRoute answers an exhausted free pool with a structured body naming the
	failed upstreams ("insufficient_quota", "[403] oc/mimo-v2.5-free ..."). The CLI
	and web UI print this string to the user, so the cause has to survive.
	"""
	if resp.status_code < 400:
		return
	detail = _error_message(resp)
	if resp.status_code == 401:
		# A token-gated gateway says only "Authentication required", which read aloud
		# gives the user nothing to act on. Name the variable that fixes it. (403 is
		# *not* included: the gateway also uses it for an exhausted upstream quota,
		# where an auth hint would send the user down the wrong path.)
		raise requests.HTTPError(
			f"OmniRoute 401: 게이트웨이가 인증을 요구합니다. "
			f"OMNIROUTE_API_KEY 환경변수에 토큰을 넣으세요 "
			f"(omniroute tokens create). {detail}".rstrip(),
			response=resp,
		)
	raise requests.HTTPError(
		f"OmniRoute {resp.status_code}: {detail or 'request failed'}", response=resp
	)
