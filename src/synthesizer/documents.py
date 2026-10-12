"""
Select the documents to generate from (GROUP= / IDS= / ids_file) and cache them in synth/cache/.
`make goldens` fetches only documents missing from the cache.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.exceptions import ConfigError
from src.synthesizer.sources import load_source, normalise
from src.utils.text import safe_filename

UNGROUPED = "Unassigned"


def select(settings: dict[str, Any], groups: list[str] | None, ids: list[str] | None
           ) -> tuple[list[str] | None, dict[str, str]]:
    """Return (ids to use, or None for everything the source has; group of each id from ids_file)."""
    group_of: dict[str, str] = {}
    ids_file = settings["source"].get("ids_file")
    if ids_file:
        path = settings["folder"] / ids_file
        for entry in json.loads(path.read_text()):
            # "group"/"ids" are the generic names; "domain"/"page_ids" are the Knowledge Agent's.
            name = entry.get("group") or entry.get("domain") or UNGROUPED
            for doc_id in entry.get("ids") or entry.get("page_ids") or []:
                group_of[str(doc_id)] = name
        if groups:
            known = {g.lower() for g in group_of.values()}
            missing = [g for g in groups if g.lower() not in known]
            if missing:
                raise ConfigError(f"{path}: unknown group(s) {missing}. Groups: {sorted(set(group_of.values()))}")
    if ids:
        return [str(i) for i in ids], group_of
    if ids_file:
        wanted_groups = {g.lower() for g in groups or []}
        return [i for i, g in group_of.items() if not groups or g.lower() in wanted_groups], group_of
    return None, group_of


def fetch(settings: dict[str, Any], wanted: list[str] | None, group_of: dict[str, str],
          groups: list[str] | None) -> list[dict[str, Any]]:
    """Fetch documents from the source, validate them, and assign each its group."""
    source = load_source(settings["source"]["type"])
    documents = []
    for raw in source.fetch(settings["source"], wanted, settings["folder"]):
        document = normalise(raw, f"source {settings['source']['type']}")
        document["group"] = group_of.get(document["id"]) or document["group"] or UNGROUPED
        if not groups or document["group"].lower() in {g.lower() for g in groups}:
            documents.append(document)
    return documents


def documents_for_generation(settings: dict[str, Any], groups: list[str] | None,
                             ids: list[str] | None) -> list[dict[str, Any]]:
    """Return the selected documents from the cache, fetching any that aren't cached yet."""
    wanted, group_of = select(settings, groups, ids)
    if wanted is None:
        # Sources without ids (e.g. a folder of files) are always read fresh.
        documents = fetch(settings, None, group_of, groups)
    else:
        cache = settings["folder"] / "cache"
        missing = [i for i in wanted if not _cache_path(settings, i).is_file()]
        if missing:
            print(f"Fetching {len(missing)} document(s) not in the cache: {missing}")
            for document in fetch(settings, missing, group_of, None):
                save_to_cache(settings, document)
        documents = []
        for doc_id in wanted:
            path = cache / f"{safe_filename(doc_id)}.json"
            if not path.is_file():
                raise ConfigError(f"Source returned no document for id {doc_id}")
            document = json.loads(path.read_text())
            document["group"] = group_of.get(doc_id) or document.get("group") or UNGROUPED
            documents.append(document)
    if not documents:
        raise ConfigError("No documents selected — check the source settings, GROUP and IDS")
    return documents


def save_to_cache(settings: dict[str, Any], document: dict[str, Any]) -> Path:
    """Write one document to synth/cache/ and return its path."""
    path = _cache_path(settings, document["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved {path} ({len(document['text'])} characters)")
    return path


def _cache_path(settings: dict[str, Any], doc_id: str) -> Path:
    """Return the cache file path for a document id."""
    return settings["folder"] / "cache" / f"{safe_filename(doc_id)}.json"
