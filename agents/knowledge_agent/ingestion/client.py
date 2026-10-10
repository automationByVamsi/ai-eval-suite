"""
The Knowledge Agent's ingestion pipeline, evaluated like an agent: for one knowledge-base page, the HTML
the preprocessing pipeline converted and the Markdown it stored in GCS.

The framework calls call_agent(connection, message) for each test case — message is the case's input as
JSON ({"page_id", "md_path", "metadata_path"}, written by `make ingestion-cases`), or just a page id (then
the file paths come from md_path / metadata_path in agent.yaml). What this returns is saved as the trace
(OFFLINE=1 replays it):

    markdown        page.md from the Markdown bucket                   -> what is judged
    source_html     the HTML the pipeline converted: content.html in the page's metadata.json
                    (the live Athena page when the metadata has none — see `source`)
    source          where source_html came from
    metadata        the page's metadata.json, without content (page_metadata, relationships, ...)
    stored_copies_match   page.md == content.markdown in metadata.json (null without metadata)
    athena          page_id, title and revision of the page in Athena NOW (is the Markdown out of date?)
    files           the gs:// paths that were read

parser.py measures the Markdown against source_html; fields.yaml reads the rest.
Needs: `make gcloud-auth` (Google sign-in, for the buckets) and the Athena settings in env/.env.
"""

import json
import time

from src.clients import gcs_client
from src.clients.athena_client import athena_http, get_page_content, page_html


def call_agent(settings, message):
    start = time.perf_counter()
    case = json.loads(message) if message.startswith("{") else {"page_id": message}
    page_id = case["page_id"]
    md_file = (settings["md_bucket"], case.get("md_path") or settings["md_path"].replace("<page_id>", page_id))
    metadata_file = (settings["metadata_bucket"],
                     case.get("metadata_path") or settings["metadata_path"].replace("<page_id>", page_id))

    markdown = gcs_client.read_text(*md_file)
    if markdown is None:
        raise FileNotFoundError(f"no Markdown for page {page_id} at gs://{md_file[0]}/{md_file[1]} — "
                                f"run make ingestion-cases to take the paths from the bucket")
    metadata = _json_or_none(gcs_client.read_text(*metadata_file)) or {}
    content = metadata.pop("content", None) or {}
    with athena_http(60) as http:
        page = get_page_content(http, page_id)
    stored_markdown = content.get("markdown")

    return {
        "markdown": markdown,
        "source_html": content.get("html") or page_html(page),
        "source": "metadata.json content.html" if content.get("html") else "Athena (live page)",
        "metadata": metadata or None,
        "stored_copies_match": None if stored_markdown is None else stored_markdown.strip() == markdown.strip(),
        "athena": {"page_id": page_id, "title": str(page.get("@title") or "").strip(),
                   "revision": str(page.get("@revision") or "")},
        "task": f"Represent the knowledge-base page '{str(page.get('@title') or '').strip()}' as Markdown, "
                f"keeping all of its content and meaning.",
        "files": {"markdown": "gs://{}/{}".format(*md_file), "metadata": "gs://{}/{}".format(*metadata_file)},
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }


def _json_or_none(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None
