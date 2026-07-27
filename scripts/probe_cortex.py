"""
Print what CORTEX credentials this process will actually use (no full secrets).

    python -m scripts.probe_cortex
"""

from __future__ import annotations

import os

from src.clients.cortex_client import CortexClient
from src.core.config import load_cortex_config
from src.core.env import load_dotenv


def main() -> None:
    load_dotenv()
    cfg = load_cortex_config()
    client = CortexClient(cfg)
    cid = client.headers.get("x-lbg-origin-client-id", "")
    print(f"CORTEX_HOST env     = {os.environ.get('CORTEX_HOST', '')!r}")
    print(f"CORTEX_MODEL env    = {os.environ.get('CORTEX_MODEL', '')!r}")
    print(f"resolved model      = {client.model!r}")
    print(f"resolved URL        = {client.scheme}://{client.host}{client.path}")
    print(f"client_id length    = {len(cid)}")
    print(f"client_id last4     = ...{cid[-4:] if len(cid) >= 4 else cid!r}")
    print(f"header keys         = {sorted(client.headers)}")
    print()
    print("Compare last4 + model to working factfind env/.env.factfind.api")
    print("If they differ, copy CORTEX_CLIENT_ID / CORTEX_MODEL from that file.")


if __name__ == "__main__":
    main()
