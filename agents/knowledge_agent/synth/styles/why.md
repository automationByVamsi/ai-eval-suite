## scenario

SIMPLE "why" question. A colleague wants the reason behind one rule, requirement or step, often because
the customer is asking them to explain it. It is sent with question_type "why", so the agent answers
with a summary of the reason the page gives.
Simple means: one ask about one rule, answered from one part of this page. No "and", "if", "when",
"but", "also" or "while" clauses (the agent would treat the question as complex).

## task

Generate one "why" question about a rule, requirement or step whose REASON the page states ("because
...", "this ensures ...", "to protect ...", "so that ..."). Vary across questions: why a step is needed,
why a restriction exists, why something must be done within a timescale, why the customer is asked for
something. Only ask about something the page gives a reason for.

## additional_guidance

The reason must come from the page; never from general banking knowledge. Phrase it as a colleague would
("why do we have to ...", "why can't we ...", "customer's asking why we ...").

## input_format

One question in UK English, colleague tone, at most 25 words, usually starting with "why".

## expected_output_format

A short passage (usually 1-3 sentences) giving the reason the page states, in the page's terms; when the
page gives several reasons, all of them, most important first. Include a condition only if the page
attaches it to the reason. No reasons that are not on the page.
