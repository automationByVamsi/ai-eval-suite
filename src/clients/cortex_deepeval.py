"""
DeepEval LLM adapter backed by CORTEX.

Mirrors working factfind/ai-evals/core/cortex_llm.py (CortexLLM):
  - generate(prompt, schema=None) with optional JSON→schema parse
  - a_generate delegates to generate
"""

from __future__ import annotations

import json

from deepeval.models import DeepEvalBaseLLM

from src.clients.cortex_client import CortexClient


class CortexDeepEvalLLM(DeepEvalBaseLLM):
    def __init__(self, cortex_client: CortexClient):
        self.cortex_client = cortex_client
        super().__init__()

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return self.cortex_client.model

    def generate(self, prompt: str, schema=None):
        response = self.cortex_client.generate(prompt)
        if schema is not None:
            try:
                return schema(**json.loads(response))
            except Exception:  # noqa: BLE001 - DeepEval falls back to raw string
                pass
        return response

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)
