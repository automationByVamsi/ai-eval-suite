"""
Knowledge Agent: pull stage outputs out of the trace, and check them.

parse()  -> extra fields judges can use (rewritten_query, anchor_page_content, ...)
checks() -> deterministic checks on top of the standard ones (answer present, keywords)
"""

from evalkit import adk, check


def parse(trace, case):
    rewritten = adk.state(trace, "rewritten_query") or \
        adk.event_json(adk.find_event(trace, "query_rewrite_agent")).get("rewritten_query", "")
    anchor_content = adk.state(trace, "anchor_page_content") or ""
    return {
        "rewritten_query": rewritten,
        "business_area": adk.state(trace, "business_area", ""),
        "anchor_page_id": str(adk.state(trace, "anchor_page_id") or ""),
        "anchor_page_content": anchor_content,
        "decision": adk.state(trace, "decision", ""),
        # Judges like faithfulness read "contexts": the pages the answer was built from.
        # Today the trace only exposes the anchor page; add expanded pages here when it does.
        "contexts": [c for c in [*(trace.get("context") or []), anchor_content] if c],
    }


def checks(fields, case):
    expected = case["expected"]
    results = [
        check("rewritten_query_present", bool(fields["rewritten_query"]), "no rewritten_query in trace"),
        check("anchor_page_id_present", bool(fields["anchor_page_id"]), "no anchor_page_id in trace"),
    ]
    if expected.get("expected_anchor_page_id"):
        want = str(expected["expected_anchor_page_id"])
        results.append(check("anchor_page_id", fields["anchor_page_id"] == want,
                             f"got {fields['anchor_page_id']!r}, expected {want!r}"))
    return results
