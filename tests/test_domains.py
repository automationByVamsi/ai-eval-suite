"""Business areas (domains.yaml): one naming standard for golden and synthetic cases."""

import pytest

from src.core.agent_config import load_agent
from src.core.domains import domain_values, load_domains
from src.core.exceptions import ConfigError


def test_each_business_area_gives_name_path_id_and_folder():
    domains = load_domains(load_agent("knowledge_agent").folder)
    assert len(domains) == 25
    assert domain_values("Complaint Managers", domains) == {
        "domain": "COMPLAINT_MANAGERS", "domain_folder": "complaint_managers",
        "domain_name": "Complaint Managers", "domain_path": "Complaint_Managers"}
    assert domain_values("CVH 2", domains)["domain_path"] == "Customer_Vulnerability_Hub_2"     # an alias
    assert domain_values("customer_vulnerability_hub", domains)["domain"] == "CUSTOMER_VULNERABILITY_HUB"
    assert domain_values("Customer Self Service Online and App", domains)["domain_name"] \
        == "Customer Self-Service Online and App"                                                 # punctuation ignored
    assert domain_values("PCA", domains) == {"domain": "PCA", "domain_folder": "pca",              # not listed
                                             "domain_name": "PCA", "domain_path": "PCA"}


def test_a_path_can_be_given_when_it_is_not_the_usual_one(tmp_path):
    (tmp_path / "domains.yaml").write_text("Fraud: [FR]\nOdd Name:\n  aliases: [OD]\n  path: Odd-Name\n")
    domains = load_domains(tmp_path)
    assert domain_values("FR", domains)["domain_path"] == "Fraud"
    assert domain_values("OD", domains)["domain_path"] == "Odd-Name"
    (tmp_path / "domains.yaml").write_text("- Fraud\n")
    with pytest.raises(ConfigError, match="official name"):
        load_domains(tmp_path)
