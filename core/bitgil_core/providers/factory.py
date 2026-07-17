"""Build a VisionProvider from a name + config, without importing every SDK.

Call sites depend only on this factory and the VisionProvider interface, so
adding a provider never touches the engine or the NVDA addon.
"""

from __future__ import annotations

from typing import Any, Mapping

from .base import VisionProvider

_KNOWN = {"anthropic", "openai", "gemini", "ollama"}


def build_provider(name: str, config: Mapping[str, Any] | None = None) -> VisionProvider:
	"""Construct a provider. `config` holds api_key / model / base_url etc.

	Provider modules are imported lazily so the caller only needs the SDK for
	the provider they actually chose.
	"""
	name = name.lower()
	cfg = dict(config or {})

	if name == "anthropic":
		from .anthropic_provider import AnthropicProvider

		return AnthropicProvider(**_pick(cfg, "api_key", "model"))
	if name == "openai":
		from .openai_provider import OpenAIProvider

		return OpenAIProvider(**_pick(cfg, "api_key", "model"))
	if name == "ollama":
		from .ollama_provider import OllamaProvider

		return OllamaProvider(**_pick(cfg, "model", "base_url"))

	if name in _KNOWN:
		raise NotImplementedError(f"provider '{name}' is planned but not yet implemented")
	raise ValueError(f"unknown provider '{name}' (known: {sorted(_KNOWN)})")


def _pick(cfg: Mapping[str, Any], *keys: str) -> dict:
	"""Keep only the keys a given provider accepts (and drop None values)."""
	return {k: cfg[k] for k in keys if cfg.get(k) is not None}
