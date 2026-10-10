## scenario

An advisor asks the knowledge agent WHAT something is: a term, level, category or rule, a fact
(format, timescale, threshold, who it applies to), or the eligibility criteria for a service or process.
The question is sent with question_type "what", so the agent answers with definitions.

## task

Generate one "what" question answered by the page. Vary across questions:
- a definition ("What is ...?", "What does ... mean?", "What counts as ...?");
- a direct fact ("What is the timescale for ...?", "What formats are available ...?");
- eligibility or applicability ("What are the eligibility criteria for ...?", "What customers qualify
  for ...?", "What exclusions apply to ...?").
Only ask about something the page defines or states explicitly. For eligibility, use only the criteria,
requirements, age limits, prerequisites and exclusions the page itself gives; never infer a rule.

## additional_guidance

Prefer what an advisor genuinely needs (a verification level, a type of support need, who qualifies, an
exclusion) over everyday words. Colleagues' wording may differ from the page's, but the subject must be
on the page.

## input_format

One question in plain UK English, advisor tone, starting with "What". Maximum 25 words. No "how do I", no
yes/no questions.

## expected_output_format

Definitions in the form "<term>: <meaning>", one per line, using the page's own words. One line for a
single term or fact; one line per term when the question needs related terms (e.g. each level); for
eligibility, one line per criterion or exclusion the page lists ("Age requirement: ...", "Excluded:
...") — all of them, however many. A meaning may be more than one sentence when the page's definition
is. For a fact, the term is the thing asked about ("Timescale: ..."). Quote figures, timescales and
thresholds exactly. Nothing the page doesn't state.
