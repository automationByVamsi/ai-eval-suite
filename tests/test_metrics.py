"""LLM judges: engine choice, skip / error handling, and DeepEval through a fake CORTEX gateway."""

from conftest import ROOT

from src.core import results
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

def _fake_devkit_and_pegasus(monkeypatch, client):
    """Install a fake `cortex` DevKit module and a fake Pegasus adapter; returns get_model's kwargs."""
    import sys
    import types

    from src.clients import cortex_client
    seen = {}
    adapters = types.SimpleNamespace(get_model=lambda **kwargs: seen.update(kwargs) or "pegasus-llm")
    monkeypatch.setitem(sys.modules, "cortex", types.SimpleNamespace(Client=lambda **kw: client))
    monkeypatch.setitem(sys.modules, "pegasus", types.ModuleType("pegasus"))
    monkeypatch.setitem(sys.modules, "pegasus.utils", types.SimpleNamespace(adapters=adapters))
    monkeypatch.setitem(sys.modules, "pegasus.utils.adapters", adapters)
    for name in ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH",
                 "CORTEX_DEVKIT_CHAT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    monkeypatch.setenv("PEGASUS_CORTEX_MODEL", "gemini-2.5-flash")
    cortex_client._shared_devkit_client.cache_clear()
    cortex_client._pegasus_model.cache_clear()
    return seen


def test_pegasus_uses_the_devkit_sign_in_as_its_key(monkeypatch):
    """A DevKit client that signs with an httpx auth flow (the token is added per request)."""
    import httpx

    from src.clients import cortex_client

    class SsoAuth(httpx.Auth):
        def auth_flow(self, request):
            request.headers["Authorization"] = "Bearer jwt-from-cx-auth-login"
            yield request

    client = httpx.Client(base_url="https://cortex.lloydsbanking.cloud/api", auth=SsoAuth())
    seen = _fake_devkit_and_pegasus(monkeypatch, client)
    try:
        assert cortex_client.pegasus_can_authenticate()                 # no CORTEX_API_KEY needed
        assert cortex_client.pegasus_llm() == "pegasus-llm"
    finally:
        cortex_client._shared_devkit_client.cache_clear()
        cortex_client._pegasus_model.cache_clear()
    assert seen["api_key"] == "jwt-from-cx-auth-login"
    assert seen["base_url"] == "https://cortex.lloydsbanking.cloud/api/v1"   # Pegasus adds /chat/completions
    assert seen["model_name"] == "gemini-2.5-flash" and seen["adapter"] == "cortex_api"


def test_devkit_token_from_a_fixed_header(monkeypatch):
    """A DevKit client that carries the token as a default header."""
    import httpx

    from src.clients import cortex_client
    client = httpx.Client(base_url="https://cortex-int.lloydsbanking.cloud/api/v1",
                          headers={"Authorization": "Bearer abc"})
    _fake_devkit_and_pegasus(monkeypatch, client)
    try:
        assert cortex_client.devkit_token() == "abc"
        assert cortex_client.devkit_api_base() == "https://cortex-int.lloydsbanking.cloud/api/v1"
    finally:
        cortex_client._shared_devkit_client.cache_clear()


def test_pegasus_engine_is_chosen_in_devkit_mode_without_a_key(monkeypatch):
    monkeypatch.setattr(judges, "pegasus_installed", lambda: True)
    for name in ("CORTEX_API_KEY", "CORTEX_CLIENT_ID", "CORTEX_CLIENT_SECRET", "PEGASUS_CERT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CORTEX_AUTH", "devkit")
    assert judges.pick_engine(definition("relevance", {})) == "pegasus"
