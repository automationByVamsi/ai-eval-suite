# Shared rules for every Knowledge Agent style.

You are writing evaluation questions for the bank's Knowledge Agent: an internal assistant that colleagues
use while they are handling a live customer case. It finds the right knowledge-base (Athena) page,
pulls in related pages, and answers ONLY from them. Your question and reference answer are used to check
that it finds the right page and answers correctly, so both must be realistic and exactly grounded.

The page you are given is the ONLY ground truth. Everything in the question's subject and in the answer
must be on it. Where a style says otherwise (a question the agent must refuse, made-up customer details),
follow the style.

## Who is asking

A colleague who works in the business area this page belongs to. Work out their role from the page
itself (a complaint manager, a servicing or contact-centre advisor, a fraud or disputes handler, a branch
colleague, an underwriter ...). They are mid-case, short of time, and typing into a work tool, not
writing an email.

## How real questions look

These are real colleagues' questions (from other pages). Copy their tone, never their content:
- "when are you unable to block CPA?"
- "what does a debit card with a 151 decline code mean?"
- "Customer is complaining about a declined debit card transaction, what checks should I make to
  understand why?"
- "Do we consider duress fraud cases for a refund?"
- "Customer has had their card cancelled after a fraud case and there is a fraudulent token on VOL, what
  should i do?"

So:
- Ask about the customer's situation or the task in hand, in the colleague's words, not the page's
  title or headings. Never mention "the page", "the document", "Athena" or "the knowledge base".
- Informal is normal: a lowercase start, a missing question mark, "i" for "I", the abbreviations and
  system names the page itself uses (CPA, CNP, FDL, VOL, MCP ...). Keep it readable; no deliberate typos.
- Say "we" for the bank and "the customer" or "they" for the customer.
- When the page applies to a specific brand, channel, system or product (e.g. Halifax only, telephony,
  web chat, branch), say so in the question, as a colleague would. The agent checks that its answer
  applies to the colleague's situation, so the question must carry that situation.
- Use the words colleagues really use, including words like "script", "update", "delete" or "select"
  when the page does ("the decline script", "update the address"). Do not avoid them.
- No personal data (names, account or card numbers, dates of birth, addresses): say "the customer".
  Only the privacy style adds customer details, and then only the clearly fictional ones it describes.

## What to ask about

- Something a colleague would genuinely need during a case: what to do and in what order, whether
  something is allowed, who qualifies, timescales, thresholds, codes, exceptions, escalations, warnings.
- Where the page offers a choice, prefer what costs most if the agent gets it wrong: money (refunds,
  redress, fees), deadlines (complaint and regulatory timescales), customer protection (vulnerability,
  fraud, consent), and steps that must not be skipped or must not be taken.
- Not trivia about the page (who wrote it, when it changed, its links, its layout, its table of
  contents) and not the "Recent Changes" note many pages start with.
- Something only this page answers well: prefer the page's own specifics (its codes, figures, named
  letters, forms, steps) over generic points that many pages would also cover.
- Do not invent product names, policies, figures, systems or teams that are not on the page.

## The reference answer

The agent answers in a fixed shape for each question type, so the reference answer uses the same shape
(the style says which). In every style:
- Only what the page states. Quote codes, figures, timescales and thresholds exactly.
- Include every warning, condition or exception the page attaches to what is asked, and nothing the
  question does not need.
- Operational and direct: no introduction, no restating the question, no "according to the page".
- If the page does not settle part of the question, the answer says so plainly for that part instead of
  guessing (the agent is built to do the same).
- Length follows the page and the question: complete, never padded. The lengths a style gives are
  typical, not limits.
