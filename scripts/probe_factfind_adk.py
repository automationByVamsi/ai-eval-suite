"""
Probe Fact Find ADK create_session (same call the sanity test uses).

    python -m scripts.probe_factfind_adk

Prints the resolved URL, header keys, and success or full error.
"""

from __future__ import annotations

from src.clients.adk_client import AdkClient
from src.core.logging_config import setup_logging


def main() -> None:
    setup_logging()
    client = AdkClient.from_agent_name("fact_find_workflow")
    scheme, host, base_path = client._host_and_base()
    path = f"{base_path}/apps/{client.app_name}/users/{client.user_id}/sessions"
    print(f"base_url     = {client.base_url}")
    print(f"base_path    = {client.base_path!r}")
    print(f"full URL     = {scheme}://{host}{path}")
    print(f"verify_tls   = {client.verify_tls}")
    print(f"header_keys  = {sorted(client.headers)}")
    print(f"app_name     = {client.app_name}")
    print(f"user_id      = {client.user_id}")
    try:
        session_id = client.create_session()
        print(f"OK session_id = {session_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
