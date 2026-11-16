"""
Negative check for the hallucination judge: does it FAIL answers that invent things?

Takes the real Athena text of the pages the agent used for TC_002 ("How do I add a support need?"),
then asks the hallucination judge (the same code a suite run uses) to score four answers:
one taken from those pages (should PASS) and three broken on purpose (should FAIL).

Run from the repo root (needs Pegasus, CORTEX and Athena, like a live run):
    uv run python negative_hallucination_check.py
"""

from src.core.agent_config import load_agent
from src.fields import lookup
from src.metrics.judges import run_judge

QUESTION = "How do I add a support need?"
PAGES = ["40345", "40017", "40015"]          # TC_002's evidence pages (anchor + related)

GOOD = ("In Colleague Tools open 'Customer Support Needs'. In 'Add a new customer support need' choose the "
        "support required, set a review date if needed, add a clear note in 'Additional information', select "
        "the consent scenario and click 'Add support need'.")

SCENARIOS = {
    "control: answer taken from the pages": (GOOD, "PASS"),
    "invented facts (30-day expiry, £25 fee)": (
        GOOD + " The support need is deleted automatically after 30 days, and the customer is charged a "
               "£25 admin fee for each one.", "FAIL"),
    "contradicts the pages (no consent needed)": (
        GOOD.replace("select the consent scenario", "you do not need the customer's consent")
        + " Consent is never required when adding a support need.", "FAIL"),
    "off topic (answers a different question)": (
        "To reset a customer's online banking password, ask them to use 'Forgotten password' on the login "
        "page and confirm their identity with a one-time passcode.", "FAIL"),
}

agent = load_agent("knowledge_agent")
contexts, problems = lookup.texts(agent.folder, "get_page_content_from_athena", PAGES, offline=False)
if problems:
    raise SystemExit(f"Could not fetch the pages from Athena: {problems}")
print(f"Pages {PAGES}: {[len(c) for c in contexts]} characters of text\n")

spec = agent.metrics["hallucination"]
for name, (answer, expected) in SCENARIOS.items():
    result = run_judge("hallucination", spec, {"question": QUESTION, "answer": answer, "contexts": contexts})
    verdict = "as expected" if result.status.upper() == expected else "UNEXPECTED"
    print(f"{result.status.upper():5} score={result.score}  expected {expected:4} -> {verdict}   {name}")
    print(f"      {result.reason[:300]}\n")
