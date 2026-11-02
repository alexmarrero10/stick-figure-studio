"""Shared Anthropic client: streaming text, JSON-schema structured output, web search."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterator

import anthropic

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeError(RuntimeError):
    pass


class Claude:
    def __init__(self, api_key: str, cfg: dict[str, Any]):
        if not api_key:
            raise ClaudeError("ANTHROPIC_API_KEY is not set. Add it on the Settings page.")
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.model = cfg.get("model", "claude-opus-5-5")
        self.effort = cfg.get("effort", "high")
        self.use_fallbacks = cfg.get("use_fallbacks", True)

    # -- internals -----------------------------------------------------------

    def _params(self, system: Any, messages: list[dict[str, Any]], max_tokens: int,
                fmt: dict[str, Any] | None = None, tools: list[dict[str, Any]] | None = None,
                effort: str | None = None) -> dict[str, Any]:
        output_config: dict[str, Any] = {"effort": effort or self.effort}
        if fmt:
            output_config["format"] = fmt
        p: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": output_config,
            "thinking": {"type": "adaptive"},
        }
        if tools:
            p["tools"] = tools
        if self.use_fallbacks:
            p["betas"] = [FALLBACK_BETA]
            p["fallbacks"] = "default"
        return p

    def _stream(self, params: dict[str, Any]):
        if self.use_fallbacks:
            return self.client.beta.messages.stream(**params)
        return self.client.messages.stream(**params)

    @staticmethod
    def _check(msg: Any) -> None:
        if msg.stop_reason == "refusal":
            detail = getattr(msg, "stop_details", None)
            cat = getattr(detail, "category", None) if detail else None
            raise ClaudeError(f"Claude declined this request{f' ({cat})' if cat else ''}. Try rephrasing the idea.")
        if msg.stop_reason == "max_tokens":
            raise ClaudeError("Claude's response was cut off (max_tokens). Try again.")

    @staticmethod
    def _wrap(e: Exception) -> ClaudeError:
        if isinstance(e, anthropic.AuthenticationError):
            return ClaudeError("Anthropic rejected the API key. Check it on the Settings page.")
        if isinstance(e, anthropic.RateLimitError):
            return ClaudeError("Anthropic rate limit hit. Wait a minute and try again.")
        if isinstance(e, anthropic.APIStatusError):
            return ClaudeError(f"Anthropic API error {e.status_code}: {e.message}")
        if isinstance(e, anthropic.APIConnectionError):
            return ClaudeError("Could not reach the Anthropic API. Check your internet connection.")
        return ClaudeError(str(e))

    @staticmethod
    def text_of(msg: Any) -> str:
        return "".join(b.text for b in msg.content if b.type == "text")

    # -- public API ----------------------------------------------------------

    def stream_text(self, system: Any, messages: list[dict[str, Any]], max_tokens: int = 64000,
                    tools: list[dict[str, Any]] | None = None) -> Iterator[str]:
        """Yield text as it is generated. Resumes automatically on pause_turn (server tools)."""
        messages = list(messages)
        try:
            for _ in range(6):
                with self._stream(self._params(system, messages, max_tokens, tools=tools)) as stream:
                    for text in stream.text_stream:
                        yield text
                    msg = stream.get_final_message()
                if msg.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": msg.content})
                    continue
                self._check(msg)
                return
            raise ClaudeError("Claude paused too many times while searching.")
        except anthropic.AnthropicError as e:
            raise self._wrap(e) from e

    def complete(self, system: Any, messages: list[dict[str, Any]], max_tokens: int = 64000,
                 tools: list[dict[str, Any]] | None = None, effort: str | None = None) -> Any:
        """Run to completion and return the final message (handles pause_turn)."""
        messages = list(messages)
        content: list[Any] = []
        try:
            for _ in range(6):
                with self._stream(self._params(system, messages, max_tokens, tools=tools, effort=effort)) as stream:
                    msg = stream.get_final_message()
                content.extend(msg.content)
                if msg.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": msg.content})
                    continue
                self._check(msg)
                msg.content = content
                return msg
            raise ClaudeError("Claude paused too many times while searching.")
        except anthropic.AnthropicError as e:
            raise self._wrap(e) from e

    def json(self, system: Any, messages: list[dict[str, Any]], schema: dict[str, Any],
             max_tokens: int = 32000, effort: str | None = None) -> dict[str, Any]:
        """Structured output constrained to a JSON schema."""
        fmt = {"type": "json_schema", "schema": schema}
        try:
            with self._stream(self._params(system, messages, max_tokens, fmt=fmt, effort=effort)) as stream:
                msg = stream.get_final_message()
        except anthropic.AnthropicError as e:
            raise self._wrap(e) from e
        self._check(msg)
        text = self.text_of(msg)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Claude returned invalid JSON: {e}") from e


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Helper for strict JSON schemas."""
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


STR = {"type": "string"}
INT = {"type": "integer"}


def arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def cached(text: str) -> list[dict[str, Any]]:
    """A system prompt block marked for prompt caching."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


ProgressFn = Callable[[str, float], None]
