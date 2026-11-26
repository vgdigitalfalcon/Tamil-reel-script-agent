"""Web search and reference URL fetching tools with rate-limit resilience."""

import asyncio
import html
import ipaddress
import logging
import re
import socket
import warnings
from typing import Any, Dict, List, NamedTuple, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

warnings.filterwarnings("ignore", category=RuntimeWarning)

logger = logging.getLogger(__name__)


def search_web(
    query: str, max_results: int = 5, timelimit: Optional[str] = None
) -> List[Dict[str, str]]:
    """Execute a DuckDuckGo web search query and return formatted results.

    timelimit: optional recency filter ('d' day, 'w' week, 'm' month, 'y' year).
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
        search_kwargs: Dict[str, Any] = {"max_results": max_results}
        if timelimit:
            search_kwargs["timelimit"] = timelimit
        raw_results = list(ddgs.text(query, **search_kwargs))
        for item in raw_results:
            url = item.get("href") or item.get("link") or ""
            if url:
                results.append(
                    {
                        "title": item.get("title", "Source"),
                        "url": url,
                        "snippet": item.get("body", "").strip(),
                    }
                )
    except Exception as e:
        logger.warning(
            f"DuckDuckGo search rate-limited or failed for query '{query}': {e}"
        )
        return []

    return results


def run_research_queries(
    queries: List[str], max_per_query: int = 3, timelimit: Optional[str] = None
) -> List[Dict[str, str]]:
    """Run a batch of 3-6 queries, deduplicating results by URL."""
    seen_urls = set()
    aggregated: List[Dict[str, str]] = []

    for q in queries:
        query_results = search_web(q, max_results=max_per_query, timelimit=timelimit)
        for res in query_results:
            url = res.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                aggregated.append(res)

    return aggregated


def _extract_html_title_and_text(
    raw_html: str, max_chars: int = 1200
) -> Dict[str, str]:
    """Parse title and readable body snippet via BeautifulSoup when available, else regex."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        title = (
            soup.title.get_text(" ", strip=True)
            if soup.title
            else "Client Reference Page"
        )
        text = " ".join(soup.get_text(" ", strip=True).split())
        return {"title": title[:160], "snippet": text[:max_chars]}
    except ImportError:
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL
        )
        title = (
            html.unescape(title_match.group(1).strip())
            if title_match
            else "Client Reference Page"
        )
        cleaned = re.sub(
            r"<(script|style|noscript)[^>]*>.*?</\1>",
            " ",
            raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        text = " ".join(html.unescape(cleaned).split())
        return {"title": title[:160], "snippet": text[:max_chars]}


_MAX_REDIRECTS = 3
_FETCH_HEADERS = {"User-Agent": "ScriptFalconBot/2.0"}
_MAX_FETCH_BYTES = 2_000_000


class _PinnedTarget(NamedTuple):
    """A URL rewritten to hit one vetted IP, plus what the server must still see."""

    url: str  # same URL with the host replaced by the vetted IP
    host_header: str  # original "host[:port]" for the Host header
    hostname: str  # original hostname, used for TLS SNI + certificate check


def _resolve_public(url: str) -> Optional[_PinnedTarget]:
    """Resolve the host once; return a target pinned to that IP only if EVERY address is public.

    Pinning means the connection goes to the address that was checked, so a DNS answer that
    changes between check and request (DNS rebinding) cannot redirect the fetch to internal
    hosts such as http://db:5432, http://api:8000 or the cloud metadata endpoint.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    port = port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not ip.is_global or ip.is_multicast:
            return None
        ips.append(ip)
    if not ips:
        return None
    ip = ips[0]
    ip_host = f"[{ip}]" if ip.version == 6 else str(ip)
    default_port = 443 if parts.scheme == "https" else 80
    netloc = ip_host if port == default_port else f"{ip_host}:{port}"
    host_header = parts.hostname if port == default_port else f"{parts.hostname}:{port}"
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    return _PinnedTarget(pinned, host_header, parts.hostname)


def _is_public_url(url: str) -> bool:
    """True only if the URL is http(s) and every address its host resolves to is public."""
    return _resolve_public(url) is not None


def _request_kwargs(target: _PinnedTarget) -> Dict:
    return {
        "headers": {**_FETCH_HEADERS, "Host": target.host_header},
        # TLS: send SNI and verify the certificate for the real hostname, not the IP.
        "extensions": {"sni_hostname": target.hostname},
    }


def _decode_capped(chunks: List[bytes], encoding: Optional[str]) -> str:
    return b"".join(chunks).decode(encoding or "utf-8", errors="replace")


def _parse_reference_text(raw_html: str, final_url: str) -> Optional[Dict[str, str]]:
    parsed = _extract_html_title_and_text(raw_html)
    if not parsed["snippet"]:
        return None
    return {"title": parsed["title"], "url": final_url, "snippet": parsed["snippet"]}


def fetch_reference_url(url: str, timeout: float = 8.0) -> Optional[Dict[str, str]]:
    """Synchronously fetch and extract clean text from an optional client reference URL."""
    if not url or not url.strip().startswith(("http://", "https://")):
        return None
    current = url.strip()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                target = _resolve_public(current)
                if target is None:
                    logger.warning(
                        f"Reference URL blocked (non-public address): '{current}'"
                    )
                    return None
                with client.stream(
                    "GET", target.url, **_request_kwargs(target)
                ) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    resp.raise_for_status()
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= _MAX_FETCH_BYTES:
                            break
                    return _parse_reference_text(
                        _decode_capped(chunks, resp.encoding), current
                    )
            logger.warning(
                f"Reference URL exceeded {_MAX_REDIRECTS} redirects: '{url}'"
            )
            return None
    except Exception as exc:
        logger.warning(f"Reference URL fetch failed for '{url}': {exc}")
        return None


async def async_fetch_reference_url(
    url: str, timeout: float = 8.0
) -> Optional[Dict[str, str]]:
    """Asynchronously fetch and extract clean text from an optional client reference URL."""
    if not url or not url.strip().startswith(("http://", "https://")):
        return None
    current = url.strip()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                target = await asyncio.to_thread(_resolve_public, current)
                if target is None:
                    logger.warning(
                        f"Reference URL blocked (non-public address): '{current}'"
                    )
                    return None
                async with client.stream(
                    "GET", target.url, **_request_kwargs(target)
                ) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    resp.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= _MAX_FETCH_BYTES:
                            break
                    return _parse_reference_text(
                        _decode_capped(chunks, resp.encoding), current
                    )
            logger.warning(
                f"Reference URL exceeded {_MAX_REDIRECTS} redirects: '{url}'"
            )
            return None
    except Exception as exc:
        logger.warning(f"Async reference URL fetch failed for '{url}': {exc}")
        return None


async def async_run_research_queries(
    queries: List[str], max_per_query: int = 3, timelimit: Optional[str] = None
) -> List[Dict[str, str]]:
    """Run DuckDuckGo queries in a worker thread without blocking the asyncio event loop."""
    return await asyncio.to_thread(
        run_research_queries, queries, max_per_query, timelimit
    )
