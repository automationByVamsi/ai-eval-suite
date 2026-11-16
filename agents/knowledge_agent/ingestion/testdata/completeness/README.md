Test cases for the `completeness` suite (Pedro's test 1): one per domain.

`input.page_id` is the domain's root page in Athena; `"check": "completeness"` tells client.py to compare
the whole page tree with the pipeline's buckets. Add `"folder"` only if the bucket folder isn't the root's
name in lower_snake_case (e.g. "Customer Vulnerability Hub 2" -> customer_vulnerability_hub_2).

    make run AGENT=knowledge_agent/ingestion SUITE=completeness
