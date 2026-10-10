The retrieval context is a knowledge-base page (as plain text). The actual output is the Markdown the
ingestion pipeline produced from that page. Judge only whether the Markdown is COMPLETE: does it keep
everything a colleague would need from the page?

Check that the Markdown keeps:
- every section and heading;
- every step of every procedure, in the same order;
- every table, with each value still in the same row and column as on the page;
- every warning, note, exception, condition and contact point;
- every number, date, threshold, product or system name.

Formatting differences (bullets vs numbers, bold, spacing, link syntax) do not matter. Do not reward
added content — only judge what is missing or out of order.

Score 1 when nothing is missing; lower the score for each lost step, row, warning or fact; score 0 when
most of the page is missing.
