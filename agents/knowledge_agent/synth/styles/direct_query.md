## scenario

An advisor asks a single, direct factual question to the internal knowledge agent.
The question is fully answerable from the content of one Athena page alone.

## task

Generate a short factual question that a busy advisor would type in one line.
The question must be completely answerable from the provided page text.
Do not combine multiple questions or introduce conditions not on the page.

## additional_guidance

Where appropriate, use language that a colleague might naturally use,
even if the wording is slightly different from the page.

Examples:

- "complaint manager" instead of "complaint handler"
- "alternative format" instead of "accessible format"
- "digital correspondence" instead of "paper-free account"

This helps test whether the knowledge agent can understand common
terminology and different ways of asking the same question.

The question must still relate to information that is explicitly
covered on the page.
Do not introduce new concepts, products, policies, or processes that
are not mentioned on the page.

## input_format

One sentence in plain UK English. No multi-part asks, no hypotheticals,
no comparisons. Maximum 20 words.

## expected_output_format

2-4 complete sentences. Facts only, taken directly from the page.
No hedging, no invented policy. No phrases such as "It depends" or "may vary"
unless those exact qualifications appear on the page.
Quote specific figures, timescales, or thresholds exactly as they appear.
