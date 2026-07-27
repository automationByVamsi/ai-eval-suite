"""CortexDeepEvalLLM schema coercion (no live CORTEX)."""

from __future__ import annotations

from pydantic import BaseModel

from src.clients.cortex_deepeval import CortexDeepEvalLLM, _strip_markdown_fence


class _FakeCortex:
    model = "fake"

    def __init__(self, text: str):
        self._text = text

    def generate(self, prompt: str) -> str:
        return self._text


class Response(BaseModel):
    response: str


class Score(BaseModel):
    score: float
    reason: str


def test_plain_string_when_no_schema():
    llm = CortexDeepEvalLLM(_FakeCortex("hello"))  # type: ignore[arg-type]
    assert llm.generate("p") == "hello"


def test_response_schema_wraps_plain_text():
    """Synthesizer path: schema=Response, model returns prose not JSON."""
    llm = CortexDeepEvalLLM(_FakeCortex("What formats are available?"))  # type: ignore[arg-type]
    out = llm.generate("p", schema=Response)
    assert isinstance(out, Response)
    assert out.response == "What formats are available?"


def test_json_schema_parses():
    llm = CortexDeepEvalLLM(  # type: ignore[arg-type]
        _FakeCortex('{"score": 0.9, "reason": "ok"}')
    )
    out = llm.generate("p", schema=Score)
    assert out.score == 0.9
    assert out.reason == "ok"


def test_fenced_json_parses():
    raw = '```json\n{"score": 0.5, "reason": "meh"}\n```'
    llm = CortexDeepEvalLLM(_FakeCortex(raw))  # type: ignore[arg-type]
    out = llm.generate("p", schema=Score)
    assert out.score == 0.5


def test_strip_fence():
    assert _strip_markdown_fence("```\nhi\n```") == "hi"
