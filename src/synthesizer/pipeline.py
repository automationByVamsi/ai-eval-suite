"""
Knowledge Agent synthesizer — fetch Athena → clean → save source docs.

Golden generation lives in src/synthesizer/goldens/ (separate package).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.clients.athena_client import AthenaClient, load_page_fixture
from src.core.config import load_yaml
from src.synthesizer.clean import athena_payload_to_text
from src.synthesizer.goldens.generator import generate_goldens_from_docs

_DEFAULT_ATHENA_BASE = (
    "https://web203-int-ew2.c2.test.lbgcp.cloud/cct1/sjlab2/athena-management-api"
)


def load_synth_config(agent: str, configs_dir: str | Path = "configs") -> dict[str, Any]:
    path = Path(configs_dir) / "synthesizers" / agent / "config.yaml"
    return load_yaml(path)


def agent_config_dir(agent: str, configs_dir: str | Path = "configs") -> Path:
    return Path(configs_dir) / "synthesizers" / agent


class KnowledgeAgentSynthesizer:
    """
    Prepare Athena pages as cleaned source docs, then generate goldens.

      fetch_content_from_athena(page_id)
      clean_content(payload)
      save_cleaned_data(...)
      generate_goldens()   # delegates to synthesizer.goldens
    """

    def __init__(
        self,
        agent: str = "knowledge_agent",
        *,
        configs_dir: str | Path = "configs",
        athena_base_url: str | None = None,
        fixture_path: str | Path | None = None,
    ):
        self.agent = agent
        self.configs_dir = Path(configs_dir)
        self.agent_dir = agent_config_dir(agent, configs_dir)
        self.cfg = load_synth_config(agent, configs_dir)
        self.fixture_path = Path(fixture_path) if fixture_path else None

        self.source_docs_dir = Path(
            self.cfg.get("source_docs_dir") or f"data/{agent}/source_docs"
        )
        self.output_dir = Path(
            self.cfg.get("output_dir") or f"testdata/{agent}/golden"
        )

        base = athena_base_url or os.environ.get("ATHENA_BASE_URL") or _DEFAULT_ATHENA_BASE
        self._athena = AthenaClient(
            base_url=base,
            verify_tls=False,
            timeout_s=60,
            retries=1,
            client_id_env="ATHEN_ID",
        )

    def fetch_content_from_athena(self, page_id: str) -> dict[str, Any]:
        """Live Athena GET, or load fixture_path when set (offline)."""
        if self.fixture_path is not None:
            return load_page_fixture(self.fixture_path)
        return self._athena.get_page_contents(str(page_id))

    def clean_content(self, athena_payload: dict[str, Any]) -> tuple[str, str]:
        """Return (title, readable_text)."""
        return athena_payload_to_text(athena_payload)

    def save_cleaned_data(
        self,
        page_id: str,
        title: str,
        text: str,
        raw: dict[str, Any] | None = None,
    ) -> Path:
        """Write cleaned JSON + .txt under source_docs_dir."""
        self.source_docs_dir.mkdir(parents=True, exist_ok=True)
        doc = {
            "page_id": str(page_id),
            "title": title,
            "content": text,
            "revision": str((raw or {}).get("@revision") or ""),
            "source": "athena",
        }
        json_path = self.source_docs_dir / f"{page_id}.json"
        json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        (self.source_docs_dir / f"{page_id}.txt").write_text(text, encoding="utf-8")
        if raw is not None:
            raw_dir = self.source_docs_dir / "_athena_raw"
            raw_dir.mkdir(exist_ok=True)
            (raw_dir / f"{page_id}.json").write_text(
                json.dumps(raw, indent=2), encoding="utf-8"
            )
        return json_path

    def prepare_page(self, page_id: str) -> Path:
        """fetch → clean → save for one page."""
        raw = self.fetch_content_from_athena(page_id)
        title, text = self.clean_content(raw)
        if not text.strip():
            raise RuntimeError(f"Page {page_id}: cleaned text is empty")
        path = self.save_cleaned_data(page_id, title, text, raw=raw)
        print(f"Prepared {path} ({len(text)} chars)")
        return path

    def generate_goldens(
        self,
        *,
        cleaned_docs_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> list[Path]:
        """Delegate to goldens package — one StylingConfig batch per styles: entry."""
        return generate_goldens_from_docs(
            agent=self.agent,
            agent_dir=self.agent_dir,
            cfg=self.cfg,
            configs_dir=self.configs_dir,
            cleaned_docs_dir=Path(cleaned_docs_dir or self.source_docs_dir),
            output_dir=Path(output_dir or self.output_dir),
        )
