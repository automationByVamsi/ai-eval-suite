"""
DeepEval LLM adapter backed by CORTEX.

DeepEval's synthesizer calls:
  generate(prompt, schema=Response)  → expects object with `.response`
Judges often call:
  generate(prompt, schema=SomePydanticModel) → expects parsed model
  generate(prompt) → plain str is fine
"""

from __future__ import annotations

import json
import re
from typing import Any

from deepeval.models import DeepEvalBaseLLM

from src.clients.cortex_client import CortexClient


def _strip_markdown_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
    return cleaned.strip()


class CortexDeepEvalLLM(DeepEvalBaseLLM):
    def __init__(self, cortex_client: CortexClient):
        self.cortex_client = cortex_client
        super().__init__()

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return self.cortex_client.model

    def generate(self, prompt: str, schema: Any = None):
        raw = self.cortex_client.generate(prompt)
        if schema is None:
            return raw
        return self._coerce_schema(raw, schema)

    async def a_generate(self, prompt: str, schema: Any = None):
        return self.generate(prompt, schema)

    def _coerce_schema(self, raw: str, schema: Any) -> Any:
        """
        Map CORTEX text into the pydantic schema DeepEval asked for.

        Order:
          1) parse JSON object into schema
          2) if schema is Response-like ({response: str}), wrap plain text
          3) TypeError → DeepEval synthesizer falls back to generate(prompt)
        """
        text = _strip_markdown_fence(raw)

        for candidate in (text, raw):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return schema(**data)
            except Exception:  # noqa: BLE001
                pass

        fields = getattr(schema, "model_fields", None)
        if isinstance(fields, dict) and set(fields.keys()) == {"response"}:
            return schema(response=text or raw)

        # Synthesizer catches TypeError and retries without schema.
        raise TypeError(
            f"CORTEX output could not be coerced into {getattr(schema, '__name__', schema)}"
        )
