## scenario

SIMPLE "how" question. A colleague needs to carry out one task and asks HOW to do it. It is sent with
question_type "how", so the agent answers with an ordered list of steps.
Simple means: one ask about one task, the task this page is mainly about, answered by one procedure on
this page. The agent treats a question with several asks, or one joined by "and", "if", "when", "but",
"also" or "while", as complex and splits it, so a simple question has none of those.

## task

Generate one "how" question about the main procedure the page lays out (actions the colleague performs in
a set order). Vary across questions:
- a direct ask ("how do I ...", "what are the steps to ...", "what's the process for ...");
- the task stated as the customer's request ("customer wants to ..., how do I set that up");
- terse, the way it is typed mid-call ("process for raising a ...").
If the page has no step-by-step procedure, ask how to do the one action it does describe.

## additional_guidance

Name the task the way a colleague would (e.g. "add a support need", "send the 8 week letter"), not by
the page title. No conditions, edge cases or second questions: those belong to the complex style.

## input_format

One question in UK English, colleague tone, at most 25 words. No yes/no questions, no "why", no
"and"/"if"/"when" clauses.

## expected_output_format

Numbered steps in the order the page gives them, one action per step, each a short imperative sentence
("1. ...", "2. ..."). Every step the page gives for this procedure, including any branch, check or
exception the page puts inside it; don't merge steps to make the list shorter or split one to make it
longer. Keep any warning or prerequisite the page attaches to a step in that step. Nothing that is not on
the page; no introduction or closing sentence.
