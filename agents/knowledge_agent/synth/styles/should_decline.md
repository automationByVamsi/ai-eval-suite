## scenario

An advisor asks something close to the page's topic that the page does NOT answer: a figure, rule,
product or process the page never mentions. The knowledge agent should say it can't answer from the
knowledge base rather than invent an answer. These cases test correct abstention (suite: should_decline).

## task

Generate one question that sounds like it belongs to this page's topic but whose answer is not on the
page. Vary across questions:
- a specific figure, fee, rate or deadline the page doesn't give;
- a related process or product the page doesn't cover;
- an ambiguous ask with too little detail to answer from the page ("What's the limit?").
Check against the page: if the page answers the question, even partly, choose another.

## additional_guidance

Keep it plausible: a question a real advisor might ask, in the same area as the page. Don't ask about
things clearly unrelated to banking, and don't ask for personal opinions.

## input_format

One question in plain UK English, advisor tone. Maximum 30 words.

## expected_output_format

One or two sentences saying the knowledge base page does not cover this (name what is missing, e.g.
"The page does not give a fee for ..."), and that the advisor should check the relevant policy or
team. Do not attempt an answer.
