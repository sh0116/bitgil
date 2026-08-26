"""Ollama (local) vision provider adapter.

The privacy-first path: the screen never leaves the machine. Talks to a local
Ollama server over HTTP, so it needs a vision-capable local model (e.g. llava,
llama3.2-vision). No API key.
"""

from __future__ import annotations

import base64
import json
from typing import Iterator, Sequence

import requests

from . import endpoint_errors
from .base import Message, VisionProvider, VisionResponse

DEFAULT_MODEL = "llava"
DEFAULT_BASE_URL = "http://localhost:11434"


def _to_ollama(messages: Sequence[Message]) -> list[dict]:
	converted: list[dict] = []
	for m in messages:
		entry: dict = {"role": m.role, "content": m.text}
		if m.image is not None:
			# Ollama takes images as a list of base64 strings on the message.
			entry["images"] = [base64.standard_b64encode(m.image).decode("ascii")]
		converted.append(entry)
	return converted


class OllamaProvider(VisionProvider):
	name = "ollama"

	def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL):
		self.model = model
		self.base_url = base_url.rstrip("/")

	def _readable(self):
		return endpoint_errors.readable(
			"Ollama", self.base_url,
			f"`ollama serve`가 실행 중이고 '{self.model}' 모델을 받아뒀는지 확인하세요.",
		)

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		with self._readable():
			resp = requests.post(
				f"{self.base_url}/api/chat",
				json={
					"model": self.model,
					"messages": _to_ollama(messages),
					"stream": False,
					"options": {"num_predict": max_tokens},
				},
				timeout=120,
			)
		resp.raise_for_status()
		data = resp.json()
		return VisionResponse(
			text=data.get("message", {}).get("content", ""),
			prompt_tokens=data.get("prompt_eval_count", 0),
			completion_tokens=data.get("eval_count", 0),
		)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		# _readable() also covers the iteration below: a stream can drop mid-flight.
		with self._readable(), requests.post(
			f"{self.base_url}/api/chat",
			json={
				"model": self.model,
				"messages": _to_ollama(messages),
				"stream": True,
				"options": {"num_predict": max_tokens},
			},
			timeout=120,
			stream=True,
		) as resp:
			resp.raise_for_status()
			for line in resp.iter_lines():
				if not line:
					continue
				chunk = json.loads(line)
				piece = chunk.get("message", {}).get("content", "")
				if piece:
					yield piece
