"""Step 2: Humanized Scriptwriter Agent for Hooks, Scriptwriting, and Production Notes."""

import logging
from typing import Any, Dict

from src.config import (
    MAX_OUTPUT_TOKENS,
    REGENERATION_MAX_OUTPUT_TOKENS,
    get_word_count_limits,
)
from src.llm import LLMClient
from src.models import (
    CtaOptionItem,
    HookItem,
    ResearchResult,
    ScriptDraft,
    ScriptInput,
)
from src.prompts import (
    REGENERATE_CTA_PROMPT,
    REGENERATE_HOOK_PROMPT,
    SCRIPT_SYSTEM_PROMPT,
)
from src.simulation import SimulationProvider

logger = logging.getLogger(__name__)


def _format_brand_dna_section(inp: ScriptInput) -> str:
    """Format Client Brand DNA constraints for scriptwriting prompts."""
    if not inp.brand_dna:
        return ""
    dna = inp.brand_dna
    lines = ["CLIENT BRAND DNA (MANDATORY):"]
    if dna.client_name:
        lines.append(f"- Client Name: {dna.client_name}")
    if dna.industry:
        lines.append(f"- Industry: {dna.industry}")
    if dna.target_audience:
        lines.append(f"- Target Audience: {dna.target_audience}")
    if dna.brand_tone:
        lines.append(f"- Brand Tone: {dna.brand_tone}")
    if dna.forbidden_words:
        lines.append(
            f"- STRICTLY FORBIDDEN WORDS FOR THIS CLIENT: {', '.join(dna.forbidden_words)}"
        )
    return "\n".join(lines) + "\n"


class ScriptAgent:
    """Generates 3 hook options, humanized timed spoken script, and production notes."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.last_usage: Dict[str, Any] = {}

    def execute(self, inp: ScriptInput, research: ResearchResult) -> ScriptDraft:
        """Generate full script draft matching duration, vocal modulation, and tone guidelines."""
        limits = get_word_count_limits(inp.duration, inp.tone)
        brand_dna_block = _format_brand_dna_section(inp)
        if inp.tone == "Tamil":
            script_lang_rule = (
                "SCRIPT LANGUAGE LOCK (PURE TAMIL): Spoken lines MUST be 100% in Tamil Unicode script "
                "(தமிழ் எழுத்துக்கள்), INCLUDING transliterated loanwords (e.g., வெப்சைட், டிஎம், வியூஸ், "
                "ஆடிட், ரீல் — DO NOT leave website, DM, views, or AUDIT in English/Roman letters). "
                "NEVER write Tamil words like namma/unga/pannunga in Roman letters (always நம்ம/உங்க/பண்ணுங்க). "
                "BAN bookish Sen-Tamil words/connectors even in Pure Tamil (NEVER எளிது, விடுங்கள், மற்றும், உங்களுக்கான, செய்யுங்கள் — ALWAYS ஈஸி, விடுங்க, அப்புறம், உங்களுக்கு, பண்ணுங்க). "
                "ONLY bracketed vocal cues like [Pause] or [Stress] may stay in English. "
                "NEVER paste raw English Objective verbatim into the CTA; adapt it naturally into spoken Tamil."
            )
            address_note = "respectful ('Neenga'/'Namma') script"
            integrity_note = "clean Tamil word integrity, zero AI clichés"
        elif inp.tone == "conversational spoken Tamil":
            script_lang_rule = (
                "SCRIPT LANGUAGE LOCK (CONVERSATIONAL SPOKEN TAMIL): NEVER write Tamil words in English/Roman "
                "letters (NEVER namma, unga, neenga, pannunga — ALWAYS நம்ம, உங்க, நீங்க, பண்ணுங்க). "
                "Allow ONLY genuine English marketing terms (website, DM, Instagram Reel, AUDIT, leads) in English script, "
                "while keeping ALL Tamil words, grammar, and suffixes strictly in Tamil script (e.g., 'AUDIT'-னு, website-ல). "
                "NEVER paste raw English Objective verbatim into the CTA (avoid 'Get agency leads கைடு வேணும்னா'; "
                "adapt it naturally like 'உங்க ஏஜென்சிக்கு லீட்ஸ் வர கைடு வேணும்னா')."
            )
            address_note = "respectful ('Neenga'/'Namma') script"
            integrity_note = "clean Tamil word integrity, zero AI clichés"
        elif inp.tone == "English":
            script_lang_rule = (
                "SCRIPT LANGUAGE LOCK (SPOKEN ENGLISH): Write in natural, conversational, everyday spoken English "
                "tailored for short-form Reels/Shorts — like a real creator speaking directly to one viewer ('you', 'your'). "
                "Keep sentences short and punchy (8-12 words max per breath), calibrated at ~2.3-2.5 words/sec. "
                "STRICT ANTI-AI CLICHÉ & ANTI-JARGON LOCK: ZERO robotic buzzwords ('In today's fast-paced digital world', "
                "'game-changer', 'unlock your potential', 'delve into', 'dive deep', 'elevate your brand') and ZERO corporate jargon."
            )
            address_note = "direct, conversational ('you'/'your') script"
            integrity_note = (
                "short 8-12 word breath lines, zero corporate jargon, zero AI clichés"
            )
        else:
            script_lang_rule = (
                "SCRIPT LANGUAGE LOCK (TANGLISH): Write spoken Tamil in English letters using natural "
                "colloquial spellings (e.g., use 'serndhu' instead of ambiguous 'sethu')."
            )
            address_note = "respectful ('Neenga'/'Namma') script"
            integrity_note = "clean Tamil word integrity, zero AI clichés"

        user_prompt = f"""Topic: {inp.topic}
