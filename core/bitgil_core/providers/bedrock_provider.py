"""Amazon Bedrock (Claude) vision provider adapter.

Same Claude models as the direct Anthropic provider, but reached through Bedrock
using the AWS credential chain (env / ~/.aws / instance role) instead of an
Anthropic API key. Handy where an org already has AWS + Bedrock access rather
than a standalone Anthropic key.

Reuses AnthropicProvider's message conversion — only the client differs. The SDK
is imported lazily so importing this module (and the test suite) needs neither
`anthropic` nor `boto3`.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from .anthropic_provider import _to_anthropic
from .base import Message, VisionProvider, VisionResponse

# Cross-region inference profiles for the APAC region (ap-northeast-2 / Seoul).
# All are vision-capable. Adjust to whatever your account has model access to;
# override per call via config `model` / the CLI `--model` flag.
DEFAULT_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
SPEED_MODELS = {
	"fast": "apac.anthropic.claude-3-haiku-20240307-v1:0",
	"balanced": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
	"quality": "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
}


class BedrockProvider(VisionProvider):
	name = "bedrock"
	SPEED_MODELS = SPEED_MODELS

	def __init__(self, model: str = DEFAULT_MODEL, aws_region: str | None = None):
		self.model = model
		self.aws_region = aws_region
		self._client = None

	def _get_client(self):
		if self._client is None:
			import anthropic  # lazy: pulls in boto3 for the AWS credential chain

			kwargs = {}
			if self.aws_region:
				kwargs["aws_region"] = self.aws_region
			self._client = anthropic.AnthropicBedrock(**kwargs)
		return self._client

	def complete(self, messages: Sequence[Message], *, max_tokens: int = 300) -> VisionResponse:
		system, msgs = _to_anthropic(messages)
		resp = self._get_client().messages.create(
			model=self.model,
			max_tokens=max_tokens,
			system=system or None,
			messages=msgs,
		)
		text = "".join(b.text for b in resp.content if b.type == "text")
		return VisionResponse(
			text=text,
			prompt_tokens=resp.usage.input_tokens,
			completion_tokens=resp.usage.output_tokens,
		)

	def stream(self, messages: Sequence[Message], *, max_tokens: int = 300) -> Iterator[str]:
		system, msgs = _to_anthropic(messages)
		with self._get_client().messages.stream(
			model=self.model,
			max_tokens=max_tokens,
			system=system or None,
			messages=msgs,
		) as stream:
			yield from stream.text_stream
