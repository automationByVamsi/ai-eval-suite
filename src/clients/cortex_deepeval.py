"""
Wraps CortexClient so every DeepEval metric and the Synthesizer use CORTEX
as their judge model transparently. This is the entire "no OpenAI key
required" trick: DeepEval only ever talks to DeepEvalBaseLLM, and this class
is our implementation of that interface backed by CORTEX.
"""

from deepeval.models import DeepEvalBaseLLM

from src.clients.cortex_client import CortexClient


class CortexDeepEvalLLM(DeepEvalBaseLLM):
    def __init__(self, cortex_client: CortexClient):
        self.cortex_client = cortex_client
        super().__init__()

    def load_model(self):
        return self.cortex_client

    def generate(self, prompt: str) -> str:
        return self.cortex_client.generate(prompt)

    async def a_generate(self, prompt: str) -> str:
        # CortexClient is a plain sync requests client; DeepEval's async path
        # just calls straight through. Swap for a real async client later if
        # judge-call latency ever becomes the bottleneck.
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return f"cortex:{self.cortex_client.model}"
