## scenario

An advisor needs step-by-step guidance on a task or process described on an
Athena page, and asks the internal knowledge agent for the ordered procedure.

## task

Generate a question asking how to carry out a specific process described on
the page. The expected answer should enumerate the steps in the correct order.
Do not invent steps or requirements not stated on the page.

## input_format

One sentence beginning "How do I…", "What are the steps to…", or
"What is the process for…". UK English, advisor tone. Maximum 25 words.

## expected_output_format

A numbered list of the exact steps found on the page, each step a complete
sentence. Preserve the ordering from the page. Include preconditions or
warnings only when explicitly stated on the page. No invented policy.
