## scenario

SIMPLE "yes/no" question. A colleague checks whether something is allowed, required, possible or
applicable. It is sent with question_type "yes_no", so the agent answers yes or no with an explanation.
Simple means: one closed question about one thing, which the page settles without any condition. A
question with an "if", "when" or "and" clause is complex, not simple.

## task

Generate one closed question the page answers clearly with yes or no. Vary across questions:
- permission or requirement ("can we ...", "do I need to ...", "should we ...");
- eligibility or applicability ("is ... eligible for ...", "does this apply to ...", "do we consider
  ... for a refund").
Across your questions make some whose correct answer is NO: something the page says is not allowed, not
required, not possible or excluded. Do not always pick a "yes".

## additional_guidance

The page must settle the answer for everyone the question covers. If the page only gives a yes or no
under a condition, choose another question.

## input_format

One closed question in UK English, colleague tone, answerable with yes or no. At most 20 words. No
"and"/"if"/"when" clauses.

## expected_output_format

"Yes." or "No.", then the explanation from the page: usually 1-2 sentences giving the rule, condition,
threshold or exception behind the answer. No hedging, and no "it depends" unless the page says so.
