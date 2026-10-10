"""LLM judges: engine choice, skip / error handling, and DeepEval through a fake CORTEX gateway."""

import pytest
from conftest import ROOT

from src.core import results
from src.core.exceptions import ConfigError
from src.metrics import judges
from src.metrics.library import definition, library

RUBRIC = str(ROOT / "agents/knowledge_agent/rubrics/intent_preservation.md")


def test_metric_library_is_valid():
    assert {"relevance", "faithfulness", "correctness"} <= set(library())


def test_judge_skips_when_the_case_lacks_the_data():
    result = judges.run_judge("correctness", {}, {"question": "q", "answer": "a", "expected_answer": ""})
    assert result.status == results.SKIP
    assert "expected_answer" in result.reason


def test_judge_field_can_point_at_a_parser_field(monkeypatch):
    seen = {}

    def fake_score(name, metric, values, threshold):
        seen.update(values)
        return 0.9, "fine"

    monkeypatch.setattr(judges, "score_with_deepeval", fake_score)
    spec = {"rubric": RUBRIC, "answer": "rewritten_query"}
    result = judges.run_judge("intent", spec, {"question": "q", "answer": "final", "rewritten_query": "rq"})
    assert result.status == results.PASS and seen["answer"] == "rq"


def test_judge_crash_is_an_error_not_a_low_score(monkeypatch):
    def boom(*args):
        raise TimeoutError("gateway timeout")

    monkeypatch.setattr(judges, "score_with_deepeval", boom)
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    result = judges.run_judge("relevance", {}, {"question": "q", "answer": "a"})
    assert result.status == results.ERROR and result.score is None


def test_engine_rule(monkeypatch):
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    monkeypatch.setattr(judges, "pegasus_has_credentials", lambda: True)
    assert judges.pick_engine(definition("relevance", {})) == "pegasus"
    assert judges.pick_engine(definition("summarization", {})) == "deepeval"     # not in Pegasus
    assert judges.pick_engine(definition("mine", {"rubric": RUBRIC})) == "deepeval"
    assert judges.pick_engine(definition("relevance", {"engine": "deepeval"})) == "deepeval"
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    assert judges.pick_engine(definition("relevance", {})) == "deepeval"         # fallback
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    monkeypatch.setattr(judges, "pegasus_has_credentials", lambda: False)        # e.g. DevKit only, no key
    assert judges.pick_engine(definition("relevance", {})) == "deepeval"


def test_deepeval_judges_run_through_cortex(fake_cortex):
    fields = {"question": "How do I get VPN?", "answer": "Raise a ticket.", "contexts": ["Raise a ticket."],
              "expected_answer": "Raise a ticket."}
    for name in ("relevance", "faithfulness", "correctness"):
        result = judges.run_judge(name, {}, fields)
        assert result.status == results.PASS, (name, result.reason)
        assert result.engine == "deepeval"
    assert judges.run_judge("intent", {"rubric": RUBRIC}, fields).status == results.PASS

    last = fake_cortex[-1]
    assert last["x-lbg-origin-client-id"] == "test"
    assert last["authorization"] == "Bearer key-123"     # CorteX 2.0 API key


def test_a_nan_score_is_an_error_not_a_fail(monkeypatch):
    monkeypatch.setattr(judges, "score_with_deepeval", lambda *args: (float("nan"), ""))
    monkeypatch.setattr(judges, "pegasus_installed", lambda: False)
    result = judges.run_judge("relevance", {}, {"question": "q", "answer": "a"})
    assert result.status == results.ERROR and result.score is None


