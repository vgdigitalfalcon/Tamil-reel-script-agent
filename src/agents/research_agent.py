"""Step 1: Resilient Research, Reference URL Grounding, and Angle Selection Agent."""

import asyncio
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from src.llm import LLMClient
from src.models import ResearchResult, ScriptInput, SourceItem
from src.prompts import RESEARCH_SYSTEM_PROMPT
from src.search_tool import (
    async_fetch_reference_url,
    async_run_research_queries,
    fetch_reference_url,
    run_research_queries,
)
from src.simulation import SimulationProvider

logger = logging.getLogger(__name__)

_RATE_LIMIT_UNCERTAINTY = (
    "Verification Needed: Live web search returned no snippets (rate-limited or offline); "
    "verify any specific factual claims against official client or authoritative sources."
)


LIVE_DATA_WARNING = (
    "Live data not fetched: this topic depends on recent events, but live web search "
    "returned no results. The script may contain outdated or invented facts. "
    "Verify every claim before recording, or try again later."
)

# Topics whose facts change week to week: search with a recency filter and never
# let the model fill gaps from memory.
_TIME_SENSITIVE_RE = re.compile(
    r"\b(news|latest|trending|this (?:week|month|year)|current (?:week|month|year)|"
    r"today|yesterday|tonight|weekly|recent(?:ly)?|update[sd]?|announce[ds]?|"
    r"launch(?:ed|es)?|breaking|headlines?|live score|price today|rate today|20[2-9]\d)\b"
    r"|இன்று|இந்த வாரம்|செய்தி|லேட்டஸ்ட்|நியூஸ்",
    re.IGNORECASE,
)

_TOPIC_LOCK = (
    "TOPIC LOCK: The Topic above is the subject of this video. Every finding, pain point "
    "and the chosen angle MUST be about that Topic. Client Brand DNA, Niche and Audience "
    "only shape who we speak to and the brand voice; never replace or reframe the Topic "
    "into the client's industry, and ignore search results that are off-topic."
)


def is_time_sensitive_topic(topic: str) -> bool:
    """True when the topic asks for current events (news, 'this week', a year, etc.)."""
    return bool(_TIME_SENSITIVE_RE.search(topic or ""))


def _format_brand_dna(inp: ScriptInput) -> str:
    """Format optional Client Brand DNA context for prompt injection."""
    if not inp.brand_dna:
        return ""
    dna = inp.brand_dna
    lines = [
        "CLIENT BRAND DNA (voice, audience and forbidden words only; does NOT change the Topic):"
    ]
    if dna.client_name:
        lines.append(f"- Brand/Client: {dna.client_name}")
    if dna.industry:
        lines.append(f"- Industry: {dna.industry}")
    if dna.target_audience:
        lines.append(f"- Target Audience: {dna.target_audience}")
    if dna.brand_tone:
        lines.append(f"- Brand Tone: {dna.brand_tone}")
    if dna.forbidden_words:
        lines.append(f"- Forbidden Words: {', '.join(dna.forbidden_words)}")
    return "\n".join(lines) + "\n"


class ResearchAgent:
    """Executes live web search + optional reference URL fetch with rate-limit fallback."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.last_usage: Dict[str, Any] = {}

    def _generate_search_queries(self, inp: ScriptInput) -> List[str]:
        """Generate 3 topic-only search queries capped at 8 core words.

        Queries carry no fixed industry words, so the topic alone decides what is searched.
        Time-sensitive topics get dated queries (and a recency filter at search time).
        """
        t = inp.topic.strip()
        cleaned = re.sub(
            r"^(why are|why do|why is|how to|what is|why|is|should|can|are)\s+",
            "",
            t,
            flags=re.IGNORECASE,
        ).rstrip("?")
        words = cleaned.split()
        core_query = " ".join(words[:8]) if len(words) > 8 else cleaned
        if is_time_sensitive_topic(t):
            month_year = date.today().strftime("%B %Y")
            return [core_query, f"{core_query} {month_year}", f"{core_query} latest"]
        return [
            core_query,
            f"{core_query} facts data",
            f"{core_query} common mistakes tips",
        ]

    @staticmethod
    def _timelimit(inp: ScriptInput) -> Optional[str]:
        """DuckDuckGo recency filter: past week for news-style topics, none otherwise."""
        return "w" if is_time_sensitive_topic(inp.topic) else None

    def _build_research_result(
        self,
        inp: ScriptInput,
        queries: List[str],
        raw_results: List[Dict[str, str]],
        ref_item: Optional[Dict[str, str]],
    ) -> ResearchResult:
        """Synthesize search & reference snippets via LLM, with graceful rate-limit fallback."""
        combined_results: List[Dict[str, str]] = []
        if ref_item:
            combined_results.append(ref_item)
        combined_results.extend(raw_results)

        search_fallback_used = len(raw_results) == 0 and ref_item is None
        time_sensitive = is_time_sensitive_topic(inp.topic)

        context_snippets = []
        for i, item in enumerate(combined_results[:12], 1):
            label = "[REF] " if ref_item and i == 1 else ""
            context_snippets.append(
                f"[{i}] {label}Title: {item.get('title')}\nURL: {item.get('url')}\nSnippet: {item.get('snippet')}\n"
            )

        if context_snippets:
            formatted_context = "\n".join(context_snippets)
        else:
            formatted_context = (
                "NO LIVE SEARCH RESULTS AVAILABLE (rate-limited or offline).\n"
                "Fall back to Client Brand DNA and conservative domain knowledge ONLY. "
                "Flag claims as 'Verification Needed' in uncertainties and do NOT invent URLs."
            )

        brand_dna_block = _format_brand_dna(inp)
        recency_rule = (
            f"TIME-SENSITIVE TOPIC (today is {date.today().isoformat()}): use ONLY facts that "
            "appear in the live results below. Never fill gaps with remembered or older events. "
            "Each key finding must be ONE concrete news item: what happened, who/which company, "
            "and when or which outlet (from the snippet's [source | date]). "
            "If the results contain nothing current, say so in uncertainties.\n"
            if time_sensitive
            else ""
        )
        ref_line = f"Reference URL: {inp.reference_url}\n" if inp.reference_url else ""

        user_prompt = f"""Topic: {inp.topic}
