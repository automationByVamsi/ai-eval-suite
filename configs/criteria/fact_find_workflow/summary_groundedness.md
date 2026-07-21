Determine whether every factual claim in the Customer FactFind Summary
(actual output) is directly supported by the aggregated payload context
(retrieval context). This mirrors the ADK UI "Groundedness Check".

Score higher when:
- Customer name, party ID, address, DOB, marital status match the context
- Support needs, account holdings, related parties, and contact notes are
  consistent with the aggregated sources
- The agent does not invent balances, parties, or notes absent from context

Score lower when:
- Claims contradict the aggregated payload
- Details are hallucinated or mixed across parties/accounts
- Unsupported qualitative statements are presented as facts
