"""Unit tests for .env expansion helpers (no network)."""

import os

from src.core.env import expand_env, expand_env_string


def test_expand_env_string_default_and_override(monkeypatch):
    monkeypatch.delenv("DEMO_VAR", raising=False)
    assert expand_env_string("${DEMO_VAR:-fallback}") == "fallback"
    monkeypatch.setenv("DEMO_VAR", "from-env")
    assert expand_env_string("${DEMO_VAR:-fallback}") == "from-env"


def test_expand_env_nested_dict(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_URL_LOCAL", "http://127.0.0.1:8080")
    data = {
        "config": {
            "base_url": "${KNOWLEDGE_BASE_URL_LOCAL:-http://localhost:8080}",
            "app_name": "${KNOWLEDGE_APP_NAME_LOCAL:-knowledge_agent}",
            "timeout_s": 180,
            "verify_tls": False,
        }
    }
    out = expand_env(data)
    assert out["config"]["base_url"] == "http://127.0.0.1:8080"
    assert out["config"]["app_name"] == "knowledge_agent"
    assert out["config"]["timeout_s"] == 180
    assert out["config"]["verify_tls"] is False


def test_agents_yaml_resolves_local_defaults(monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_BASE_URL_LOCAL", raising=False)
    # Avoid picking up a developer .env for this assertion.
    monkeypatch.setenv("KNOWLEDGE_BASE_URL_LOCAL", "http://localhost:8080")
    from src.core.config import load_agents_config

    agents = load_agents_config("configs/agents.yaml")
    assert "knowledge_agent_local" in agents
    assert "knowledge_agent_replay" in agents
    local = agents["knowledge_agent_local"]["config"]
    assert local["base_url"] == "http://localhost:8080"
    assert local["app_name"] == "knowledge_agent"
    assert local["verify_tls"] is False
    assert agents["knowledge_agent_replay"]["type"] == "replay"
