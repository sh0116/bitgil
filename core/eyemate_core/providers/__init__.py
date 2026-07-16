"""Vision-LLM provider adapters behind a single interface.

Following AI-content-describer's proven multi-provider approach: users bring
their own API key and pick a provider. A local option (Ollama) supports the
privacy-first / offline path.
"""

from .base import Message, VisionProvider, VisionResponse

__all__ = ["VisionProvider", "Message", "VisionResponse"]
