"""Thin wrappers around Claude (Anthropic) and Gemini (Google AI Studio).

Both degrade gracefully: if the key/SDK is missing, ``available`` is False and
``complete()`` returns None so the pipeline can record "AI skipped" rather than
crash.
"""
from __future__ import annotations

import logging

import config

log = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self) -> None:
        self._client = None
        if config.ANTHROPIC_API_KEY:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            except Exception as exc:  # noqa: BLE001
                log.warning("Claude init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1200) -> str | None:
        if not self.available:
            return None
        try:
            msg = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system or "You are a precise equity & macro research assistant.",
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        except Exception as exc:  # noqa: BLE001
            log.error("Claude completion failed: %s", exc)
            return None


class GeminiClient:
    def __init__(self) -> None:
        self._model = None
        if config.GEMINI_API_KEY:
            try:
                import google.generativeai as genai

                genai.configure(api_key=config.GEMINI_API_KEY)
                self._model = genai.GenerativeModel(config.GEMINI_MODEL)
            except Exception as exc:  # noqa: BLE001
                log.warning("Gemini init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self._model is not None

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1200) -> str | None:
        if not self.available:
            return None
        try:
            full = f"{system}\n\n{prompt}" if system else prompt
            resp = self._model.generate_content(
                full,
                generation_config={"max_output_tokens": max_tokens, "temperature": 0.4},
            )
            return resp.text
        except Exception as exc:  # noqa: BLE001
            log.error("Gemini completion failed: %s", exc)
            return None
