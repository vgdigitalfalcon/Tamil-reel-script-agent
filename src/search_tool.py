"""Web search and reference URL fetching tools with rate-limit resilience."""

import asyncio
import html
import logging
import re
import warnings
from typing import Dict, List, Optional

import httpx

warnings.filterwarnings("ignore", category=RuntimeWarning)

logger = logging.getLogger(__name__)


def search_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Execute a DuckDuckGo web search query and return formatted results.

    Returns an empty list on rate-limit or network failure so callers can fall back gracefully.
    """
    if not query or not query.strip():
        return []

    results: List[Dict[str, str]] = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        ddgs = DDGS()
        raw_results = list(ddgs.text(query, max_results=max_results))
        for item in raw_results:
            url = item.get("href") or item.get("link") or ""
            if url:
                results.append({
                    "title": item.get("title", "Source"),
                    "url": url,
                    "snippet": item.get("body", "").strip(),
                })
    except Exception as e:
        logger.warning(f"DuckDuckGo search rate-limited or failed for query '{query}': {e}")
        return []

    return results


def run_research_queries(queries: List[str], max_per_query: int = 3) -> List[Dict[str, str]]:
    """Run a batch of 3-6 queries, deduplicating results by URL."""
    seen_urls = set()
    aggregated: List[Dict[str, str]] = []

    for q in queries:
        query_results = search_web(q, max_results=max_per_query)
        for res in query_results:
            url = res.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                aggregated.append(res)

    return aggregated


def _extract_html_title_and_text(raw_html: str, max_chars: int = 1200) -> Dict[str, str]:
    """Parse title and readable body snippet via BeautifulSoup when available, else regex."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else "Client Reference Page"
        text = " ".join(soup.get_text(" ", strip=True).split())
        return {"title": title[:160], "snippet": text[:max_chars]}
    except ImportError:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
        title = html.unescape(title_match.group(1).strip()) if title_match else "Client Reference Page"
        cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        text = " ".join(html.unescape(cleaned).split())
        return {"title": title[:160], "snippet": text[:max_chars]}


def fetch_reference_url(url: str, timeout: float = 8.0) -> Optional[Dict[str, str]]:
    """Synchronously fetch and extract clean text from an optional client reference URL."""
    if not url or not url.strip().startswith(("http://", "https://")):
        return None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url.strip(), headers={"User-Agent": "ScriptFalconBot/2.0"})
            resp.raise_for_status()
            parsed = _extract_html_title_and_text(resp.text)
            if not parsed["snippet"]:
                return None
            return {
                "title": parsed["title"],
                "url": str(resp.url),
                "snippet": parsed["snippet"],
            }
    except Exception as exc:
        logger.warning(f"Reference URL fetch failed for '{url}': {exc}")
        return None


async def async_fetch_reference_url(url: str, timeout: float = 8.0) -> Optional[Dict[str, str]]:
    """Asynchronously fetch and extract clean text from an optional client reference URL."""
    if not url or not url.strip().startswith(("http://", "https://")):
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url.strip(), headers={"User-Agent": "ScriptFalconBot/2.0"})
            resp.raise_for_status()
            parsed = _extract_html_title_and_text(resp.text)
            if not parsed["snippet"]:
                return None
            return {
                "title": parsed["title"],
                "url": str(resp.url),
                "snippet": parsed["snippet"],
            }
    except Exception as exc:
        logger.warning(f"Async reference URL fetch failed for '{url}': {exc}")
        return None


async def async_run_research_queries(queries: List[str], max_per_query: int = 3) -> List[Dict[str, str]]:
    """Run DuckDuckGo queries in a worker thread without blocking the asyncio event loop."""
    return await asyncio.to_thread(run_research_queries, queries, max_per_query)
