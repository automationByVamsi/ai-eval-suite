"""
make ingestion-cases: one test case per page the preprocessing pipeline stored, from the buckets themselves.

    make gcloud-auth
    make ingestion-cases                          # every page: prints pages per domain, writes the cases
    make ingestion-cases PER_DOMAIN=5             # a sample: the first 5 pages of each domain
    make ingestion-cases DOMAIN=<domain>          # one domain only

Lists every .md file in the Markdown bucket and every .json in the metadata bucket (agent.yaml
`connection:`), takes each file's page id (the last number of 3+ digits in its path) and domain (its
first folder), and writes testdata/markdown/<domain>/KA_MD_<page_id>.json with the exact file paths.
Case files that already exist are left alone (delete the folder to start again).
"""

import argparse
import json
import re
import sys
from collections import Counter

from src.clients import gcs_client
from src.core.agent_config import load_agent


def main(argv=None):
    args = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    args.add_argument("--per-domain", type=int, help="only the first N pages of each domain")
    args.add_argument("--domain", help="only this domain (its folder name in the bucket)")
    args = args.parse_args(argv)

    agent = load_agent("knowledge_agent/ingestion")
    md_bucket, json_bucket = agent.connection["md_bucket"], agent.connection["metadata_bucket"]
    markdown, skipped = by_page(gcs_client.list_names(md_bucket), ".md")
    metadata, _ = by_page(gcs_client.list_names(json_bucket), ".json")

    print(f"\ngs://{md_bucket}: {len(markdown)} pages with Markdown "
          f"({len(metadata)} with metadata in gs://{json_bucket})")
    for path in list(markdown.values())[:3]:
        print(f"  e.g. {path}")
    if skipped:
        print(f"  {len(skipped)} .md file(s) without a page id in the path, e.g. {skipped[:3]}")
    domains = Counter(domain_of(path) for path in markdown.values())
    print("\nPages per domain:")
    for domain, count in sorted(domains.items()):
        print(f"  {domain:<50} {count}")

    folder, written, taken = agent.suite("markdown").testdata, 0, Counter()
    for page_id, path in sorted(markdown.items(), key=lambda item: (domain_of(item[1]), item[1])):
        domain = domain_of(path)
        if args.domain and domain != args.domain:
            continue
        taken[domain] += 1
        if args.per_domain and taken[domain] > args.per_domain:
            continue
        case = folder / domain / f"KA_MD_{page_id}.json"
        if case.exists():
            continue
        case.parent.mkdir(parents=True, exist_ok=True)
        case.write_text(json.dumps({
            "test_case_id": f"KA_MD_{page_id}",
            "description": f"{domain}: Athena page {page_id} -> the pipeline's Markdown keeps its structure and text",
            "input": {"page_id": page_id, "md_path": path, "metadata_path": metadata.get(page_id, "")},
            "expected": {},
            "metadata": {"domain": domain},
        }, indent=2) + "\n")
        written += 1
    print(f"\n{written} new test case(s) in {folder}\n"
          f"Next: make run AGENT=knowledge_agent/ingestion SUITE=markdown JUDGES=0   (checks only, fast)\n")
    return 0


def by_page(names, extension):
    """({page id: file path}, [paths without a page id]) for the files ending in `extension`."""
    found, skipped = {}, []
    for name in names:
        if name.endswith(extension):
            numbers = re.findall(r"\d{3,}", name)
            if numbers:
                found.setdefault(numbers[-1], name)
            else:
                skipped.append(name)
    return found, skipped


def domain_of(path):
    """The first folder of a file path ('customer-vulnerability/40345.md' -> 'customer-vulnerability')."""
    return path.split("/")[0] if "/" in path else "all"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:                 # e.g. not signed in: one line, not a traceback
        sys.exit(f"ERROR: {error}")
