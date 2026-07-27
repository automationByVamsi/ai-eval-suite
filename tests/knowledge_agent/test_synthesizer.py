"""Offline synthesizer helpers — HTML clean + Athena fixture (no live network)."""

from __future__ import annotations

import json
from pathlib import Path

from src.clients.athena_client import load_page_fixture
from src.synthesizer.clean import athena_payload_to_text, html_to_text

FIXTURE = Path("8708-response.json")


def test_html_to_text_strips_tags_keeps_headings():
    html = "<div><h2>Overview</h2><p>Hello&nbsp;world</p><ul><li>One</li><li>Two</li></ul></div>"
    text = html_to_text(html)
    assert "Overview" in text
    assert "Hello world" in text
    assert "One" in text
    assert "<h2>" not in text
    assert "&nbsp;" not in text


def test_athena_fixture_cleans_to_readable_text():
    assert FIXTURE.is_file(), "expected 8708-response.json in repo root"
    payload = load_page_fixture(FIXTURE)
    title, text = athena_payload_to_text(payload)

    assert "Accessible Format" in title
    assert "Braille" in text
    assert "Large Print" in text
    assert "Easy Read" in text
    assert "<div" not in text
    assert "mt-section" not in text
    # TOC object in body[] should not dump raw JSON
    assert '"@target"' not in text
    assert len(text) > 500


def test_synth_config_loads():
    from src.synthesizer.pipeline import load_synth_config

    cfg = load_synth_config("knowledge_agent")
    assert cfg["agent_name"] == "knowledge_agent"
    assert "8708" in [str(p) for p in cfg["fetch"]["page_ids"]]
    assert cfg["generation"]["max_goldens_per_context"] >= 1
    assert cfg["run"]["data_suite"] == "golden"


def test_fixture_mode_fetch_page(tmp_path, monkeypatch):
    """generate path can use local fixture without calling Athena."""
    from src.synthesizer import pipeline as pl

    raw = pl._fetch_page(
        "8708",
        {
            "use_fixture": True,
            "fixture_path": str(FIXTURE),
        },
    )
    assert raw.get("@title")
    title, text = athena_payload_to_text(raw)
    out = pl._save_cleaned_doc(
        agent="knowledge_agent",
        page_id="8708",
        title=title,
        text=text,
        raw=raw,
    )
    assert out.is_file()
    saved = json.loads(out.read_text())
    assert saved["page_id"] == "8708"
    assert "Braille" in saved["content"]
