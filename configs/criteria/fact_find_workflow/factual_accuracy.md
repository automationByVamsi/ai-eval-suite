Score how accurately the FactFind summary reproduces key identifiers and
values from the aggregated payload context.

Critical fields to check when present in context:
- Complaint reference (NC########)
- Party ID(s)
- Customer full name / title
- Account number(s) associated with the complaint
- Support need descriptions and consent statuses
- Contact note dates / high-level outcomes

Score higher when identifiers and numeric/date values match the context
exactly (allowing only formatting differences such as date DD/MM/YYYY vs ISO).

Score lower when IDs, names, balances, or dates are wrong, swapped, or rounded
in a misleading way.
