"""
The Knowledge Agent's ingestion pipeline, evaluated like an agent: for one knowledge-base page,
what Athena has (the source) and what the preprocessing pipeline made of it (the Markdown in GCS).

The framework calls call_agent(connection, page_id) for each test case, saves what it returns as the
trace (OFFLINE=1 replays it), and judges it like any agent's answer:
    agentOutput  the pipeline's Markdown          -> the "answer" the judges and checks look at
    context      the Athena page as plain text    -> the source the Markdown is judged against
Structure counts and text coverage are measured in parser.py; fields in fields.yaml.

Needs: `make gcloud-auth` (Google sign-in, for the buckets) and the Athena settings in env/.env.
Where the files are: `connection:` in agent.yaml.
"""

import json
import time

from src.clients import gcs_client
from src.clients.athena_client import athena_http, get_page_content, page_html
from src.utils.html_text import html_to_text


def call_agent(settings, page_id):
    start = time.perf_counter()
    md_file = (settings["md_bucket"], settings["md_path"].replace("<page_id>", page_id))
    markdown = gcs_client.read_text(*md_file)
    if markdown is None:
        raise FileNotFoundError(f"no Markdown for page {page_id} at gs://{md_file[0]}/{md_file[1]} — "
                                f"check md_path in agents/ka_ingestion/agent.yaml (GCS_MD_PATH)")
    metadata_file = (settings["metadata_bucket"], settings["metadata_path"].replace("<page_id>", page_id))
    metadata = gcs_client.read_text(*metadata_file)       # optional: only used for the revision check
    with athena_http(60) as http:
        page = get_page_content(http, page_id)
    html, title = page_html(page), str(page.get("@title") or "").strip()

    return {
        "agentOutput": markdown,
        "context": [f"{title}\n\n{html_to_text(html)}"],
        "task": f"Represent the knowledge-base page '{title}' as Markdown, keeping all of its content and meaning.",
        "athena": {"page_id": page_id, "title": title, "revision": str(page.get("@revision") or ""), "html": html},
        "metadata": _json_or_none(metadata),
        "files": {"markdown": "gs://{}/{}".format(*md_file), "metadata": "gs://{}/{}".format(*metadata_file)},
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }


def _json_or_none(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None
