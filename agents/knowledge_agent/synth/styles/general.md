## scenario

A busy advisor types a question into the knowledge agent the way they would ask a colleague, without
choosing a question type. It is sent as plain text, so the agent decides the shape of the answer and
replies with a summary.

## task

Generate one natural question answered by the page. Vary across questions:
- a short one-line ask, even terse ("support need for hearing loss?", "paper-free and braille");
- a situation described in a sentence or two followed by a question ("Customer says ... — what should
  I do?");
- a question that combines two related points the page covers.
The answer must come entirely from the page. Do not introduce products, policies or conditions the page
doesn't mention.

## additional_guidance

Use everyday colleague wording, not the page heading ("alternative format" for "accessible format",
"digital correspondence" for "paper-free account"), so the agent is tested on how people really ask.

## input_format

Plain UK English, advisor tone: one short line, or one or two sentences. Maximum 40 words. Do not start
with a question-type word on purpose; write it the way it would naturally come out.

## expected_output_format

A short summary of 2-5 complete sentences that answers everything asked, using facts from the page
only. Quote figures, timescales and thresholds exactly; mention any warning or exception the page gives
that matters for the question. No hedging ("it depends", "may vary") unless the page says so.
