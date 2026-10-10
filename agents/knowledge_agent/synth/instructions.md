# Shared rules for every Knowledge Agent style.

The page you are given is from the bank's internal knowledge base (Athena). Use ONLY its content as
ground truth.

When writing questions:
- Sound like a bank colleague (advisor, complaints handler, servicing team) asking an internal
  knowledge tool, in UK English.
- Prefer concrete operational topics: what to do, in what order, who it applies to, timescales,
  thresholds, formats, exceptions and warnings.
- Avoid trivia about the page itself: headings, HTML, table of contents, links, edit history.
- Do not invent product names, policies, figures or teams that are not on the page.
- One question per test case; do not stack several unrelated questions.

When writing expected answers:
- Stay faithful to the page; quote figures, timescales and thresholds exactly.
- Call out warnings, exceptions and conditions the page attaches to what is asked.
- Use the answer shape the style asks for (steps, definitions, yes/no + why, or a summary).
- Let the page and the question decide the length: complete, with nothing the question needs left out,
  and nothing added to make it longer. The lengths in a style are typical, not limits.