Audience: {inp.audience}
Platform: {inp.platform}
Target Duration: {inp.duration} seconds (STRICT spoken word count: {limits["min"]}-{limits["max"]} words, excluding [modulation] tags)
Tone / Language Mode: {inp.tone}
{script_lang_rule}
Objective: {inp.objective}
{brand_dna_block}
RESEARCH FINDINGS:
{chr(10).join(f"- {f}" for f in research.key_findings)}

CHOSEN CONTENT ANGLE:
{research.chosen_angle} (Reason: {research.angle_reason})

PAIN POINTS:
{chr(10).join(f"- {p}" for p in research.pain_points)}

Write a single-narrator, {address_note} with inline vocal modulation cues ([Pause], [Stress], [Curious tone], [Direct eye contact], [Slow down]), {integrity_note}, zero formal Sen-Tamil (NEVER எளிது, விடுங்கள், மற்றும், உங்களுக்கான — always ஈஸி, விடுங்க, அப்புறம், உங்களுக்கு), and pure spoken words strictly between {limits["min"]} and {limits["max"]} words (if {inp.duration}s >= 45, write enough body points so you never fall below {limits["min"]} words).
"""

        fallback = SimulationProvider.get_script_fallback(inp, research)
        self.llm.last_usage = {}
        data = self.llm.generate_json(
            system_prompt=SCRIPT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            default_fallback=fallback,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        self.last_usage = dict(getattr(self.llm, "last_usage", {}) or {})

        hooks_list = [
            HookItem(
                text=h.get("text", ""),
                type=h.get("type", "bold statement"),
                is_recommended=h.get("is_recommended", False),
                reason=h.get("reason", ""),
            )
            for h in data.get("hooks", [])
        ]

        if hooks_list and not any(h.is_recommended for h in hooks_list):
            hooks_list[0].is_recommended = True
            hooks_list[0].reason = "Selected as most compelling angle."

        active_hook = data.get("hook") or (hooks_list[0].text if hooks_list else "")

        cta_items = [
            CtaOptionItem(
                text=c.get("text", ""),
                is_recommended=c.get("is_recommended", False),
                reason=c.get("reason", ""),
            )
            for c in data.get("cta_options", [])
            if c.get("text")
        ]

        raw_points = data.get("body_points", [])
        if isinstance(raw_points, str):
            body_points_list = [
                ln.strip() for ln in raw_points.splitlines() if ln.strip()
            ]
        else:
            body_points_list = [str(x) for x in (raw_points or [])]

        draft = ScriptDraft(
            hooks=hooks_list,
            hook=active_hook,
            context=data.get("context", ""),
            body_points=body_points_list,
            engagement=data.get("engagement", ""),
            cta=data.get("cta", ""),
            cta_options=cta_items,
            on_screen_texts=data.get("on_screen_texts", []),
            caption=data.get("caption", ""),
            hashtags=data.get("hashtags", []),
            estimated_duration=data.get("estimated_duration", f"{inp.duration} sec"),
        )
        return draft

    def regenerate_hooks(self, inp: ScriptInput, draft: ScriptDraft) -> ScriptDraft:
        """Regenerate only hook options and swap recommended hook."""
        brand_dna_block = _format_brand_dna_section(inp)
        prompt = f"""Topic: {inp.topic}
