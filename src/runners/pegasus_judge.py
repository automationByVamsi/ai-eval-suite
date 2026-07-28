"""Minimal Pegasus judge call — same shape as evaluations/evaluate_Faithfulness.py."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from src.metrics.base_metric import resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase

# Catalog mode → Faithfulness(method=...)
_MODE_TO_METHOD = {
    "pegasus": "pegasus",
    "pegasus_ragas": "ragas",
    "pegasus_deepeval": "deepeval",
}


def run_pegasus_faithfulness(
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
    *,
    cortex_client: Any = None,
) -> MetricResult:
    """
    Build a 1-row Pegasus DataFrame and call Faithfulness.evaluate(...).

    Expects prepare_for_judges (or equivalent) to have set Pegasus columns on
    response: question / answer / retrieved_contexts (or response.context).
    """
    name = str(cfg.get("name") or "faithfulness")
    threshold = float(cfg.get("threshold", 0.7))
    mode = str(cfg.get("mode") or "pegasus").strip().lower()
    method = _MODE_TO_METHOD.get(mode, "pegasus")

    question = str(
        resolve_field(cfg.get("input_source") or "question", test_case, response) or ""
    )
    answer = str(
        resolve_field(cfg.get("actual_source") or "answer", test_case, response) or ""
    )
    contexts = resolve_field(
        cfg.get("context_source") or "retrieval_context", test_case, response
    )
    if not isinstance(contexts, list) or not contexts:
        contexts = (response.metadata or {}).get("retrieved_contexts")
    if not isinstance(contexts, list) or not contexts:
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason="Skipped: no retrieved_contexts for Pegasus faithfulness.",
        )

    try:
        from pegasus.metrics.rag import Faithfulness  # type: ignore

        llm = _build_llm(cortex_client)
        metric = Faithfulness(llm=llm, method=method, threshold=threshold)
        data = pd.DataFrame(
            [
                {
                    "question": question,
                    "answer": answer,
                    "retrieved_contexts": [str(c) for c in contexts if str(c).strip()],
                }
            ]
        )
        results = metric.evaluate(data)
        score = float(results.get("score") or 0.0)
        return MetricResult(
            name=name,
            score=score,
            threshold=threshold,
            passed=bool(results.get("passed", score >= threshold)),
            reason=str(
                results.get("details")
                or (results.get("reasons") or [""])[0]
                or results.get("score_details")
                or ""
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason=f"Pegasus metric errored: {exc}",
        )


def _build_llm(cortex_client: Any):
    """
    Build a Pegasus LLM.

    Preferred (CorteX 2.0 developer route — Pegasus docs):
      CORTEX_BASE_URL + CORTEX_API_KEY + PEGASUS_CORTEX_MODEL

    Fallback (legacy Apigee / Istio):
      CORTEX_HOST + CORTEX_CLIENT_ID/SECRET or PEGASUS_CERT_PATH
    """
    from src.core.env import load_dotenv

    load_dotenv()

    from pegasus.utils.adapters import get_model  # type: ignore

    api_key = os.environ.get("CORTEX_API_KEY", "").strip()
    if api_key in {"your_api_key_here", "changeme", "TODO"}:
        api_key = ""
    # Prefer CorteX 2.0 base URL when set (Pegasus docs).
    base_url = (
        os.environ.get("CORTEX_BASE_URL", "").strip()
        or getattr(cortex_client, "base_url", None)
        or os.environ.get("CORTEX_HOST", "").strip()
        or None
    )
    model_name = (
        os.environ.get("PEGASUS_CORTEX_MODEL", "").strip()
        or os.environ.get("CORTEX_MODEL", "").strip()
        or getattr(cortex_client, "model", None)
        or "gemini-3.1-lite"
    )
    # Legacy Apigee models often need vertex_ai/ prefix; CorteX 2.0 API-key route does not.
    if not api_key and not str(model_name).startswith("vertex_ai/"):
        model_name = f"vertex_ai/{model_name}"

    client_id = os.environ.get("CORTEX_CLIENT_ID", "").strip()
    client_secret = os.environ.get("CORTEX_CLIENT_SECRET", "").strip()
    cert_path = (
        os.environ.get("PEGASUS_CERT_PATH", "").strip()
        or os.environ.get("CORTEX_CERT_PATH", "").strip()
    )

    kwargs: dict[str, Any] = {
        "adapter": "cortex_api",
        "model_type": "llm",
        "model_name": model_name,
        "ssl_verify": False,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if client_id:
        kwargs["client_id"] = client_id
    if client_secret:
        kwargs["client_secret"] = client_secret
    if cert_path:
        kwargs["cert_path"] = cert_path

    if not (api_key or cert_path or (client_id and client_secret)):
        raise ValueError(
            "Pegasus CORTEX auth missing. For CorteX 2.0 set CORTEX_BASE_URL + "
            "CORTEX_API_KEY (+ optional PEGASUS_CORTEX_MODEL) in .env"
        )

    try:
        return get_model(**kwargs)
    except TypeError:
        kwargs.pop("ssl_verify", None)
        return get_model(**kwargs)
