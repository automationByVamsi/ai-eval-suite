## scenario

An advisor encounters an edge case or exception and asks the internal
knowledge agent what rule or action applies under a specific condition.
The answer is fully derivable from one Athena page.

## task

Generate a question that states a condition explicitly and asks for the
applicable rule, threshold, or action. The answer must come entirely from
the page content.

## additional_guidance

Conditional questions may also cover exclusions.

Examples:

- Which customers are excluded from this process?
- Under what circumstances does this process not apply?

Where exclusions are explicitly stated, prioritise them.

## input_format

One or two sentences. State the condition explicitly
(e.g. "If the customer is on a paper-free account…").
UK English, advisor tone. Maximum 35 words.

## expected_output_format

A direct answer identifying the rule or action that applies under the stated
condition. Reference specific thresholds, exceptions, or limitations from the
page. No invented policy. Clearly flag any exception using the page's own
language.
