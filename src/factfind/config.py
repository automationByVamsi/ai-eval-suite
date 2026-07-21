"""
Fact Find ground-truth config: endpoints + auth headers from environment.

Mirrors cce2ec-qe-playwright-e2e factfind/config/{endpoints,api-headers}.ts
Secrets stay in env / .env.factfind.api — never committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def require_env(name: str) -> str:
    value = env(name)
    if value is None:
        raise RuntimeError(f"{name} must be set (see .env.factfind.api.example)")
    return value


def counter_api_version() -> str:
    return (env("COUNTER_API_VERSION", "v3") or "v3").lower()


@dataclass(frozen=True)
class Endpoints:
    ica_case_details_template: str
    account_details: str
    customer_holding: str
    contact_notes_template: str
    trusted_parties_template: str

    @classmethod
    def from_env(cls) -> Endpoints:
        version = counter_api_version()
        apic = env(
            "FACTFIND_APIC_BASE",
            "https://apic-v10-ent.test.lloydsbanking.cloud",
        )
        nucleus = env(
            "FACTFIND_NUCLEUS_BASE",
            "https://nucleuscomplaintsproxy-test2.ia.lloydsbanking.cloud",
        )
        return cls(
            ica_case_details_template=(
                f"{nucleus}/MMXAPI2/api2/v3/{{complaintRef}}/ICA-case-details"
            ),
            account_details=(
                f"{apic}/lbg-sit/sit01/customer-profile/{version}/account-details"
            ),
            customer_holding=(
                f"{apic}/lbg-sit/sit01/customer-profile/{version}/customer-holding-summary"
            ),
            contact_notes_template=(
                f"{apic}/lbg-sit/lbg01/v2/parties/{{partyId}}/contact-notes"
            ),
            trusted_parties_template=(
                f"{apic}/lbg-sit/lbg01/v2/parties/{{partyId}}/trusted-parties"
            ),
        )

    def ica_case_details(self, complaint_ref: str) -> str:
        return self.ica_case_details_template.format(complaintRef=complaint_ref)

    def contact_notes(self, party_id: str) -> str:
        return self.contact_notes_template.format(partyId=quote(str(party_id), safe=""))

    def trusted_parties(self, party_id: str) -> str:
        return self.trusted_parties_template.format(partyId=quote(str(party_id), safe=""))


def get_counter_api_headers() -> dict[str, str]:
    version = counter_api_version()
    prefix = "COUNTER_V1" if version == "v1" else "COUNTER_V3"
    return {
        "content-type": "application/json",
        "x-ibm-client-id": require_env(f"{prefix}_IBM_CLIENT_ID"),
        "x-ibm-client-secret": require_env(f"{prefix}_IBM_CLIENT_SECRET"),
        "x-lbg-consent-level": require_env(f"{prefix}_CONSENT_LEVEL"),
        "x-lbg-outlet-id": require_env(f"{prefix}_OUTLET_ID"),
        "x-lbg-user-id": require_env(f"{prefix}_USER_ID"),
    }


def get_ocis_api_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "X-IBM-Client-Id": require_env("OCIS_IBM_CLIENT_ID"),
        "X-IBM-Client-Secret": require_env("OCIS_IBM_CLIENT_SECRET"),
        "X-lbg-user-id": require_env("OCIS_USER_ID"),
        "X-lbg-user-id-type": require_env("OCIS_USER_ID_TYPE"),
        "X-lbg-outlet-id": require_env("OCIS_OUTLET_ID"),
        "X-lbg-outlet-id-type": require_env("OCIS_OUTLET_ID_TYPE"),
        "X-lbg-application-id": require_env("OCIS_APPLICATION_ID"),
        "X-lbg-consent-level": require_env("OCIS_CONSENT_LEVEL"),
    }


def get_nucleus_api_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "X-MMXAPI-ImpersonateUser": require_env("NUCLEUS_IMPERSONATE_USER_ID"),
    }


def cert_paths() -> tuple[Path, Path] | None:
    """mTLS cert/key for APIC origin (optional if already on corporate network)."""
    cert = env("FACTFIND_APIC_CERT_PATH", "data/fact_find_workflow/certs/apic.pem")
    key = env("FACTFIND_APIC_KEY_PATH", "data/fact_find_workflow/certs/apic.key")
    cert_path, key_path = Path(cert or ""), Path(key or "")
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path
    return None


ELIGIBLE_PRODUCT_TYPES = frozenset(
    {"CURRENT_ACCOUNT", "SAVINGS", "DEPOSIT_SAVINGS", "DEPOSIT_AND_SAVINGS"}
)

DEFAULT_OUTPUT_DIR = Path("data/fact_find_workflow/aggregated_payloads")
DEFAULT_REFS_FILE = Path("data/fact_find_workflow/complaint-references.json")
