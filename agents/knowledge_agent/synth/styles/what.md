## scenario

SIMPLE "what" question. A colleague asks WHAT something is: a term, code, level, category, rule, a fact
(timescale, threshold, format, who it applies to) or the criteria for something. It is sent with
question_type "what", so the agent answers with definitions: each term with its meaning.
Simple means: one ask about one thing this page defines or states, answered from one part of the page.
No "and", "if", "when", "but", "also" or "while" clauses (the agent would treat the question as complex).

## task

Generate one "what" question answered by the page. Vary across questions:
- a definition or meaning ("what is ...", "what does ... mean", "what counts as ...");
- a code, level or category the page explains ("what does decline code 51 mean");
- a direct fact or criteria ("what's the timescale for ...", "what are the eligibility criteria for ...").
Only ask about something the page defines or states explicitly. For criteria, use only the requirements,
limits and exclusions the page itself gives; never infer one.

## additional_guidance

Prefer the page's own specifics an advisor needs on a case (a code, a level, a named letter or form, a
threshold) over everyday words anyone knows. The colleague's wording may differ from the page's.

## input_format

One question in UK English, colleague tone, starting with "what" (any case). At most 20 words. No "how do
I", no yes/no questions, no "and"/"if"/"when" clauses.

## expected_output_format

One line per term the question asks about, "<term>: <meaning>", with the term exactly as the page names
it and the meaning in one or two sentences from the page (more only when the page's definition needs
it). For a fact, the term is the thing asked about ("Timescale: ..."); for criteria, one line per
criterion or exclusion the page lists ("Minimum age: ...", "Excluded: ..."), all of them. Quote codes,
figures and thresholds exactly. Do not define terms the question did not ask about.
