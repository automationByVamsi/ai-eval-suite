"""agents/knowledge_agent/ingestion: the pipeline's Markdown checked against the Athena page (no real Athena or GCS)."""

import importlib.util
import json

import httpx
import pytest

from src.clients import gcs_client
from src.core import paths
from src.core.results import FAIL, PASS
from src.runners.suite_runner import run_suite

FIXTURES = paths.ROOT / "tests" / "fixtures"
# A made-up page with every case the pipeline handles on purpose: a callout box, a nested list, a list
# inside a table cell, a link without text, an image, and hidden blocks (editor note, recent changes, script).
HTML = (FIXTURES / "ingestion_page.html").read_text()
GOOD_MD = (FIXTURES / "ingestion_page.md").read_text()      # what the pipeline's rules make of it
LOSSY_MD = GOOD_MD.replace("2. Order the card.\n", "").replace("> **WARNING** Never ask for the PIN.\n>\n", "")
ADDED_MD = GOOD_MD + "\nCards are free for everyone.\n"


def _agent_module(name):
    folder = paths.AGENTS_DIR / "knowledge_agent" / "ingestion"
    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CASE = {"test_case_id": "KA_MD_40345", "input": {"page_id": "40345", "md_path": "cv/40345.md"}, "expected": {}}


@pytest.fixture
def one_case(monkeypatch):
    """The markdown suite with one case (the real cases are written by make ingestion-cases)."""
    monkeypatch.setattr("src.runners.suite_runner.load_cases", lambda agent, suite: [CASE])


def _trace(markdown, revision="7", stored_revision="7", copies_match=True):
    return {"markdown": markdown, "source_html": HTML, "source": "metadata.json content.html",
            "metadata": {"page_metadata": {"id": "40345", "revision": stored_revision}},
            "stored_copies_match": copies_match,
            "athena": {"page_id": "40345", "title": "Ordering a replacement card", "revision": revision},
            "task": "Represent ... as Markdown", "files": {"markdown": "gs://md/40345.md"}, "latency_ms": 5}


def test_parser_follows_the_pipeline_rules():
    good = _agent_module("parser").parse(_trace(GOOD_MD), {})
    counts = {k: good[f"source_{k}"] for k in ("headings", "list_items", "table_rows", "links", "callouts")}
    assert counts == {"headings": 2, "list_items": 3, "table_rows": 2, "links": 1, "callouts": 2}
    assert all(good[f"md_{k}"] == v for k, v in counts.items())
    assert good["text_coverage"] == 1.0 and good["summary"] == "no differences"
    assert good["answer"] == GOOD_MD
    assert "editor note" not in good["contexts"][0].lower() and "var x" not in good["contexts"][0]   # hidden blocks
    assert good["contexts"][0].startswith("Ordering a replacement card\n\nOrdering a replacement card")


def test_parser_shows_what_was_lost_or_added():
    parse = _agent_module("parser").parse
    lossy = parse(_trace(LOSSY_MD), {})
    assert lossy["differences"]["counts"]["list items"] == "3 → 2"
    assert lossy["differences"]["missing_lines"] == ["order the card.", "never ask for the pin."]
    assert lossy["summary"] == "list items 3 → 2 · callouts 2 → 1 · 2 lines missing"
    added = parse(_trace(ADDED_MD), {})
    assert added["differences"]["added_lines"] == ["cards are free for everyone."]
    assert added["text_coverage"] == 1.0 and added["summary"] == "1 line added"


def test_parser_unescapes_html_like_the_pipeline():
    escaped = HTML.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parsed = _agent_module("parser").parse({**_trace(GOOD_MD), "source_html": escaped}, {})
    assert parsed["summary"] == "no differences"


def test_client_takes_the_source_from_metadata_json(monkeypatch):
    client = _agent_module("client")
    monkeypatch.setattr(client, "get_page_content", lambda http, page_id: {"@title": "Ordering a replacement card",
                                                                            "@revision": "8", "body": ["<p>live</p>"]})
    monkeypatch.setattr(client, "athena_http", lambda timeout: httpx.Client())
    metadata = {"page_metadata": {"id": "40345", "revision": "7"}, "content": {"html": HTML, "markdown": GOOD_MD}}
    files = {("md", "kb/40345.md"): GOOD_MD, ("meta", "kb/40345.json"): json.dumps(metadata)}
    monkeypatch.setattr(client.gcs_client, "read_text", lambda bucket, path: files.get((bucket, path)))
    settings = {"md_bucket": "md", "md_path": "kb/<page_id>.md", "metadata_bucket": "meta",
                "metadata_path": "kb/<page_id>.json"}
    trace = client.call_agent(settings, "40345")
    assert trace["markdown"] == GOOD_MD and trace["source_html"] == HTML
    assert trace["source"] == "metadata.json content.html" and trace["stored_copies_match"] is True
    assert trace["metadata"] == {"page_metadata": {"id": "40345", "revision": "7"}}       # content not saved twice
    assert trace["athena"]["revision"] == "8" and trace["files"]["markdown"] == "gs://md/kb/40345.md"
    with pytest.raises(FileNotFoundError, match="no Markdown for page 40999 at gs://md/kb/40999.md"):
        client.call_agent(settings, "40999")
    files[("md", "cv/40345.md")] = GOOD_MD                    # a case from make ingestion-cases: exact paths
    trace = client.call_agent(settings, json.dumps({"page_id": "40345", "md_path": "cv/40345.md",
                                                    "metadata_path": "none.json"}))
    assert trace["files"]["markdown"] == "gs://md/cv/40345.md"
    assert trace["source"] == "Athena (live page)" and trace["source_html"] == "<p>live</p>"  # no metadata.json
    assert trace["stored_copies_match"] is None and trace["metadata"] is None


