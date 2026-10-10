## scenario

An advisor needs to carry out a task and asks the knowledge agent HOW to do it. The question is sent
with question_type "how", so the agent answers with an ordered list of steps.
This style covers simple procedures ("How do I add a support need?") and complex ones: several
conditions at once, an edge case, or "what should I do if ..." situations that the page still answers
with a procedure.

## task

Generate one "how" question about a procedure the page lays out (actions the advisor performs in a set
order). Vary across questions:
- a plain procedure ("How do I ...?", "What are the steps to ...?", "What is the process for ...?");
- a procedure under a condition the page covers ("How do I ... when the customer is ...?");
- a multi-constraint case the page answers step by step ("How should I ... if ... and ...?").
Only ask about a procedure the page actually describes; if the page has no procedure, ask how to do the
one action it does describe. One procedure per question.

## additional_guidance

Use the words an advisor would use on the phone or in branch, not the page heading (e.g. "alternative
format" for "accessible format", "complaint manager" for "complaint handler"), but only about what the
page covers. Do not introduce conditions, products or steps the page doesn't mention.

## input_format

One question in plain UK English, advisor tone, starting with "How" or "What are the steps" / "What is
the process". Maximum 35 words. No yes/no questions, no "why".

## expected_output_format

Numbered steps in the order the page gives them, one action per step, each a short sentence ("1. ...",
"2. ..."). 2-8 steps. Where the question has a condition, include the steps and any exception that
apply under it. Keep any warning or prerequisite the page attaches to a step in that step. Only steps
that are on the page; no introduction or closing sentence.
