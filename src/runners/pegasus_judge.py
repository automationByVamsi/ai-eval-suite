"""Minimal Pegasus judge calls — same pattern as evaluations/evaluate_Faithfulness.py."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from src.metrics.base_metric import resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase

# Catalog mode → Pegasus metric method=
_MODE_TO_METHOD = {
    "pegasus": "pegasus",
    "pegasus_ragas": "ragas",
    "pegasus_deepeval": "deepeval",
}

# AnswerCorrectness supports ragas + pegasus only (no deepeval).
_ANSWER_CORRECTNESS_METHODS = frozenset({"pegasus", "ragas"})


def run_pegasus_metric(
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
    *,
    cortex_client: Any = None,
) -> MetricResult:
    """Dispatch to the right Pegasus RAG metric based on catalog type/name."""
    mtype = str(cfg.get("type") or cfg.get("name") or "").strip().lower()
    name = str(cfg.get("name") or "").strip().lower()

    if mtype in {"answer_correctness", "correctness"} or "correctness" in name:
        return run_pegasus_answer_correctness(
            cfg, test_case, response, cortex_client=cortex_client
        )
    return run_pegasus_faithfulness(
        cfg, test_case, response, cortex_client=cortex_client
    )


def run_pegasus_faithfulness(
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
    *,
    cortex_client: Any = None,
) -> MetricResult:
    """answer vs retrieved_contexts (does not use expected_answer)."""
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
        return _result_from_pegasus(name, threshold, metric.evaluate(data))
    except Exception as exc:  # noqa: BLE001
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason=f"Pegasus metric errored: {exc}",
        )


def run_pegasus_answer_correctness(
    cfg: dict[str, Any],
    test_case: TestCase,
    response: AgentResponse,
    *,
    cortex_client: Any = None,
) -> MetricResult:
    """
    Agent answer vs ground-truth reference_answer.

    Pegasus AnswerCorrectness supports method=pegasus|ragas only (not deepeval).
    Dataset columns: answer, reference_answer.
    """
    name = str(cfg.get("name") or "answer_correctness")
    threshold = float(cfg.get("threshold", 0.7))
    mode = str(cfg.get("mode") or "pegasus").strip().lower()
    method = _MODE_TO_METHOD.get(mode, "pegasus")
    if method not in _ANSWER_CORRECTNESS_METHODS:
        # Docs: no deepeval method for Answer Correctness — coerce to pegasus.
        method = "pegasus"

    answer = str(
        resolve_field(cfg.get("actual_source") or "answer", test_case, response) or ""
    )
    question = str(
        resolve_field(cfg.get("input_source") or "question", test_case, response) or ""
    )
    reference = resolve_field(
        cfg.get("expected_source") or "expected_answer", test_case, response
    )
    if not reference:
        reference = (response.metadata or {}).get("reference_answer") or (
            response.metadata or {}
        ).get("expected_answer")
    reference = str(reference or "").strip()
    if not reference:
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason="Skipped: no reference_answer / expected_answer for Answer Correctness.",
        )
    if not question.strip():
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason="Skipped: no question for Answer Correctness (pegasus method).",
        )

    try:
        from pegasus.metrics.rag import AnswerCorrectness  # type: ignore

        llm = _build_llm(cortex_client)
        metric = AnswerCorrectness(llm=llm, method=method, threshold=threshold)
        # pegasus method requires: answer, reference_answer, question
        # ragas method requires: answer, reference_answer (question still safe to include)
        data = pd.DataFrame(
            [
                {
                    "question": question,
                    "answer": answer,
                    "reference_answer": reference,
                }
            ]
        )
        return _result_from_pegasus(name, threshold, metric.evaluate(data))
    except Exception as exc:  # noqa: BLE001
        return MetricResult(
            name=name,
            score=0.0,
            threshold=threshold,
            passed=False,
            reason=f"Pegasus metric errored: {exc}",
        )


def _result_from_pegasus(
    name: str, threshold: float, results: dict[str, Any]
) -> MetricResult:
    score = float(results.get("score") or 0.0)
    passed = bool(results.get("passed", score >= threshold))
    reason = _reason_from_pegasus_results(results)
    if not reason or _is_score_only_reason(reason):
        # Prefer LLM reasoning; if missing, still explain pass/fail vs threshold.
        if passed:
            reason = f"{reason + ' — ' if reason else ''}score {score:.2f} ≥ threshold {threshold:.2f}"
        else:
            reason = (
                f"{reason + ' — ' if reason else ''}"
                f"score {score:.2f} < threshold {threshold:.2f} "
                f"(answer did not match reference_answer closely enough)"
            )
    return MetricResult(
        name=name,
        score=score,
        threshold=threshold,
        passed=passed,
        reason=reason.strip(),
    )


def _reason_from_pegasus_results(results: dict[str, Any]) -> str:
    """Pull the best human-readable explanation from a Pegasus evaluate() dict."""
    # Faithfulness / AnswerCorrectness demos usually return reasoning: [str, ...]
    for key in ("reasoning", "reasons"):
        value = results.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if first and str(first).strip():
                return str(first).strip()
        elif isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("details", "score_details"):
        value = results.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _is_score_only_reason(text: str) -> bool:
    """True when the string is just a score banner with no explanation."""
    lowered = text.strip().lower()
    return (
        "score:" in lowered
        and "because" not in lowered
        and "reason" not in lowered
        and len(lowered) < 80
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
