"""
Everything that talks to another system over HTTP:

  adk_client.py      the agent under test (Google ADK)
  cortex_client.py   the judge / generator model, through the CORTEX gateway
  athena_client.py   the Hive Athena MCP server (knowledge-base pages for the synthesizer)

Change a file here when an endpoint, header or auth scheme changes — nothing else should need to.
"""
