Test cases for the `markdown` suite: one per page the preprocessing pipeline stored.
They are written from the buckets themselves (sign in first):

    make gcloud-auth
    make ingestion-cases                 # or PER_DOMAIN=5 for a sample, DOMAIN=<folder> for one domain

Each case is `<domain>/KA_MD_<page_id>.json` with the page id and its exact Markdown / metadata files.
