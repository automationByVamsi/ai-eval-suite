Evaluate whether the Account Holdings section correctly associates the
complaint account from the aggregated payload.

Score higher when:
- The account number linked to the complaint (accountNumberFull / Classic
  account in context) appears in the summary
- It is explicitly marked as associated with the complaint when that is how
  the agent UI presents it
- Account status, role (e.g. HOLDER_OF_PRODUCT), and opened date match context
- Balances and overdraft figures match context (including £0.00)

Score lower when:
- The wrong account is highlighted as complaint-associated
- The complaint account is omitted while other accounts are emphasised
- Financial figures disagree with context
