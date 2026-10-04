## scenario

An advisor checks whether something is allowed, required or possible and asks a YES/NO question.
The question is sent with question_type "yes_no", so the agent answers yes or no with an explanation.

## task

Generate a closed question ("Can I ...?", "Do I need to ...?", "Is it possible to ...?",
"Should I ...?") that the page answers clearly with yes or no.
Across your questions, make some whose correct answer is NO — for example about something the page
says is not allowed, not required, or not possible. Do not always pick a "yes".

## additional_guidance

The page must settle the answer. If it only says "it depends", state the condition in the question
so that the page gives a clear yes or no for it.

## input_format

One closed question in plain UK English that can be answered yes or no. Maximum 25 words.

## expected_output_format

Start with "Yes." or "No.", then 1-3 sentences explaining why, taken from the page, including any
condition or exception the page attaches.
