"""
Ingestion completeness (Pedro's test 1): did the preprocessing pipeline store every page of a domain?

For one domain (a root page in Athena), client.py calls collect() and saves what it returns as the trace:

    1. Athena: every page under the root, from the control-plane /tree endpoint (the pipeline's own list)
    2. GCS: what the pipeline stored for each page in the domain's folder, in all three buckets:
           {folder}/{page_id}/metadata.json  page.md  page.html
       and, from each metadata.json, the revision it converted and its preprocessing_status
    3. Athena: each page's current revision (is the stored copy out of date?)

The trace is one row of facts per page (in the tree, in the buckets, or both). It holds no verdicts:
fields.yaml picks out the missing / incomplete / extra / out-of-date pages and checks.yaml decides.

    {"root": {page_id, title}, "folder": "customer_vulnerability_hub_2", "buckets": {...},
     "pages": [{"page_id", "title", "path", "depth", "draft_state", "in_tree",
                "metadata", "markdown", "html",                       # which files exist (true / false)
                "stored_revision", "preprocessing_status", "page_type", # from metadata.json
                "athena_revision", "athena_error"}],                  # Athena now
     "latency_ms"}

The folder is the root's name in lower_snake_case, as the pipeline names it (page_location.py
root_folder: "Customer Vulnerability Hub 2" -> customer_vulnerability_hub_2), unless the case gives one.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from src.clients import gcs_client
from src.clients.athena_client import athena_http, get_page_content, get_page_tree, tree_pages

FILES = {"metadata": "metadata.json", "markdown": "page.md", "html": "page.html"}
BUCKETS = {"metadata": "metadata_bucket", "markdown": "md_bucket", "html": "html_bucket"}
WORKERS = 8                                   # pages read at the same time (GCS and Athena)


def collect(settings, case):
    start = time.perf_counter()
    root_id = str(case["page_id"])
    tree = tree_pages(get_page_tree(root_id))
    folder = case.get("folder") or folder_name(tree[0]["title"])

    # Which files the pipeline stored, per page id: {"40345": {"metadata", "markdown"}, ...}
    stored, buckets = {}, {}
    for kind, setting in BUCKETS.items():
        bucket = settings[setting]
        buckets[kind] = f"gs://{bucket}/{folder}/"
        for name in gcs_client.list_names(bucket, f"{folder}/"):
            page_id = page_id_of(name, FILES[kind])
            if page_id:
                stored.setdefault(page_id, set()).add(kind)

    in_tree = {page["page_id"]: page for page in tree}
    rows = [{**page, "in_tree": True} for page in tree]
    rows += [{"page_id": page_id, "title": "", "path": "", "depth": None, "draft_state": None, "in_tree": False}
             for page_id in sorted(set(stored) - set(in_tree), key=int)]
    for row in rows:
        row.update({kind: kind in stored.get(row["page_id"], set()) for kind in FILES})

    with ThreadPoolExecutor(WORKERS) as pool:
        details = pool.map(lambda row: _stored_details(settings["metadata_bucket"], folder, row), rows)
        for row, found in zip(rows, details, strict=True):
            row.update(found)
        with athena_http(60) as http:
            revisions = pool.map(lambda row: _athena_revision(http, row), rows)
            for row, found in zip(rows, revisions, strict=True):
                row.update(found)

    return {
        "root": {"page_id": root_id, "title": tree[0]["title"]},
        "folder": folder,
        "buckets": buckets,
        "pages": rows,
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }


def folder_name(name):
    """A business-area name as the pipeline's bucket folder:
    'Customer Vulnerability Hub 2' -> 'customer_vulnerability_hub_2'."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def page_id_of(name, file_name):
    """The page id in '<folder>/<page_id>/<file_name>', or None for any other file."""
    parts = name.split("/")
    return parts[-2] if len(parts) >= 3 and parts[-1] == file_name and parts[-2].isdigit() else None


def _stored_details(bucket, folder, row):
    """From the page's metadata.json: the revision the pipeline converted, its status and page type."""
    if not row["metadata"]:
        return {"stored_revision": None, "preprocessing_status": None, "page_type": None}
    try:
        metadata = json.loads(gcs_client.read_text(bucket, f"{folder}/{row['page_id']}/metadata.json") or "{}")
    except ValueError:
        metadata = {}
    page = metadata.get("page_metadata") or {}
    revision = page.get("revision")
    return {"stored_revision": None if revision is None else str(revision),
            "preprocessing_status": (metadata.get("operational_metadata") or {}).get("preprocessing_status"),
            "page_type": page.get("page_type"),
            "title": row["title"] or str(page.get("title") or "")}


def _athena_revision(http, row):
    """The page's revision in Athena now (pages only in the bucket may be deleted: an error is kept, not raised)."""
    try:
        return {"athena_revision": str(get_page_content(http, row["page_id"]).get("@revision") or "") or None,
                "athena_error": None}
    except Exception as error:  # noqa: BLE001 — one page Athena can't return is a finding, not a crash
        return {"athena_revision": None, "athena_error": str(error)[:300]}