@pytest.mark.parametrize("markdown, trace_args, failed", [
    (GOOD_MD, {}, []),
    (LOSSY_MD, {}, ["list_items_kept", "callouts_kept", "text_coverage"]),
    (GOOD_MD, {"stored_revision": "6"}, ["same_revision"]),            # made from an older version of the page
    (GOOD_MD, {"copies_match": False}, ["stored_copies_match"]),       # page.md != metadata.json markdown
])
def test_markdown_suite_checks_on_a_saved_trace(outputs, one_case, markdown, trace_args, failed):
    saved = outputs / "outputs" / "traces" / "knowledge_agent" / "ingestion" / "markdown"
    saved.mkdir(parents=True)
    (saved / "KA_MD_40345.json").write_text(json.dumps(_trace(markdown, **trace_args)))
    run = run_suite("knowledge_agent/ingestion", "markdown", offline=True, judges=False, case_ids=["KA_MD_40345"])
    case = run.cases[0]
    assert [r.name for r in case.results if r.status == FAIL] == failed
    assert (case.status == PASS) == (not failed)


def test_gcs_read_text(monkeypatch):
    monkeypatch.setattr(gcs_client, "access_token", lambda: "token")
    replies = {"a.md": (200, "# Page"), "none.md": (404, ""), "secret.md": (403, "")}
    seen = []

    def fake_get(url, headers, **kwargs):
        seen.append((url, headers["Authorization"]))
        status, text = replies[url.split("/o/")[1].split("?")[0]]
        return httpx.Response(status, text=text, request=httpx.Request("GET", url))
    monkeypatch.setattr(gcs_client.httpx, "get", fake_get)
    assert gcs_client.read_text("bucket", "a.md") == "# Page"
    assert seen[0] == ("https://storage.googleapis.com/storage/v1/b/bucket/o/a.md?alt=media", "Bearer token")
    assert gcs_client.read_text("bucket", "none.md") is None
    with pytest.raises(RuntimeError, match="no access to gs://bucket/secret.md"):
        gcs_client.read_text("bucket", "secret.md")


def test_not_signed_in_is_a_clear_case_error(outputs, one_case):
    run = run_suite("knowledge_agent/ingestion", "markdown", offline=False, judges=False, case_ids=["KA_MD_40345"])
    assert run.cases[0].error == "agent: not signed in to Google Cloud — run: make gcloud-auth"


def test_a_sub_agent_is_listed_run_and_found_again(outputs, one_case):
    from src.core.agent_config import list_agents
    from src.core.results import load_run, recent_runs
    assert "knowledge_agent/ingestion" in list_agents()
    saved = outputs / "outputs" / "traces" / "knowledge_agent" / "ingestion" / "markdown"
    saved.mkdir(parents=True)
    (saved / "KA_MD_40345.json").write_text(json.dumps(_trace(GOOD_MD)))
    run = run_suite("knowledge_agent/ingestion", "markdown", offline=True, judges=False, case_ids=["KA_MD_40345"])
    assert run.run_id.endswith("_knowledge_agent.ingestion_markdown")          # one folder under outputs/runs/
    assert load_run("latest", "knowledge_agent/ingestion", "markdown").run_id == run.run_id
    assert [r.run_id for r in recent_runs("knowledge_agent/ingestion", "markdown", 5)] == [run.run_id]


def test_make_ingestion_cases_from_the_buckets(monkeypatch, tmp_path, capsys):
    import importlib

    from src.core.agent_config import load_agent
    make_cases = importlib.import_module("agents.knowledge_agent.ingestion.make_cases")
    listing = {"md": ["customer-vulnerability/40345.md", "customer-vulnerability/40017.md", "complaints/50001.md",
                      "complaints/readme.md", "customer-vulnerability/40345.html"],
               "meta": ["customer-vulnerability/40345.json"]}

    def agent_writing_to_tmp(name):
        agent = load_agent(name)
        agent.connection.update(md_bucket="md", metadata_bucket="meta")
        agent.suite("markdown").testdata = tmp_path
        return agent
    monkeypatch.setattr(make_cases, "load_agent", agent_writing_to_tmp)
    monkeypatch.setattr(make_cases.gcs_client, "list_names", lambda bucket: listing[bucket])

    assert make_cases.main(["--per-domain", "1"]) == 0
    out = capsys.readouterr().out
    assert "3 pages with Markdown (1 with metadata" in out and "without a page id" in out
    assert "complaints" in out and "customer-vulnerability" in out
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json"))
    assert written == ["complaints/KA_MD_50001.json", "customer-vulnerability/KA_MD_40017.json"]   # 1 per domain
    case = json.loads((tmp_path / "complaints" / "KA_MD_50001.json").read_text())
    assert case["input"] == {"page_id": "50001", "md_path": "complaints/50001.md", "metadata_path": ""}


def test_dashboard_shows_the_page_comparison(outputs, one_case):
    from streamlit.testing.v1 import AppTest
    saved = outputs / "outputs" / "traces" / "knowledge_agent" / "ingestion" / "markdown"
    saved.mkdir(parents=True)
    (saved / "KA_MD_40345.json").write_text(json.dumps(_trace(LOSSY_MD)))
    run_suite("knowledge_agent/ingestion", "markdown", offline=True, judges=False, case_ids=["KA_MD_40345"])
    app = AppTest.from_file(str(paths.ROOT / "src" / "reporting" / "dashboard.py"), default_timeout=60)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    text = " ".join(str(m.value) for m in app.markdown)
    assert "Source page (HTML)" in text and "Pipeline Markdown" in text and "list items 3 → 2" in text
    assert any("never ask for the pin." in str(c.value) for c in app.code)       # a missing line
