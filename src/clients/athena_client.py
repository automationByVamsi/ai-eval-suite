"""
Athena Control Plane — fetch page HTML/JSON by page id.

  GET {base_url}/control-plane/v1/pages/{page_id}/contents?format=json
  Header: x-lbg-origin-client-id: <ATHEN_ID>
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.core.network import get


class AthenaClient:
    """Tiny wrapper around Athena page-contents GET."""

    def __init__(
        self,
        *,
        base_url: str,
        verify_tls: bool = False,
        timeout_s: float = 60,
        retries: int = 1,
        client_id_env: str = "ATHEN_ID",
    ):
        self.base_url = base_url.rstrip("/")
        self.verify_tls = verify_tls
        self.timeout_s = timeout_s
        self.retries = retries
        self.client_id_env = client_id_env

    def _headers(self) -> dict[str, str]:
        client_id = os.environ.get(self.client_id_env, "").strip()
        if not client_id:
            raise RuntimeError(
                f"{self.client_id_env} is missing/empty — needed for Athena "
                f"(x-lbg-origin-client-id)."
            )
        return {"x-lbg-origin-client-id": client_id}

    def get_page_contents(self, page_id: str) -> dict[str, Any]:
        """Live GET page contents as JSON."""
        url = f"{self.base_url}/control-plane/v1/pages/{page_id}/contents"
        data = get(
            url,
            headers=self._headers(),
            params={"format": "json"},
            verify_tls=self.verify_tls,
            timeout_s=self.timeout_s,
            retries=self.retries,
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"Athena page {page_id}: expected a JSON object")
        return data


def load_page_fixture(path: str | Path) -> dict[str, Any]:
    """Load a saved Athena response (e.g. 8708-response.json) for offline generate."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Athena fixture must be a JSON object: {path}")
    return data
