## scenario

An advisor meets a term, level, category or rule and asks the knowledge agent WHAT it is or means.
The question is sent with question_type "what", so the agent answers with definitions.

## task

Generate a "what is / what does ... mean / what counts as" question about a term, category, level
or concept that the page defines or explains.
Only ask about something the page actually defines.

## additional_guidance

Prefer terms an advisor would genuinely need explained (a verification level, a type of support
need, an account category) over everyday words.

## input_format

One question in plain UK English, starting with "What" (e.g. "What is ...?", "What does ... mean?").
Maximum 20 words. No "how do I", no yes/no questions.

## expected_output_format

The term followed by its meaning as the page gives it: "<term>: <meaning>". If the page defines
closely related terms the question needs (e.g. two levels), give each on its own line in the same
form. 1-4 lines. Use the page's own definitions; no examples the page doesn't give.
