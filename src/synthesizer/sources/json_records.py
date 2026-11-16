"""
Source `json_records`: one document per record in a JSON file (e.g. an API export).
Settings: file, records_key, id_field, title_field, group_field, text_fields (default: the whole record as JSON).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def fetch(settings: dict[str, Any], ids: list[str] | None, folder: Path) -> list[dict[str, Any]]:
    """Return one document per record; the full record is kept in metadata.record for the output template."""
    data = json.loads((folder / settings["file"]).read_text())
    records = data[settings["records_key"]] if settings.get("records_key") else data
    if not isinstance(records, list):
        raise ValueError(f"{settings['file']}: expected a list of records (set records_key?)")

    id_field = settings.get("id_field", "id")
    documents = []
    for record in records:
        record_id = str(record.get(id_field, ""))
        if ids is not None and record_id not in ids:
            continue
        if settings.get("text_fields"):
            text = "\n\n".join(f"{f}: {record[f]}" for f in settings["text_fields"] if record.get(f))
        else:
            text = json.dumps(record, indent=2, ensure_ascii=False)
        documents.append({
            "id": record_id,
            "title": str(record.get(settings.get("title_field", ""), "")),
            "text": text,
            "group": str(record.get(settings.get("group_field", ""), "")),
            "metadata": {"record": record},
        })
    return documents
