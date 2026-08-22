"""Build a VisionProvider from a name + config, without importing every SDK.

Call sites depend only on this factory and the VisionProvider interface, so
adding a provider never touches the engine or the NVDA addon.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .base import VisionProvider

_KNOWN = {"demo", "anthropic", "bedrock", "openai", "gemini", "ollama"}


def build_provider(
	name: str,
	config: Mapping[str, Any] | None = None,
	*,
	speed: Optional[str] = None,
) -> VisionProvider:
	"""Construct a provider. `config` holds api_key / model / base_url etc.

	`speed` is the active profile's tier ("fast" | "balanced" | "quality"). When
	config does not pin a model, the tier resolves to a concrete model for the
	chosen provider — so a latency-sensitive profile automatically gets a faster
	model without hard-coding a provider-specific id in the profile. Precedence:
	explicit config model > profile speed tier > provider default.

	Provider modules are imported lazily so the caller only needs the SDK for
	the provider they actually chose.
	"""
	name = name.lower()
	cfg = dict(config or {})

	if name == "demo":
		# Keyless canned-narration provider — no SDK, no credentials, no config.
		from .demo_provider import DemoProvider

		return DemoProvider()
	if name == "anthropic":
		from .anthropic_provider import AnthropicProvider

		return AnthropicProvider(**_resolve(cfg, AnthropicProvider, speed, "api_key", "model"))
	if name == "bedrock":
		# Claude via Bedrock — uses the AWS credential chain, not an API key.
		from .bedrock_provider import BedrockProvider

		return BedrockProvider(**_resolve(cfg, BedrockProvider, speed, "model", "aws_region"))
	if name == "openai":
		from .openai_provider import OpenAIProvider

		return OpenAIProvider(**_resolve(cfg, OpenAIProvider, speed, "api_key", "model"))
	if name == "gemini":
		from .gemini_provider import GeminiProvider

		return GeminiProvider(**_resolve(cfg, GeminiProvider, speed, "api_key", "model"))
	if name == "ollama":
		# Ollama runs whatever local model the user pulled, so speed tiers don't map.
		from .ollama_provider import OllamaProvider

		return OllamaProvider(**_pick(cfg, "model", "base_url"))

	raise ValueError(f"unknown provider '{name}' (known: {sorted(_KNOWN)})")


def _resolve(
	cfg: dict, provider_cls: type, speed: Optional[str], *keys: str
) -> dict:
	"""Fill in a speed-tier model when the caller didn't pin one, then _pick."""
	if not cfg.get("model") and speed:
		tier_model = provider_cls.model_for_speed(speed)
		if tier_model:
			cfg = {**cfg, "model": tier_model}
	return _pick(cfg, *keys)


def _pick(cfg: Mapping[str, Any], *keys: str) -> dict:
	"""Keep only the keys a given provider accepts (and drop None values)."""
	return {k: cfg[k] for k in keys if cfg.get(k) is not None}
