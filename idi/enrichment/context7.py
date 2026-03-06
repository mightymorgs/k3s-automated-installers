"""Context7 API client -- search libraries and fetch documentation snippets."""
from __future__ import annotations

import httpx

BASE_URL = "https://context7.com/api/v2"


def search_library(query: str) -> str | None:
    """Search for a Context7 library ID by name. Returns best match ID or None."""
    resp = httpx.get(f"{BASE_URL}/libs/search", params={"query": query})
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    if isinstance(results, list) and results:
        return results[0]["id"]
    return None


def fetch_snippets(library_id: str, query: str, max_tokens: int = 5000) -> list[dict]:
    """Fetch documentation snippets for a query within a library."""
    resp = httpx.get(
        f"{BASE_URL}/context",
        params={"libraryId": library_id, "query": query, "type": "json", "tokens": max_tokens},
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("codeSnippets", [])