def test_devkit_mode_uses_cortex_client_instead_of_the_api_key(monkeypatch):
    """CORTEX_AUTH=devkit: calls go through cortex.Client() (fake here); no host, client id or key needed."""
    import sys
    import types

    from src.clients import cortex_client
    calls = []

    class FakeResponse:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class FakeDevkitClient:
        base_url = "https://cortex.lloydsbanking.cloud/api/"      # what the real DevKit client points at

        def __init__(self, timeout=None):
            pass

        def post(self, path, json):
            calls.append((path, json["model"]))
            if len(calls) == 1:
                return FakeResponse(503, {})                       # busy: retried
            return FakeResponse(200, {"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setitem(sys.modules, "cortex", types.SimpleNamespace(Client=FakeDevkitClient))
    monkeypatch.setattr(cortex_client.time, "sleep", lambda s: None)
    for name in ("CORTEX_HOST", "CORTEX_CLIENT_ID", "CORTEX_API_KEY", "CORTEX_DEVKIT_CHAT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    monkeypatch.setenv("CORTEX_MODEL", "vertex_ai/gemini-2.5-pro")
    cortex_client.deepeval_llm.cache_clear()
    try:
        assert cortex_client.deepeval_llm().generate("hi") == "OK"
    finally:
        cortex_client.deepeval_llm.cache_clear()
    assert calls == [("/v1/chat/completions", "vertex_ai/gemini-2.5-pro")] * 2     # not /api/api/v1/...


def test_devkit_mode_without_the_package_says_how_to_install(monkeypatch):
    import sys

    from src.clients import cortex_client
    from src.core.exceptions import JudgeConfigError
    monkeypatch.setitem(sys.modules, "cortex", None)                   # import cortex -> ImportError
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    cortex_client.deepeval_llm.cache_clear()
    try:
        import pytest
        with pytest.raises(JudgeConfigError, match="make setup"):
            cortex_client.deepeval_llm()
    finally:
        cortex_client.deepeval_llm.cache_clear()


def test_devkit_chat_path_follows_the_client_base_address():
    from types import SimpleNamespace

    from src.clients.cortex_client import _devkit_chat_path
    host = "https://cortex.lloydsbanking.cloud"
    assert _devkit_chat_path(SimpleNamespace(base_url=f"{host}/api")) == "/v1/chat/completions"
    assert _devkit_chat_path(SimpleNamespace(base_url=f"{host}/api/v1/")) == "/chat/completions"
    assert _devkit_chat_path(SimpleNamespace(base_url=host)) == "/api/v1/chat/completions"


# --- Pegasus through the CorteX DevKit (no API key) ------------------------------------------

def _fake_pegasus(monkeypatch, metric_calls=None):
    """A fake Pegasus: get_model records its arguments; rag.AnswerRelevancy scores 0.82."""
    import sys
    import types

    from src.clients import cortex_client
    seen = {}

    class AnswerRelevancy:
        def __init__(self, **kwargs):
            if metric_calls is not None:
                metric_calls.append(kwargs)

        def evaluate(self, frame, **kwargs):
            if metric_calls is not None:
                metric_calls.append(list(frame.columns))
                metric_calls.append(kwargs)
            return {"score": 0.82}

    adapters = types.SimpleNamespace(get_model=lambda **kwargs: seen.update(kwargs) or "pegasus-llm")
    rag = types.SimpleNamespace(AnswerRelevancy=AnswerRelevancy)
    monkeypatch.setitem(sys.modules, "pegasus", types.ModuleType("pegasus"))
    monkeypatch.setitem(sys.modules, "pegasus.utils", types.SimpleNamespace(adapters=adapters))
    monkeypatch.setitem(sys.modules, "pegasus.utils.adapters", adapters)
    monkeypatch.setitem(sys.modules, "pegasus.metrics", types.SimpleNamespace(rag=rag))
    monkeypatch.setitem(sys.modules, "pegasus.metrics.rag", rag)
    for name in ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH", "CORTEX_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PEGASUS_CORTEX_MODEL", "gemini-2.5-flash")
    cortex_client._pegasus_model.cache_clear()
    return seen


def test_pegasus_uses_its_own_devkit_support_like_the_knowledge_agent(monkeypatch):
    """Same get_model call as the Knowledge Agent's guardrails: cortex_v2 + auth_mode=devkit, no key."""
    from src.clients import cortex_client
    seen = _fake_pegasus(monkeypatch)
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    try:
        assert cortex_client.pegasus_can_authenticate()
        assert cortex_client.pegasus_llm() == "pegasus-llm"
    finally:
        cortex_client._pegasus_model.cache_clear()
    assert seen == {"adapter": "cortex_v2", "model_type": "llm", "auth_mode": "devkit", "cortex_env": "prd",
                    "model_name": "gemini-2.5-flash", "ssl_verify": False}


def test_pegasus_api_key_mode_is_unchanged(monkeypatch):
    from src.clients import cortex_client
    seen = _fake_pegasus(monkeypatch)
    monkeypatch.setenv("CORTEX_AUTH", "api_key")
    monkeypatch.setenv("CORTEX_HOST", "https://cortex.example/api/v1")
    monkeypatch.setenv("CORTEX_API_KEY", "k")
    try:
        cortex_client.pegasus_llm()
    finally:
        cortex_client._pegasus_model.cache_clear()
    assert seen["adapter"] == "cortex_api" and seen["api_key"] == "k" and "auth_mode" not in seen


def test_pegasus_metric_is_called_like_the_knowledge_agent_guardrails(monkeypatch):
    """Metric(llm=..., method=...) — no threshold (we apply it) — and evaluate(frame)["score"]."""
    calls = []
    _fake_pegasus(monkeypatch, calls)
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    try:
        result = judges.run_judge("relevance", {}, {"question": "q?", "answer": "a."})
    finally:
        from src.clients import cortex_client
        cortex_client._pegasus_model.cache_clear()
    assert (result.status, result.score, result.engine) == (results.PASS, 0.82, "pegasus")
    assert calls[0] == {"llm": "pegasus-llm", "method": "pegasus"}
    assert calls[1] == ["question", "answer", "retrieved_contexts"]
    assert calls[2] == {"temperature": 0.0}                     # metric_library.yaml judge_temperature


def test_pegasus_safety_hallucination_gets_separate_arguments(monkeypatch):
    """Safety metrics: evaluate(query=, text=, context=[...]) — no DataFrame, no method=; the page texts stay a list."""
    import sys
    import types
    calls = []
    _fake_pegasus(monkeypatch)

    class Hallucination:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def evaluate(self, **kwargs):
            calls.append(kwargs)
            return {"score": 0.89, "passed": True, "explanation": "Fully supported by the context.", "raw_score": 9.0}

    monkeypatch.setitem(sys.modules, "pegasus.metrics.safety", types.SimpleNamespace(Hallucination=Hallucination))
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    pages = ["Page 40345: open Customer Support Needs ...", "Page 40017: ..."]
    try:
        result = judges.run_judge("hallucination", {"threshold": 0.66},
                                  {"question": "How do I add a support need?", "answer": "Open ...", "contexts": pages})
        skipped = judges.run_judge("hallucination", {}, {"question": "q?", "answer": "a.", "contexts": []})
    finally:
        from src.clients import cortex_client
        cortex_client._pegasus_model.cache_clear()
    assert (result.status, result.score, result.engine) == (results.PASS, 0.89, "pegasus")
    assert result.reason == "Fully supported by the context. (raw score 9.0/10)"
    assert calls[0] == {"llm": "pegasus-llm"}                               # no method=: not a RAG metric
    assert calls[1] == {"query": "How do I add a support need?", "text": "Open ...", "context": pages,
                        "temperature": 0.0}
    assert skipped.status == results.SKIP                                  # no evidence pages: nothing to judge against


def test_metric_library_call_must_be_keywords(monkeypatch, tmp_path):
    from src.core import paths
    from src.metrics import library
    monkeypatch.setattr(paths, "METRIC_LIBRARY", tmp_path / "lib.yaml")
    try:
        (tmp_path / "lib.yaml").write_text("h: {needs: [question, answer], pegasus: H, call: frame}\n")
        _clear(library)
        with pytest.raises(ConfigError, match="call: can only be `keywords`"):
            library.library()
    finally:
        monkeypatch.undo()
        _clear(library)


def test_pegasus_metric_without_temperature_still_runs_with_a_warning(capsys):
    class OldMetric:                                            # evaluate() takes no temperature
        def evaluate(self, frame):
            return {"score": 0.5}

    judges._NO_TEMPERATURE.discard("OldMetric")
    assert judges._evaluate(OldMetric(), "frame", "OldMetric") == {"score": 0.5}
    assert judges._evaluate(OldMetric(), "frame", "OldMetric") == {"score": 0.5}
    assert capsys.readouterr().out.count("does not accept temperature") == 1   # warned once, not per case

    class Broken:
        def evaluate(self, frame, temperature=0.0):
            raise TypeError("bad frame")                        # a real error is not swallowed
    with pytest.raises(TypeError, match="bad frame"):
        judges._evaluate(Broken(), "frame", "Broken")


def test_judge_temperature_comes_from_metric_library(monkeypatch, tmp_path):
    from src.core import paths
    from src.metrics import library
    monkeypatch.setattr(paths, "METRIC_LIBRARY", tmp_path / "lib.yaml")
    try:
        for value, expected in [("judge_temperature: 0.3\n", 0.3), ("", 0.0)]:
            (tmp_path / "lib.yaml").write_text(value + "relevance: {needs: [question, answer], deepeval: X}\n")
            _clear(library)
            assert library.judge_temperature() == expected
            assert list(library.library()) == ["relevance"]      # the setting is not a metric
        (tmp_path / "lib.yaml").write_text("judge_temperature: hot\n")
        _clear(library)
        with pytest.raises(ConfigError, match="judge_temperature must be a number"):
            library.judge_temperature()
    finally:
        monkeypatch.undo()                                     # back to the real metric_library.yaml
        _clear(library)



def test_pegasus_engine_is_chosen_in_devkit_mode_without_a_key(monkeypatch):
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    for name in ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    assert judges.pick_engine(definition("relevance", {})) == "pegasus"


def _clear(library):
    for cached in (library._file, library.judge_temperature, library.library):
        cached.cache_clear()
