"""HTML report (make report): one self-contained file with the dashboard's views."""

import re

from src.reporting.html_report import _markdown, write_report
from src.runners.suite_runner import run_suite


def test_report_is_one_self_contained_file(tmp_path):
    run = run_suite("knowledge_agent", "sanity", offline=True, judges=False)
    out = write_report(run, tmp_path / "r.html")
    page = out.read_text()
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert "Overview" in page and "Test cases (2)" in page and "Release targets" in page
    assert "TC_002" in page and "TC_012" in page
    assert not re.search(r'<(script|link)[^>]+(src|href)=', page)        # nothing loaded from outside


def test_markdown_answers_render_lists_and_bold():
    html = _markdown("Steps:\n- **Open** MCP\n- Add the need\n\n1. one\n2. two")
    assert "<ul><li><b>Open</b> MCP</li><li>Add the need</li></ul>" in html
    assert "<ol><li>one</li><li>two</li></ol>" in html
    assert "&lt;script&gt;" in _markdown("<script>")                       # text is escaped
