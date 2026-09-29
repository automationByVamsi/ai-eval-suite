Evaluate whether the FactFind summary is honest about missing or failed
backend data, using the aggregated payload context (including error markers).

Score higher when:
- Failed Trusted Parties / empty trusted lists are stated as none identified
  (or equivalent), not replaced with invented parties
- Failed contact notes or holdings are not silently filled with fake data
- Related parties from customer holdings are still shown when available, even
  if Trusted Parties API failed
- The agent does not claim successful retrieval for sources marked as errors

Score lower when:
- The summary invents trusted parties, notes, balances, or holdings absent
  from context
- API failures in context are ignored and positive data is fabricated
