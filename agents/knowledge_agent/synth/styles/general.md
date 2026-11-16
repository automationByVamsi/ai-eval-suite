## scenario

SIMPLE untyped question. A busy colleague types a quick question without choosing a question type, so
it is sent as plain text and the agent replies with a direct summary.
Simple means: one ask about one thing this page covers, answered from one part of the page. No "and",
"if", "when", "but", "also" or "while" clauses (the agent would treat the question as complex).

## task

Generate one quick, natural question the page answers directly. Vary across questions:
- terse, keyword-style, the way it is typed mid-call ("refund timescale for chargebacks?", "who handles
  CNP disputes");
- a one-line ask in plain words ("where do i log a vulnerability for a customer").
The answer must come entirely from the page.

## additional_guidance

Use everyday colleague wording, not the page heading, so the agent is tested on how people really ask.
Do not start with a question-type word on purpose; write it as it would naturally come out.

## input_format

Plain UK English, colleague tone: one short line, at most 15 words. No "and"/"if"/"when" clauses.

## expected_output_format

A direct answer in 1-3 complete sentences using facts from the page only. Quote codes, figures,
timescales and thresholds exactly; include a warning or exception only if the page attaches it to what
is asked.
