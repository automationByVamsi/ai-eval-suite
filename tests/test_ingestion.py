"""agents/ka_ingestion: the pipeline's Markdown checked against the Athena page (no real Athena or GCS)."""

import importlib.util
import json

import httpx
import pytest

from src.clients import gcs_client
from src.core import paths
from src.core.results import FAIL, PASS
from src.runners.suite_runner import run_suite

HTML = ("<h2>Add a support need</h2><p>Open <a href='/p/1'>Customer Support Needs</a>.</p>"
        "<ol><li>Choose the support required.</li><li>Set a review date.</li></ol>"
        "<table><tr><th>Need</th><th>Review</th></tr><tr><td>Large print</td><td>12 months</td></tr></table>")
GOOD_MD = ("## Add a support need\n\nOpen [Customer Support Needs](/p/1).\n\n"
           "1. Choose the support required.\n2. Set a review date.\n\n"
           "| Need | Review |\n|---|---|\n| Large print | 12 months |\n")
LOSSY_MD = "## Add a support need\n\nOpen Customer Support Needs.\n\n1. Choose the support required.\n"


def _agent_module(name):
    spec = importlib.util.spec_from_file_location(name, paths.AGENTS_DIR / "ka_ingestion" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trace(markdown, revision="7", stored_revision="7"):
    return {"agentOutput": markdown, "context": ["Add a support need ..."], "task": "Represent ... as Markdown",
            "athena": {"page_id": "40345", "title": "Add a support need", "revision": revision, "html": HTML},
            "metadata": {"revision": stored_revision}, "files": {"markdown": "gs://md/40345.md"}, "latency_ms": 5}


def test_parser_counts_structure_and_text_coverage():
    parse = _agent_module("parser").parse
    good = parse(_trace(GOOD_MD), {})
    assert (good["source_headings"], good["source_list_items"], good["source_table_rows"], good["source_links"]) \
        == (1, 2, 2, 1)
    assert (good["md_headings"], good["md_list_items"], good["md_table_rows"], good["md_links"]) == (1, 2, 2, 1)
    assert good["text_coverage"] == 1.0 and good["missing_lines"] == []
    lossy = parse(_trace(LOSSY_MD), {})
    assert lossy["md_list_items"] == 1 and lossy["md_table_rows"] == 0 and lossy["md_links"] == 0
    assert lossy["text_coverage"] < 0.98 and "set a review date." in lossy["missing_lines"]


def test_client_reads_athena_and_the_buckets(monkeypatch):
    client = _agent_module("client")
    monkeypatch.setattr(client, "get_page_content", lambda http, page_id: {"@title": "Add a support need",
                                                                            "@revision": "7", "body": [HTML]})
    monkeypatch.setattr(client, "athena_http", lambda timeout: httpx.Client())
    files = {("md", "kb/40345.md"): GOOD_MD, ("meta", "kb/40345.json"): '{"revision": "7"}'}
    monkeypatch.setattr(client.gcs_client, "read_text", lambda bucket, path: files.get((bucket, path)))
    settings = {"md_bucket": "md", "md_path": "kb/<page_id>.md", "metadata_bucket": "meta",
                "metadata_path": "kb/<page_id>.json"}
    trace = client.call_agent(settings, "40345")
    assert trace["agentOutput"] == GOOD_MD and trace["athena"]["revision"] == "7"
    assert trace["context"][0].startswith("Add a support need\n\nAdd a support need")
    assert trace["metadata"] == {"revision": "7"} and trace["files"]["markdown"] == "gs://md/kb/40345.md"
    with pytest.raises(FileNotFoundError, match="no Markdown for page 40999 at gs://md/kb/40999.md"):
        client.call_agent(settings, "40999")


@pytest.mark.parametrize("markdown, stored, failed", [
    (GOOD_MD, "7", []),
    (LOSSY_MD, "7", ["list_items_kept", "table_rows_kept", "links_kept", "text_coverage"]),
    (GOOD_MD, "6", ["same_revision"]),                       # made from an older version of the page
])
def test_markdown_suite_checks_on_a_saved_trace(outputs, markdown, stored, failed):
    saved = outputs / "outputs" / "traces" / "ka_ingestion" / "markdown"
    saved.mkdir(parents=True)
    (saved / "KA_MD_40345.json").write_text(json.dumps(_trace(markdown, stored_revision=stored)))
    run = run_suite("ka_ingestion", "markdown", offline=True, judges=False, case_ids=["KA_MD_40345"])
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


def test_not_signed_in_is_a_clear_case_error(outputs):
    run = run_suite("ka_ingestion", "markdown", offline=False, judges=False, case_ids=["KA_MD_40345"])
    assert run.cases[0].error == "agent: not signed in to Google Cloud — run: make gcloud-auth"
