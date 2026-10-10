## scenario

An advisor checks whether something is allowed, required, possible or applicable and asks a YES/NO
question. The question is sent with question_type "yes_no", so the agent answers yes or no with an
explanation. This style covers conditional questions ("If the customer is ..., can I ...?") and
eligibility checks ("Is a customer who ... eligible for ...?").

## task

Generate one closed question the page answers clearly with yes or no. Vary across questions:
- permission or requirement ("Can I ...?", "Do I need to ...?", "Should I ...?");
- a condition or exception stated in the question ("If ..., is it still possible to ...?");
- eligibility ("Is a customer who ... eligible for ...?", "Does this apply to ...?").
Across your questions make some whose correct answer is NO: something the page says is not allowed,
not required, not possible or excluded. Do not always pick a "yes".

## additional_guidance

The page must settle the answer. If the page only says "it depends", put the condition in the question
so that the page gives a clear yes or no for it. Use only exclusions and criteria the page states.

## input_format

One closed question in plain UK English, advisor tone, answerable with yes or no. Maximum 35 words.

## expected_output_format

Start with "Yes." or "No.", then 1-3 sentences explaining why, taken from the page, including any
condition, threshold or exception the page attaches.