Tone: {inp.tone}
{brand_dna_block}Current Script Body:
{chr(10).join(draft.body_points)}

Generate 3 brand new punchy, single-narrator respectful hooks (question, bold statement, pain-point), max 12 spoken words each, strictly matching Tone='{inp.tone}' and zero AI clichés. In 'Tamil' or 'conversational spoken Tamil', never write Tamil words (like namma, unga, pannunga) in Roman letters — always use Tamil script. In 'English', write natural conversational spoken English addressing 'you'/'your' with zero corporate jargon."""

        fallback = SimulationProvider.get_hooks_fallback(inp, draft)
        self.llm.last_usage = {}
        data = self.llm.generate_json(
            system_prompt=REGENERATE_HOOK_PROMPT,
            user_prompt=prompt,
            default_fallback=fallback,
            max_output_tokens=REGENERATION_MAX_OUTPUT_TOKENS,
        )
        self.last_usage = dict(getattr(self.llm, "last_usage", {}) or {})

        new_hooks = [
            HookItem(
                text=h.get("text", ""),
                type=h.get("type", "bold statement"),
                is_recommended=h.get("is_recommended", False),
                reason=h.get("reason", ""),
            )
            for h in data.get("hooks", [])
        ]
        new_hooks = [h for h in new_hooks if h.text.strip()]
        updated_draft = draft.model_copy(deep=True)
        if not new_hooks:
            # Malformed/empty LLM output: keep the existing hooks rather than blanking them.
            return updated_draft
        # Exactly one hook is flagged, and it is the one used as the active hook.
        wanted = (data.get("recommended_hook") or "").strip()
        chosen = next(
            (h for h in new_hooks if wanted and h.text.strip() == wanted), None
        )
        chosen = chosen or next(
            (h for h in new_hooks if h.is_recommended), new_hooks[0]
        )
        for h in new_hooks:
            h.is_recommended = h is chosen
        rec_text = chosen.text

        updated_draft.hooks = new_hooks
        updated_draft.hook = rec_text
        return updated_draft

    def regenerate_cta(self, inp: ScriptInput, draft: ScriptDraft) -> ScriptDraft:
        """Regenerate only CTA options and swap in the best CTA."""
        brand_dna_block = _format_brand_dna_section(inp)
        prompt = f"""Topic: {inp.topic}
Objective: {inp.objective}
Tone: {inp.tone}
{brand_dna_block}
Generate 3 NEW specific, respectful, non-vague CTA options matching the objective, with zero AI clichés.
CRITICAL RULES:
- For 'Tamil' or 'conversational spoken Tamil': NEVER write Tamil words in Roman letters (no namma/unga/pannunga — always நம்ம/உங்க/பண்ணுங்க), and NEVER paste the raw English Objective verbatim into the Tamil CTA (e.g., avoid 'Get agency leads கைடு வேணும்னா'; naturally translate/adapt it like 'உங்க ஏஜென்சிக்கு லீட்ஸ் வர கைடு வேணும்னா').
- For 'English': Write natural conversational spoken English addressing 'you'/'your' with zero AI clichés or corporate jargon."""

        fallback = SimulationProvider.get_cta_fallback(inp, draft)
        self.llm.last_usage = {}
        data = self.llm.generate_json(
            system_prompt=REGENERATE_CTA_PROMPT,
            user_prompt=prompt,
            default_fallback=fallback,
            max_output_tokens=REGENERATION_MAX_OUTPUT_TOKENS,
        )
        self.last_usage = dict(getattr(self.llm, "last_usage", {}) or {})

        cta_options_raw = data.get("cta_options", [])
        cta_items = [
            CtaOptionItem(
                text=c.get("text", ""),
                is_recommended=c.get("is_recommended", False),
                reason=c.get("reason", ""),
            )
            for c in cta_options_raw
            if c.get("text")
        ]
        rec_cta = data.get("recommended_cta") or (
            cta_items[0].text if cta_items else draft.cta
        )

        updated_draft = draft.model_copy(deep=True)
        updated_draft.cta = rec_cta
        if cta_items:
            updated_draft.cta_options = cta_items
        return updated_draft
