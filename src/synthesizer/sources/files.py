"""
Source `files`: read .txt/.md/.json documents from a folder (default synth/documents).
Sub-folder names become the document's group.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def fetch(settings: dict[str, Any], ids: list[str] | None, folder: Path) -> list[dict[str, Any]]:
    """Return one document per .txt/.md/.json file under the folder, skipping names starting with _."""
    root = folder / settings.get("folder", "documents")
    if not root.is_dir():
        raise FileNotFoundError(f"Source folder not found: {root}")
    documents = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".txt", ".md", ".json") or path.name.startswith("_"):
            continue
        group = str(path.parent.relative_to(root)) if path.parent != root else ""
        if path.suffix == ".json":
            data = json.loads(path.read_text())
            document = {"id": data.get("id") or path.stem, "title": data.get("title", ""),
                        "text": data.get("text") or data.get("content", ""),
                        "group": data.get("group") or group, "metadata": data.get("metadata", {})}
        else:
            text = path.read_text().strip()
            document = {"id": path.stem, "title": text.splitlines()[0] if text else "", "text": text,
                        "group": group}
        if ids is None or str(document["id"]) in ids:
            documents.append(document)
    return documents
