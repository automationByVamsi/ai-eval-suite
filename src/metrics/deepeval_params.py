"""DeepEval API shims across package versions."""

from __future__ import annotations

try:
    # deepeval >= ~3/4
    from deepeval.test_case import SingleTurnParams as _Params
except ImportError:  # pragma: no cover - older deepeval
    from deepeval.test_case import LLMTestCaseParams as _Params  # type: ignore

# Public alias used by GEval metrics in this repo.
SingleTurnParams = _Params
