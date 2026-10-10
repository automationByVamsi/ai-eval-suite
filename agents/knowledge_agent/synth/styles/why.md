## scenario

An advisor wants to understand the reason behind a rule, requirement or step and asks the knowledge
agent WHY. The question is sent with question_type "why", so the agent answers with a reasoned summary.

## task

Generate one "why" question about a rule, requirement or step whose REASON the page states ("because
...", "this ensures ...", "to protect ...", "so that ..."). Vary across questions: why a step is needed,
why a rule or restriction exists, why an exception or condition applies. If the page gives no reason
for anything, ask about the stated purpose of the process instead. Never ask why about something the
page gives no reason for.

## additional_guidance

The reason must come from the page; do not rely on general banking knowledge for the "because".

## input_format

One question in plain UK English, advisor tone, starting with "Why". Maximum 25 words.

## expected_output_format

The rule or step, then every reason the page gives for it, in the page's terms, as complete sentences:
usually 2-4 sentences, more when the page gives several reasons or a reason with a condition attached.
Include a condition or exception only if the page attaches it to the reason. No reasons that are not
on the page.
