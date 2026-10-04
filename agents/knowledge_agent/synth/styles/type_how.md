## scenario

An advisor needs to carry out a task and asks the knowledge agent HOW to do it.
The question is sent with question_type "how", so the agent answers with an ordered list of steps.

## task

Generate a "how do I / how should I / what are the steps to" question about a procedure that the
page describes step by step (an action the advisor performs, in a set order).
Only ask about a procedure the page actually lays out. If the page has no procedure, ask how to do
the one action it does describe.

## additional_guidance

Use the words an advisor would use on the phone or in branch, not the page's heading.
Ask about one procedure only, not two.

## input_format

One question in plain UK English, starting with "How" (e.g. "How do I ...?", "How should I ...?").
Maximum 25 words. No yes/no questions, no "why".

## expected_output_format

Numbered steps in the order the page gives them, one action per step, each a short sentence
("1. ...", "2. ..."). 2-8 steps. Only steps that are on the page; keep any warning or condition the
page attaches to a step in that step. No introduction or closing sentence.