Audience: {inp.audience}
Niche: {inp.niche}
Objective: {inp.objective}
{_TOPIC_LOCK}
{recency_rule}{ref_line}{brand_dna_block}
LIVE SEARCH & REFERENCE RESULTS:
{formatted_context}

Please analyze these results, extract everyday spoken audience pain points (no corporate jargon), and output the research summary JSON strictly following the system prompt rules.
"""

        fallback = SimulationProvider.get_research_fallback(inp, combined_results)
        self.llm.last_usage = {}
        data = self.llm.generate_json(
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            default_fallback=fallback,
        )
        self.last_usage = dict(getattr(self.llm, "last_usage", {}) or {})

        source_items = [
            SourceItem(
                url=s.get("url", ""),
                title=s.get("title", ""),
                claim_supported=s.get("claim_supported", ""),
                is_verified=s.get("is_verified", True),
            )
            for s in data.get("sources", [])
            if s.get("url")
        ]

        uncertainties = list(data.get("uncertainties", []))
        if search_fallback_used and _RATE_LIMIT_UNCERTAINTY not in uncertainties:
            uncertainties.append(_RATE_LIMIT_UNCERTAINTY)
        live_data_warning = (
            LIVE_DATA_WARNING if time_sensitive and not raw_results else ""
        )

        return ResearchResult(
            topic=inp.topic,
            queries_run=queries,
            key_findings=data.get("key_findings", []),
            pain_points=data.get("pain_points", []),
            chosen_angle=data.get("chosen_angle", ""),
            angle_reason=data.get("angle_reason", ""),
            sources=source_items,
            uncertainties=uncertainties,
            search_fallback_used=search_fallback_used,
            is_time_sensitive=time_sensitive,
            live_data_warning=live_data_warning,
        )

    def execute(self, inp: ScriptInput) -> ResearchResult:
        """Synchronously run web searches, optional reference URL fetch, and LLM synthesis."""
        queries = self._generate_search_queries(inp)
        raw_results = run_research_queries(
            queries,
            max_per_query=3,
            timelimit=self._timelimit(inp),
            news=is_time_sensitive_topic(inp.topic),
            topic=inp.topic,
        )
        ref_item = fetch_reference_url(inp.reference_url) if inp.reference_url else None
        return self._build_research_result(inp, queries, raw_results, ref_item)

    async def aexecute(self, inp: ScriptInput) -> ResearchResult:
        """Non-blocking async research execution offloading search & LLM calls off the event loop."""
        queries = self._generate_search_queries(inp)
        search_coro = async_run_research_queries(
            queries,
            max_per_query=3,
            timelimit=self._timelimit(inp),
            news=is_time_sensitive_topic(inp.topic),
            topic=inp.topic,
        )
        if inp.reference_url:
            raw_results, ref_item = await asyncio.gather(
                search_coro,
                async_fetch_reference_url(inp.reference_url),
            )
        else:
            raw_results = await search_coro
            ref_item = None

        return await asyncio.to_thread(
            self._build_research_result,
            inp,
            queries,
            raw_results,
            ref_item,
        )
