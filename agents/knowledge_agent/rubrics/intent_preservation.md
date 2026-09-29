Determine whether the rewritten query (actual output) preserves the original
intent of the user's question (input). The rewrite may add clarifying detail,
correct grammar, or expand abbreviations, but it must NOT:

- change what the user is actually asking for
- introduce a new topic that wasn't implied by the original question
- drop a constraint the user stated (e.g. a specific product, date, or persona)

Score higher when the rewritten query a human would agree means the same
thing as the original question. Score lower if the rewrite drifts in meaning,
even if it is fluent, well-formed text.
