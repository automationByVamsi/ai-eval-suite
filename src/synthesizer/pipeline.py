"""
Knowledge Agent synthesizer pipeline (generate goldens / run against them).

All knobs live in configs/synthesizer/<agent>/config.yaml.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import EvolutionConfig, StylingConfig
from deepeval.synthesizer.types import Evolution

from src.clients.athena_client import AthenaClient, load_page_fixture
from src.clients.cortex_client import CortexClient
from src.clients.cortex_deepeval import CortexDeepEvalLLM
from src.core.config import load_cortex_config, load_yaml
from src.runners.case_runner import load_cases, run_case
from src.runners.evaluate import evaluate
from src.synthesizer.clean import athena_payload_to_text

_EVOLUTION_BY_NAME = {e.name: e for e in Evolution}


def load_synth_config(agent: str, configs_dir: str | Path = "configs") -> dict[str, Any]:
    path = Path(configs_dir) / "synthesizer" / agent / "config.yaml"
    return load_yaml(path)


def _fetch_page(page_id: str, fetch_cfg: dict[str, Any]) -> dict[str, Any]:
    """Live Athena GET, or offline fixture when use_fixture is true."""
    if fetch_cfg.get("use_fixture"):
        fixture = fetch_cfg.get("fixture_path") or fetch_cfg.get("fixtures", {}).get(str(page_id))
        if not fixture:
            raise RuntimeError(
                f"fetch.use_fixture=true but no fixture_path / fixtures[{page_id}] set"
            )
        return load_page_fixture(fixture)

    client = AthenaClient(
        base_url=str(fetch_cfg["base_url"]),
        verify_tls=bool(fetch_cfg.get("verify_tls", False)),
        timeout_s=float(fetch_cfg.get("timeout_s", 60)),
        retries=int(fetch_cfg.get("retries", 1)),
        client_id_env=str(fetch_cfg.get("client_id_env", "CORTEX_CLIENT_ID")),
    )
    return client.get_page_contents(str(page_id))


def _save_cleaned_doc(
    *,
    agent: str,
    page_id: str,
    title: str,
    text: str,
    raw: dict[str, Any],
) -> Path:
    """Save cleaned text (+ raw JSON) under data/<agent>/source_docs/."""
    out_dir = Path("data") / agent / "source_docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "page_id": str(page_id),
        "title": title,
        "content": text,
        "source": "athena",
    }
    json_path = out_dir / f"{page_id}.json"
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (out_dir / f"{page_id}.txt").write_text(text, encoding="utf-8")
    raw_dir = out_dir / "_athena_raw"
    raw_dir.mkdir(exist_ok=True)
    (raw_dir / f"{page_id}.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return json_path


def _build_styling(gen_cfg: dict[str, Any], configs_dir: Path, agent: str) -> StylingConfig:
    styling = dict(gen_cfg.get("styling") or {})
    instruction_file = gen_cfg.get("instruction_file")
    if instruction_file:
        path = Path(instruction_file)
        if not path.is_file():
            path = Path(configs_dir) / "synthesizer" / agent / Path(instruction_file).name
        if path.is_file():
            instructions = path.read_text(encoding="utf-8").strip()
            # DeepEval StylingConfig has no free-form "instructions" field —
            # fold the file into scenario so the model still sees it.
            existing = styling.get("scenario") or ""
            styling["scenario"] = (
                f"{existing}\n\nInstructions:\n{instructions}".strip()
                if existing
                else f"Instructions:\n{instructions}"
            )
    return StylingConfig(
        scenario=styling.get("scenario"),
        task=styling.get("task"),
        input_format=styling.get("input_format"),
        expected_output_format=styling.get("expected_output_format"),
    )


def _build_evolution(gen_cfg: dict[str, Any]) -> EvolutionConfig | None:
    evo = gen_cfg.get("evolution")
    if not evo:
        return None
    raw_map = evo.get("evolutions") or {}
    evolutions: dict[Evolution, float] = {}
    for name, weight in raw_map.items():
        key = str(name).upper().replace("-", "_").replace(" ", "_")
        if key not in _EVOLUTION_BY_NAME:
            raise ValueError(
                f"Unknown evolution {name!r}. Known: {sorted(_EVOLUTION_BY_NAME)}"
            )
        evolutions[_EVOLUTION_BY_NAME[key]] = float(weight)
    if evolutions:
        return EvolutionConfig(
            num_evolutions=int(evo.get("num_evolutions", 1)),
            evolutions=evolutions,
        )
    return EvolutionConfig(num_evolutions=int(evo.get("num_evolutions", 1)))


def generate_goldens(
    agent: str,
    configs_dir: str | Path = "configs",
    *,
    use_fixture: bool | None = None,
) -> list[Path]:
    """
    Fetch Athena pages → clean HTML → DeepEval synthesizer → testdata/<agent>/<suite>/.
    """
    cfg = load_synth_config(agent, configs_dir)
    fetch_cfg = dict(cfg.get("fetch") or {})
    if use_fixture is not None:
        fetch_cfg["use_fixture"] = use_fixture
    gen_cfg = cfg.get("generation") or {}
    page_ids = [str(p) for p in (fetch_cfg.get("page_ids") or [])]
    if not page_ids:
        raise SystemExit("fetch.page_ids is empty in synthesizer config")

    contexts: list[list[str]] = []
    page_for_context: list[str] = []

    for page_id in page_ids:
        raw = _fetch_page(page_id, fetch_cfg)
        title, text = athena_payload_to_text(raw)
        if not text.strip():
            raise RuntimeError(f"Page {page_id}: cleaned text is empty")
        _save_cleaned_doc(agent=agent, page_id=page_id, title=title, text=text, raw=raw)
        contexts.append([text])
        page_for_context.append(page_id)
        print(f"Fetched + cleaned page {page_id} ({len(text)} chars)")

    cortex = CortexClient(load_cortex_config(f"{configs_dir}/cortex.yaml"))
    llm = CortexDeepEvalLLM(cortex)
    styling = _build_styling(gen_cfg, Path(configs_dir), agent)
    evolution = _build_evolution(gen_cfg)

    synthesizer = Synthesizer(
        model=llm,
        async_mode=False,
        styling_config=styling,
        evolution_config=evolution,
    )
    goldens = synthesizer.generate_goldens_from_contexts(
        contexts=contexts,
        include_expected_output=bool(gen_cfg.get("include_expected_output", True)),
        max_goldens_per_context=int(gen_cfg.get("max_goldens_per_context", 2)),
    )

    suite = str(gen_cfg.get("output_suite") or "golden")
    out_dir = Path("testdata") / agent / suite
    out_dir.mkdir(parents=True, exist_ok=True)

    # Clear previous goldens in this suite so re-runs don't leave stale cases.
    for old in out_dir.glob("TC_GOLDEN_*.json"):
        old.unlink()

    written: list[Path] = []
    agent_name = str(cfg.get("agent_name") or agent)
    for i, golden in enumerate(goldens, start=1):
        # Round-robin map goldens back to page ids (DeepEval returns flat list).
        page_id = page_for_context[(i - 1) % len(page_for_context)]
        test_case_id = f"TC_GOLDEN_{i:03d}"
        case = {
            "test_case_id": test_case_id,
            "description": f"Synthesized from Athena page {page_id}",
            "agent_name": agent_name,
            "input": {"question": golden.input},
            "expected": {
                "answer": golden.expected_output or "",
                "source_page_id": page_id,
            },
        }
        path = out_dir / f"{test_case_id}.json"
        path.write_text(json.dumps(case, indent=2), encoding="utf-8")
        written.append(path)
        print(f"Wrote {path}")

    print(f"Generated {len(written)} golden(s) under {out_dir}/")
    return written


def run_goldens(agent: str, configs_dir: str | Path = "configs") -> None:
    """Load generated goldens → live ADK invoke → optional suite judges."""
    cfg = load_synth_config(agent, configs_dir)
    run_cfg = cfg.get("run") or {}
    data_suite = str(run_cfg.get("data_suite") or (cfg.get("generation") or {}).get("output_suite") or "golden")
    metrics_suite = str(run_cfg.get("metrics_suite") or "sanity")
    do_judges = bool(run_cfg.get("run_judges", True))
    # Allow env override without editing YAML (same pattern as KA sanity tests).
    if os.environ.get("RUN_JUDGES") == "0":
        do_judges = False
    if os.environ.get("RUN_JUDGES") == "1":
        do_judges = True

    cases = load_cases(agent, data_suite)
    if not cases:
        raise SystemExit(f"No cases under testdata/{agent}/{data_suite}/ — run --mode generate first")

    output_dir = Path("outputs/traces")
    failed: list[str] = []

    for case in cases:
        print(f"\n=== {case['test_case_id']} ===")
        result = run_case(agent, case, data_suite, output_dir=output_dir)
        print(f"Saved: {result.saved_path}")
        print(f"Answer preview: {(result.response.answer or '')[:200]!r}")

        if do_judges:
            judges = evaluate(agent, metrics_suite, case, result.response)
            if judges.failed:
                for j in judges.failed:
                    failed.append(f"{case['test_case_id']}:{j.name} score={j.score}")
                    print(f"  FAIL {j.name}: {j.score} — {j.reason}")
            else:
                print(f"  Judges OK ({len(judges.judges)})")

    if failed:
        raise SystemExit(f"{len(failed)} judge failure(s):\n  " + "\n  ".join(failed))
    print("\nAll golden runs completed.")
