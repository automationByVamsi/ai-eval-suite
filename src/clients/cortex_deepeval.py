"""
CORTEX adapter for DeepEval.

DeepEval calls this like a normal LLM:
  - generate(prompt)           → str
  - generate(prompt, schema=X) → instance of X (pydantic model)

The synthesizer (golden generation) specifically does:
  res = model.generate(prompt, schema=Response)   # Response has field: response: str
  text = res.response

So when CORTEX returns plain text (not JSON), we must wrap it as Response(response=text)
instead of returning a raw string — otherwise you get:
  AttributeError: 'str' object has no attribute 'response'
"""

from __future__ import annotations

import json
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel

from src.clients.cortex_client import CortexClient


def _strip_code_fence(text: str) -> str:
    """Remove ```json ... ``` wrappers that Gemini sometimes adds."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _to_schema(text: str, schema: type[BaseModel]) -> BaseModel:
    """
    Turn CORTEX text into the pydantic schema DeepEval asked for.

    Try JSON first. If that fails and the schema only has a `response` field
    (DeepEval's Response model), wrap the plain text.
    """
    cleaned = _strip_code_fence(text)

    # 1) Prefer real JSON: {"response": "..."} or {"score": 0.9, ...}
    for candidate in (cleaned, text):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return schema(**data)
        except Exception:
            pass

    # 2) Synthesizer Response model: only field is `response: str`
    field_names = set(getattr(schema, "model_fields", {}) or {})
    if field_names == {"response"}:
        return schema(response=cleaned or text)

    # 3) Let DeepEval retry without schema (it catches TypeError)
    raise TypeError(f"Cannot map CORTEX output to schema {schema.__name__}")


class CortexDeepEvalLLM(DeepEvalBaseLLM):
    """Thin DeepEval LLM that sends every prompt to CORTEX."""

    def __init__(self, cortex_client: CortexClient):
        self.cortex_client = cortex_client
        super().__init__()

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return self.cortex_client.model

    def generate(self, prompt: str, schema: Any = None):
        text = self.cortex_client.generate(prompt)
        if schema is None:
            return text
        return _to_schema(text, schema)

    async def a_generate(self, prompt: str, schema: Any = None):
        # CORTEX client is sync; DeepEval async path just reuses it.
        return self.generate(prompt, schema)
