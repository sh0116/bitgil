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

# How many alternative vision routes one call may try before giving up. Each attempt
# is a full round trip inside a narration turn, so latency bounds this, not patience.
_MAX_ROUTE_ATTEMPTS = 3

# Statuses that condemn a route for the session rather than for one call: the upstream
# can't take our payload (or isn't there), which no amount of waiting changes.
_ROUTE_IS_UNUSABLE = frozenset({400, 404, 415, 422, 501})


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
		self._candidates: list[str] | None = None
		self._dead_models: set[str] = set()

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
		"""POST, falling forward through vision-capable routes until one answers.

		Bitgil's payload is always a screenshot, and on OmniRoute nothing guarantees the
		chosen route can read one. Two independent ways it fails, both measured live:

		- A combo resolves to text-only upstreams → 400 "No target in combo ... has
		  confirmed vision support" — the combo channels never declare
		  `capabilities.vision` themselves, so the gateway can't promise this.
		- A model *does* declare vision but refuses the image anyway → 400 "DuckDuckGo
		  AI Chat error: ERR_BAD_REQUEST", or has no quota left → 429. The flag in
		  /v1/models is a claim, not a working route.

		The gateway's own fallback can't cover us here (that's what combos are for, and
		combos are the thing without a vision guarantee), so the retry lives here: ask
		which models claim vision, try them in turn, keep the one that works, and
		remember the ones that can't so later frames don't pay for them again. This runs
		mid-narration for someone who cannot read a terminal — an error they can act on
		is the last resort, not the first response.
		"""
		self._retire_dead_route()
		resp = self._post(messages, max_tokens, stream)
		if not self._should_reroute(resp):
			return resp
		attempted: list[str] = []
		for candidate in self._vision_candidates():
			if candidate in self._dead_models or candidate == self.model:
				continue
			if len(attempted) >= _MAX_ROUTE_ATTEMPTS:
				break
			resp.close()
			attempted.append(candidate)
			self.model = candidate
			self._vision_model_discovered = True
			resp = self._post(messages, max_tokens, stream)
			if resp.status_code < 400:
				return resp
			if resp.status_code in _ROUTE_IS_UNUSABLE:
				# The upstream rejected the *payload* (or doesn't exist): no later frame
				# will fare better, so stop spending a round trip on it every time.
				# A 429/5xx is left out — quota resets, so it stays a candidate.
				self._dead_models.add(candidate)
		if attempted:
			raise requests.HTTPError(
				f"OmniRoute: 이미지를 읽을 수 있는 모델 {len(attempted)}개를 시도했지만 모두 "
				f"실패했습니다 (마지막 {resp.status_code}: {_error_message(resp)}). "
				f"대시보드({self._dashboard_url()})에서 쿼터가 남은 비전 프로바이더를 연결하세요.",
				response=resp,
			)
		return resp

	def _retire_dead_route(self) -> None:
		"""Move off a route already known to refuse our payload, before spending a call.

		The fall-forward loop leaves `self.model` on the last route it tried, which on a
		total failure is a dead one. Without this, every later frame burns its first
		round trip re-asking a model that already said no — and each round trip is
		silence for someone waiting to hear what changed on screen. Only routes *we*
		chose are ever marked dead, so a user-pinned `--model` is never retired here.
		"""
		if self.model not in self._dead_models:
			return
		for candidate in self._vision_candidates():
			if candidate not in self._dead_models:
				self.model = candidate
				return

	def _should_reroute(self, resp) -> bool:
		"""Is this a failure on a route *we* chose, that another route might survive?"""
		if resp.status_code < 400 or resp.status_code == 401:
			return False       # 401 is auth — no other route fixes it
		# A combo default is our choice, not the user's, and so is anything we
		# discovered. An explicitly pinned `--model` is respected: the user asked for
		# that route, so its error is the answer.
		return self.model.startswith("auto/") or self._vision_model_discovered

	def _get_models(self):
		with self._readable():
			resp = requests.get(
				f"{self.base_url}/models", headers=self._headers(), timeout=_TIMEOUT
			)
		_raise_for_gateway_error(resp)
		return resp

	def _vision_candidates(self) -> list[str]:
		"""Model ids the gateway says can accept an image, widest context first.

		Cached: the model list doesn't change mid-session, and this runs inside a
		narration turn. Ordered by input capacity because the other measured rejection
		is a context-limit 400 on a screenshot.
		"""
		if self._candidates is not None:
			return self._candidates
		resp = self._get_models()
		found = _vision_first(_concrete_models(_json_or_empty(resp)))
		if not found:
			raise requests.HTTPError(
				"OmniRoute 게이트웨이에 이미지를 읽을 수 있는 모델이 없습니다. "
				f"대시보드({self._dashboard_url()})에서 비전 지원 프로바이더를 연결하세요.",
				response=resp,
			)
		self._candidates = [model_id for model_id, _, _ in found]
		return self._candidates

	def route_report(self) -> dict:
		"""What this gateway can do with an image — the data behind `--list-routes`.

		Diagnostic, not narration. When every route fails, the only useful next question
		is *which* models this install calls vision-capable, and that answer differs per
		machine (it follows the providers connected in the dashboard). Someone debugging
		this is usually the blind user themselves, so it has to be one command, not a
		hand-assembled curl | python pipeline.
		"""
		models = _concrete_models(_json_or_empty(self._get_models()))
		vision = _vision_first(models)
		return {
			"base_url": self.base_url,
			"dashboard": self._dashboard_url(),
			"authenticated": bool(self._api_key),
			"models": models,
			"vision": vision,
			# The same slice a narration turn would actually attempt, in order.
			"would_try": [model_id for model_id, _, _ in vision[:_MAX_ROUTE_ATTEMPTS]],
		}

	def _dashboard_url(self) -> str:
		# The gateway serves its dashboard at the root; base_url points at the /v1 API.
		return self.base_url[: -len("/v1")] if self.base_url.endswith("/v1") else self.base_url

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


def _json_or_empty(resp) -> dict:
	try:
		body = resp.json()
	except ValueError:
		return {}
	return body if isinstance(body, dict) else {}


def _concrete_models(payload: dict) -> list[tuple[str, int, bool]]:
	"""(id, input capacity, claims vision) for each non-combo model in /v1/models.

	The `auto/*` combos are dropped: they never declare `capabilities.vision`, which is
	the whole reason we ask the gateway which concrete model to use.
	"""
	models = []
	for entry in payload.get("data") or []:
		model_id = entry.get("id") or ""
		if not model_id or model_id.startswith("auto/"):
			continue
		room = entry.get("max_input_tokens") or entry.get("context_length") or 0
		claims_vision = bool((entry.get("capabilities") or {}).get("vision"))
		models.append((model_id, room, claims_vision))
	return models


def _vision_first(models: list[tuple[str, int, bool]]) -> list[tuple[str, int, bool]]:
	"""The image-capable models, widest input capacity first.

	Capacity decides the order because the other measured rejection of a screenshot is
	a context-limit 400 — the roomiest route is the likeliest to accept one.
	"""
	return sorted(
		(model for model in models if model[2]), key=lambda model: model[1], reverse=True
	)


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
