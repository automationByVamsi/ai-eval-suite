## scenario

An advisor wants to understand the reason behind a rule or step and asks the knowledge agent WHY.
The question is sent with question_type "why", so the agent answers with a reasoned explanation.

## task

Generate a "why do we / why must / why is" question about a rule, requirement or step whose
REASON the page states (e.g. "because ...", "this ensures ...", "to protect ...").
If the page gives no reason for anything, ask about the stated purpose of the process instead.
Never ask why about something the page gives no reason for.

## additional_guidance

The reason must come from the page. Do not rely on general banking knowledge for the "because".

## input_format

One question in plain UK English, starting with "Why". Maximum 20 words.

## expected_output_format

2-4 complete sentences: the rule, then the reason(s) the page gives for it, in the page's terms.
No reasons that are not on the page.
