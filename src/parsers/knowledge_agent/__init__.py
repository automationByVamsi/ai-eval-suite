"""
Knowledge Agent parsers — thin views on top of shared adk_parser.

Preferred judge path:
  prepare_response(case, response) → prepare_sample(case, response) → evaluate(...)
"""

from src.parsers.knowledge_agent.view import (
    KnowledgeAgentView,
    enrich,
    extract,
    prepare_response,
)

__all__ = ["KnowledgeAgentView", "extract", "enrich", "prepare_response"]
