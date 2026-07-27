"""Offline synthesizer + goldens package tests (no live Athena / CORTEX)."""

from __future__ import annotations

import json
from pathlib import Path

from src.clients.athena_client import load_page_fixture
from src.synthesizer.clean import athena_payload_to_text, html_to_text
from src.synthesizer.goldens.evolution import build_evolution_config
from src.synthesizer.goldens.filtration import load_filtration_settings
from src.synthesizer.goldens.styling import build_styling_config, parse_style_md
from src.synthesizer.pipeline import KnowledgeAgentSynthesizer, load_synth_config

FIXTURE = Path("8708-response.json")
AGENT_DIR = Path("configs/synthesizers/knowledge_agent")


def test_html_to_text_strips_tags_keeps_headings():
    html = "<div><h2>Overview</h2><p>Hello&nbsp;world</p><ul><li>One</li><li>Two</li></ul></div>"
    text = html_to_text(html)
    assert "Overview" in text
    assert "Hello world" in text
    assert "One" in text
    assert "<h2>" not in text


def test_athena_fixture_cleans_to_readable_text():
    payload = load_page_fixture(FIXTURE)
    title, text = athena_payload_to_text(payload)
    assert "Accessible Format" in title
    assert "Braille" in text
    assert "<div" not in text
    assert len(text) > 500


def test_synth_config_has_styles_section():
    cfg = load_synth_config("knowledge_agent")
    assert "fetch" not in cfg and "run" not in cfg
    assert cfg["instruction_file"] == "instructions.md"
    assert cfg["evolution_file"] == "evolution.yaml"
    assert cfg["filtration_file"] == "filtration.yaml"
    names = [s["name"] for s in cfg["styles"]]
    assert "simple_query" in names
    assert "complex_query" in names
    assert names  # at least one style configured


def test_style_files_parse_and_build_styling_config():
    path = AGENT_DIR / "styles" / "simple_query.md"
    sections = parse_style_md(path)
    assert sections["input_format"]
    assert sections["expected_output_format"]

    shared = (AGENT_DIR / "instructions.md").read_text()
    cfg = build_styling_config(path, shared_instructions=shared)
    assert cfg.scenario and "Shared instructions" in cfg.scenario
    assert cfg.task
    assert cfg.input_format
    assert cfg.expected_output_format


def test_evolution_and_filtration_builders():
    evo = build_evolution_config(AGENT_DIR / "evolution.yaml")
    assert evo is not None
    assert evo.num_evolutions >= 1

    settings = load_filtration_settings(AGENT_DIR / "filtration.yaml")
    assert settings is not None
    assert settings["synthetic_input_quality_threshold"] == 0.5
    assert settings["max_quality_retries"] == 3


def test_prepare_page_from_fixture(tmp_path):
    synth = KnowledgeAgentSynthesizer("knowledge_agent", fixture_path=FIXTURE)
    synth.source_docs_dir = tmp_path / "source_docs"
    path = synth.prepare_page("8708")
    saved = json.loads(path.read_text())
    assert saved["page_id"] == "8708"
    assert "Braille" in saved["content"]
    assert saved.get("revision") == "3"
