from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.registry import METRIC_REGISTRY
from src.metrics.base_metric import BaseMetric, resolve_field
from src.models.agent_response import AgentResponse
from src.models.metric_result import MetricResult
from src.models.test_case import TestCase


@METRIC_REGISTRY.register("pegasus_faithfulness")
class PegasusFaithfulnessMetric(BaseMetric):
    """Evaluate faithfulness via Pegasus using a one-row DataFrame per case."""

    def __init__(
        self,
        *args: Any,
        cortex_client=None,
        method: str = "pegasus",
        input_source: str = "question",
        actual_source: str = "answer",
        context_source: str = "retrieval_context",
        llm_adapter: str = "cortex_api",
        llm_model_type: str = "llm",
        api_key_env: str = "CORTEX_API_KEY",
        cert_path_env: str = "PEGASUS_CERT_PATH",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.cortex_client = cortex_client
        self.method = method
        self.input_source = input_source
        self.actual_source = actual_source
        self.context_source = context_source
        self.llm_adapter = llm_adapter
        self.llm_model_type = llm_model_type
        self.api_key_env = api_key_env
        self.cert_path_env = cert_path_env

    def evaluate(self, test_case: TestCase, response: AgentResponse) -> MetricResult:
        context = resolve_field(self.context_source, test_case, response)
        if not isinstance(context, list) or not context:
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason="Skipped: no retrieval_context available for Pegasus faithfulness.",
            )

        try:
            metric_cls, get_model = self._import_pegasus()
            llm = self._build_llm(get_model)
            metric = (
                metric_cls(llm=llm, method=self.method, threshold=self.threshold)
                if llm is not None
                else metric_cls(method=self.method, threshold=self.threshold)
            )
            question = str(resolve_field(self.input_source, test_case, response) or "")
            answer = str(resolve_field(self.actual_source, test_case, response) or "")
            dataset = pd.DataFrame(
                [
                    {
                        "question": question,
                        "answer": answer,
                        "retrieved_contexts": [str(c) for c in context if str(c).strip()],
                    }
                ]
            )
            result = metric.evaluate(dataset)
            score = self._score_from_result(result)
            passed = bool(result.get("passed", score >= self.threshold))
            reason = self._reason_from_result(result)
            return MetricResult(
                name=self.name,
                score=score,
                threshold=self.threshold,
                passed=passed,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001 - keep one bad optional backend isolated
            return MetricResult(
                name=self.name,
                score=0.0,
                threshold=self.threshold,
                passed=False,
                reason=f"Pegasus metric errored: {exc}",
            )

    def _import_pegasus(self):
        try:
            from pegasus.metrics.rag import Faithfulness  # type: ignore[import-not-found]
            from pegasus.utils.adapters import get_model  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            self._maybe_add_pegasus_path()
            from pegasus.metrics.rag import Faithfulness  # type: ignore[import-not-found]
            from pegasus.utils.adapters import get_model  # type: ignore[import-not-found]
        return Faithfulness, get_model

    def _maybe_add_pegasus_path(self) -> None:
        for env_name in ("PEGASUS_SRC_PATH", "PEGASUS_REPO_PATH"):
            raw = os.environ.get(env_name, "").strip()
            if not raw:
                continue
            base = Path(raw).expanduser()
            candidates = [base]
            if env_name == "PEGASUS_REPO_PATH":
                candidates.insert(0, base / "src")
            for candidate in candidates:
                text = str(candidate)
                if candidate.exists() and text not in sys.path:
                    sys.path.insert(0, text)

    def _build_llm(self, get_model):
        if self.method == "ragas":
            return None
        kwargs = {
            "adapter": self.llm_adapter,
            "model_type": self.llm_model_type,
        }
        if self.cortex_client is not None:
            kwargs["model_name"] = getattr(self.cortex_client, "model", None)
            kwargs["base_url"] = getattr(self.cortex_client, "base_url", None)
        api_key = os.environ.get(self.api_key_env, "").strip()
        cert_path = os.environ.get(self.cert_path_env, "").strip()
        if api_key:
            kwargs["api_key"] = api_key
        if cert_path:
            kwargs["cert_path"] = cert_path
        filtered = {k: v for k, v in kwargs.items() if v not in (None, "")}
        try:
            sig = inspect.signature(get_model)
        except (TypeError, ValueError):
            return get_model(**filtered)
        accepted = {
            name: value
            for name, value in filtered.items()
            if name in sig.parameters
        }
        return get_model(**accepted)

    def _score_from_result(self, result: dict[str, Any]) -> float:
        raw = result.get("score", 0.0)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def _reason_from_result(self, result: dict[str, Any]) -> str:
        details = result.get("details")
        if details:
            return str(details)
        reasons = result.get("reasons")
        if isinstance(reasons, list) and reasons:
            return str(reasons[0])
        score_details = result.get("score_details")
        if score_details:
            return str(score_details)
        return ""
