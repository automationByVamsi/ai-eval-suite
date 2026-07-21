"""Unit tests for Fact Find MCP catalog helpers (no live ADK / CORTEX)."""

from src.parsers.fact_find_workflow.mcp_catalog import (
    default_factfind_mcp_servers,
    extract_mcp_tools_called,
    mcp_tools_from_tool_calls,
)
from deepeval.test_case import ToolCall


def test_default_mcp_servers_catalog():
    servers = default_factfind_mcp_servers()
    assert len(servers) == 1
    assert servers[0].server_name == "fact_find_backends"
    names = {t["name"] for t in servers[0].available_tools}
    assert "get_ica_case_details" in names
    assert "get_trusted_parties" in names


def test_extract_mcp_tools_from_adk_events():
    raw = {
        "raw_events": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "id": "c1",
                                "name": "get_ica_case_details",
                                "args": {"complaintRef": "NC10010556"},
                            }
                        }
                    ]
                }
            },
            {
                "content": {
                    "parts": [
                        {
                            "functionResponse": {
                                "id": "c1",
                                "name": "get_ica_case_details",
                                "response": {"success": True},
                            }
                        }
                    ]
                }
            },
        ]
    }
    tools = extract_mcp_tools_called(raw)
    assert len(tools) == 1
    assert tools[0].name == "get_ica_case_details"
    assert tools[0].args["complaintRef"] == "NC10010556"


def test_mcp_tools_from_tool_calls():
    converted = mcp_tools_from_tool_calls(
        [ToolCall(name="get_contact_notes", input_parameters={"partyId": "68905187"})]
    )
    assert converted[0].name == "get_contact_notes"
    assert converted[0].args["partyId"] == "68905187"
