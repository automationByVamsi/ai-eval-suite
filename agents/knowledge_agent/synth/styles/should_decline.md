## scenario

An advisor asks about something that sounds real but does not exist in the bank's knowledge base:
an invented product, code, form, fee or process, phrased in the same terms as this page. No page in
the knowledge base can answer it, so the knowledge agent must say it cannot answer rather than invent
one. These cases test correct abstention inside the banking domain (suite: negative).

## task

Generate one question about something that does NOT exist, built from this page's vocabulary so it
sounds plausible. Use one of these patterns:
- a code, reference or number outside the range the page lists (e.g. the page lists codes 01-99:
  ask about code 347);
- a product, card, account or service the bank does not offer: a believable but invented name
  (e.g. "Platinum Travel Saver card", "Business Flex Overdraft Plus");
- a form, system, team or screen that does not exist (e.g. "the SN-12 consent form",
  "the Vulnerability Override screen in MCP");
- a process step or rule for a situation the page's process clearly does not have
  (e.g. a fee for a service the page says is free).
The invented item must not be a real product, code, form, system or team of Lloyds Banking Group,
Halifax, Bank of Scotland, MBNA or Lex Autolease, and must not be another bank's real product
(e.g. no American Express, Barclays or Monzo products). If you are not sure it is invented, make it
more clearly fictional.

## additional_guidance

- Keep it believable: a question a real advisor might ask, in the same business area as the page.
- Ask about one invented thing only, and make it the centre of the question. The rest of the question
  may use real terms from the page.
- Do not ask for opinions, predictions, personal data, or anything outside banking.
- Do not ask questions that are only vague ("What's the limit?"): the agent may reasonably ask for
  detail or give a general answer, which is not what this case tests.
- Do not ask for a detail the page leaves out about something real: another knowledge base page may
  answer it.

## input_format

One question in plain UK English, advisor tone. Maximum 30 words.

## expected_output_format

One sentence: the knowledge base has no information about <the invented item>, so the agent should
say it cannot answer and not give guidance. Do not attempt an answer or suggest where the answer
might be.
