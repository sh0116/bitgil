# eyemate-core

Reusable, screen-reader-agnostic core for [EyeMate (눈동무)](../README.md).

This package is **MIT-licensed** on purpose: while the NVDA add-on itself must be
GPLv2 (it runs inside the GPLv2 NVDA process), the logic below has no NVDA
dependency and can be reused by other screen readers (Orca, etc.) or standalone
apps.

## Modules

| Module | Role |
|--------|------|
| `providers/` | Vision-LLM provider adapters (OpenAI, Anthropic, Gemini, Ollama) behind one interface |
| `change_detect/` | Perceptual-hash + OCR-diff gate — call the LLM only on *meaningful* change |
| `context/` | Session context: recent narration history + active profile prompt |
| `postprocess/` | Response post-processing: length caps, glossary substitution, importance filtering |
| `profiles.py` | YAML profile loader (domain/community profile packs) |

## Install

```bash
pip install -e .[dev,openai,anthropic]
```
