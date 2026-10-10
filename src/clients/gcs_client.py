"""
Read files from Google Cloud Storage buckets, signed in as you.

Sign in once with `make gcloud-auth` (browser SSO; Google's "application default credentials", the
same as the agent repos use). This file asks gcloud for an access token and downloads with plain
HTTPS, so no Google Python package is needed:

    read_text("my-bucket", "folder/40345.md")   -> the file's text, or None when it doesn't exist

Certificate checks follow VERIFY_TLS / CA_BUNDLE (src/core/tls.py), like every other client.
"""

from __future__ import annotations

import functools
import subprocess
from urllib.parse import quote

import httpx

from src.core import tls

NOT_SIGNED_IN = "not signed in to Google Cloud — run: make gcloud-auth"


@functools.cache
def access_token() -> str:
    """Your Google access token (valid ~1 hour, so one per run is enough)."""
    try:
        done = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"],
                              capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError("gcloud is not installed (Google Cloud SDK) — install it, then: make gcloud-auth") from None
    if done.returncode != 0 or not done.stdout.strip():
        raise RuntimeError(NOT_SIGNED_IN)
    return done.stdout.strip()


def read_text(bucket: str, path: str) -> str | None:
    """The text of gs://<bucket>/<path>, or None when there is no such file."""
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(path, safe='')}?alt=media"
    response = httpx.get(url, headers={"Authorization": f"Bearer {access_token()}"},
                         verify=tls.httpx_verify(), timeout=60)
    if response.status_code == 404:
        return None
    if response.status_code in (401, 403):
        raise RuntimeError(f"no access to gs://{bucket}/{path} (HTTP {response.status_code}) — "
                           f"run make gcloud-auth, or ask for read access to the bucket")
    response.raise_for_status()
    return response.text
