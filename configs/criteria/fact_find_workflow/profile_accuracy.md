Evaluate Customer Profile accuracy against the aggregated payload context.

Check these fields when present in context:
- Full name / title (Primary Customer)
- Party ID
- Current address (lines + postcode)
- Date of birth and age
- Marital status
- Party ID created / time-with-bank date

Score higher when profile fields match the context exactly (formatting
differences such as date layout are acceptable).

Score lower when name parts, IDs, address, DOB, or marital status disagree
with context or are missing without explanation.
