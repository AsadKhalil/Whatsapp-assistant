"""One Chat Completions code path for OpenAI, Gemini and Ollama Cloud, plus speech-to-text."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import OpenAI

from app.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: Any = None  # appended to the conversation before the tool results


class LLM:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._chat = OpenAI(api_key=settings.llm_api_key or "missing", base_url=settings.llm_base_url or None,
                            timeout=30, max_retries=1, http_client=http_client)
        self._stt = OpenAI(api_key=settings.stt_api_key or settings.llm_api_key or "missing",
                           base_url=settings.stt_base_url or None, timeout=60, max_retries=1, http_client=http_client)
        self.model = settings.llm_model
        self.stt_model = settings.stt_model
        # OpenAI accepts tools in Chat Completions only with reasoning off; Gemini 3 and Ollama take no value.
        effort = settings.llm_reasoning_effort or ("none" if not settings.llm_base_url else "")
        self._extra = {"reasoning_effort": effort} if effort else {}

    def complete(self, messages: list, tools: list[dict]) -> ModelReply:
        response = self._chat.chat.completions.create(model=self.model, messages=messages, tools=tools, **self._extra)
        message = response.choices[0].message
        calls = []
        for i, tc in enumerate(message.tool_calls or []):
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(tc.id or f"call_{i}", tc.function.name,
                                  arguments if isinstance(arguments, dict) else {}))
        # Hand back the SDK object itself: it keeps provider extras such as Gemini's thought signatures.
        return ModelReply(text=(message.content or "").strip(), tool_calls=calls, message=message)

    def transcribe(self, audio: bytes) -> str:
        # The file name decides the format: WhatsApp's ".oga" is rejected, ".ogg" is accepted.
        result = self._stt.audio.transcriptions.create(model=self.stt_model, file=("voice.ogg", audio, "audio/ogg"))
        return result.text.strip()
