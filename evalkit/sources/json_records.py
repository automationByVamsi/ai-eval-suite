"""
Source `json_records`: one JSON file holding a list of records (e.g. an API export) — no code needed.

    source:
      type: json_records
      file: records.json          # relative to the agent's synth/ folder; a list, or {"<key>": [...]}
      records_key: items          # optional: where the list is, if the file is an object
      id_field: id
      title_field: name           # optional
      group_field: region         # optional
      text_fields: [summary, details]   # optional: joined as the text. Leave out to use the
                                        # whole record as pretty JSON (good for structured data)
"""

import json


def fetch(settings, ids, folder):
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
