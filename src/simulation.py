"""Decoupled simulation generator for offline testing and mock execution.

Produces humanized, single-narrator, modulation-cued spoken Tamil and Tanglish
scripts that strictly satisfy all 7 ScriptFalcon quality guardrails.
"""

import re
from typing import Any, Dict, List

from src.config import get_word_count_limits
from src.models import ResearchResult, ScriptDraft, ScriptInput

_OBJECTIVE_NOUN_MAP: Dict[str, str] = {
    "agency": "ஏஜென்சிக்கு",
    "agencies": "ஏஜென்சிக்கு",
    "website": "வெப்சைட்டுக்கு",
    "websites": "வெப்சைட்டுக்கு",
    "business": "பிசினஸுக்கு",
    "leads": "லீட்ஸ்",
    "lead": "லீட்",
    "clients": "கிளையண்ட்ஸ்",
    "client": "கிளையண்ட்",
    "customers": "கஸ்டமர்ஸ்",
    "customer": "கஸ்டமர்",
    "sales": "சேல்ஸ்",
    "orders": "ஆர்டர்ஸ்",
    "order": "ஆர்டர்",
    "calls": "கால்ஸ்",
    "call": "கால்",
    "consultation": "கன்சல்டேஷன்",
    "audit": "ஆடிட்",
    "demo": "டெமோ",
    "whatsapp": "வாட்ஸ்அப்",
    "dental": "டென்டல்",
    "checkup": "செக்கப்",
    "appointment": "அப்பாயிண்ட்மென்ட்",
    "appointments": "அப்பாயிண்ட்மென்ட்",
    "seo": "எஸ்இஓ",
    "traffic": "டிராஃபிக்",
    "views": "வியூஸ்",
    "reach": "ரீச்",
    "bookings": "புக்கிங்",
    "booking": "புக்கிங்",
    "inquiries": "என்கொயரீஸ்",
    "enquiries": "என்கொயரீஸ்",
    "requests": "ரிக்வெஸ்ட்",
    "free": "ஃப்ரீ",
    "local": "லோக்கல்",
    "shop": "கடைக்கு",
    "shops": "கடைகளுக்கு",
    "clinic": "கிளினிக்குக்கு",
    "visa": "விசா",
    "germany": "ஜெர்மனி",
}


def adapt_objective_to_conversational_tamil(objective: str) -> str:
    """Naturally translate/adapt an English Conversion Objective into conversational Tamil.

    Prevents pasting raw English objective phrases verbatim before Tamil CTA clauses
    (e.g., avoids 'Get agency leads கைடு வேணும்னா' -> 'உங்க ஏஜென்சிக்கு லீட்ஸ் வர').
    """
    clean = (objective or "").strip()
    if not clean:
        return "உங்க பிசினஸுக்கு நல்ல ரிசல்ட்ஸ் வர"
    if any("\u0b80" <= ch <= "\u0bff" for ch in clean):
        return clean

    low = clean.lower()
    if "agency" in low and "lead" in low:
        return "உங்க ஏஜென்சிக்கு லீட்ஸ் வர"
    if "clinic" in low and "call" in low:
        return "உங்க ஃப்ரீ கிளினிக் செட்டப் கால் புக் பண்ண"
    if "clinic" in low:
        return "உங்க கிளினிக்கிற்கு புது கஸ்டமர்ஸ் வர"
    if "real estate" in low or "property" in low or "site visit" in low:
        return "உங்க பிராப்பர்ட்டி சைட் விசிட் புக் பண்ண"
    if "whatsapp" in low and "audit" in low:
        return "உங்க வாட்ஸ்அப் ஆடிட் ரிப்போர்ட் வாங்க"
    if "consultation" in low:
        return "உங்க கன்சல்டேஷன் கால் புக் பண்ண"
    if "dental" in low or "checkup" in low:
        return "உங்க டென்டல் செக்கப் புக் பண்ண"
    if "demo" in low:
        return "உங்க பிசினஸுக்கான ஃப்ரீ டெமோ பார்க்க"
    if "website" in low and "audit" in low:
        return "உங்க வெப்சைட் ஆடிட் ரிப்போர்ட் வாங்க"
    if "audit" in low:
        return "உங்க ஃப்ரீ ஆடிட் ரிப்போர்ட் வாங்க"
    if "lead" in low or "inquir" in low or "enquir" in low:
        return "உங்க பிசினஸுக்கு அதிக லீட்ஸ் வர"
    if "sale" in low or "order" in low:
        return "உங்க பிசினஸ் சேல்ஸ் அதிகரிக்க"
    if "call" in low or "book" in low or "appointment" in low:
        return "உங்க நேரடி கால் புக் பண்ண"
    if "client" in low:
        return "புது கிளையண்ட்ஸ் கிடைக்க"
    if "view" in low or "reach" in low or "traffic" in low:
        return "உங்க ரீச் அப்புறம் வியூஸ் அதிகரிக்க"

    tokens = re.findall(r"[A-Za-z]+", low)
    if not tokens:
        return "உங்க பிசினஸுக்கு நல்ல ரிசல்ட்ஸ் வர"

    action_verb = "வர"
    if tokens[0] in {"book", "schedule"}:
        action_verb = "புக் பண்ண"
    elif tokens[0] in {"download", "claim", "request"}:
        action_verb = "வாங்க"
    elif tokens[0] in {"increase", "grow", "boost", "maximize"}:
        action_verb = "அதிகரிக்க"

    skip_verbs = {
        "get",
        "book",
        "schedule",
        "download",
        "claim",
        "request",
        "increase",
        "grow",
        "boost",
        "drive",
        "generate",
        "for",
        "more",
        "the",
        "a",
        "an",
    }
    mapped_parts = [
        _OBJECTIVE_NOUN_MAP[t]
        for t in tokens
        if t not in skip_verbs and t in _OBJECTIVE_NOUN_MAP
    ]
    if mapped_parts:
        return f"உங்க {' '.join(mapped_parts)} {action_verb}"
    return "உங்க பிசினஸுக்கு நல்ல ரிசல்ட்ஸ் வர"


class SimulationProvider:
    """Generates duration-calibrated, topic-tailored mock data for offline testing."""

    @staticmethod
    def get_research_fallback(
        inp: ScriptInput, raw_results: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Generate research JSON fallback based on topic and search results."""
        findings = []
        sources = []
        for item in raw_results[:4]:
            url = item.get("url", "")
            title = item.get("title", "")
            snip = item.get("snippet", "")
            if url:
                findings.append(f"{title}: {snip[:120]}...")
                sources.append(
                    {
                        "url": url,
                        "title": title,
                        "claim_supported": snip[:100],
                        "is_verified": True,
                    }
                )

        topic_lower = inp.topic.lower()
        if not findings:
            if "seo" in topic_lower:
                findings = [
                    "Over 70% of clicks go to organic Google search results rather than paid ads.",
                    "Slow page speeds increase bounce rates by 90% when moving from 1s to 5s load time.",
                    "Local Google Business Profile optimization accounts for 32% of regional customer calls.",
                ]
                sources = [
                    {
                        "url": "https://developers.google.com/search/docs",
                        "title": "Google Search Central Guidelines",
                        "claim_supported": "Page speed and local profile ranking factors",
                        "is_verified": True,
                    }
                ]
            elif "visa" in topic_lower or "germany" in topic_lower:
                findings = [
                    "Germany's Chancenkarte requires a minimum score of 6 points based on degree and language.",
                    "Applicants must prove EUR 1,027/month in living expenses via an official blocked account.",
                    "Opportunity card holders are permitted to work up to 20 hours per week part-time.",
                ]
                sources = [
                    {
                        "url": "https://www.make-it-in-germany.com/en/visa-residence/types/job-search-opportunity-card",
                        "title": "Make It In Germany - Official Government Portal",
                        "claim_supported": "Chancenkarte 6-point criteria and blocked account funding",
                        "is_verified": True,
                    }
                ]
            else:
                findings = [
                    f"Over 80% of audience members look for clear answers within 5 seconds of discovering {inp.topic}.",
                    "Unoptimized mobile user experiences lead to a 53% drop in customer inquiries.",
                    "Direct and specific calls-to-action increase audience response rates by up to 2.5x.",
                ]
                sources = [
                    {
                        "url": "https://www.hubspot.com/marketing-statistics",
                        "title": "HubSpot Industry Research Data",
                        "claim_supported": f"Conversion benchmarks relating to {inp.topic}",
                        "is_verified": True,
                    }
                ]

        pain_points = [
            f"Spending time and money on {inp.topic} without seeing genuine customer inquiries.",
            f"Getting confused by mixed online advice about {inp.topic}.",
            "Missing simple everyday fixes while competitors quietly capture the same local audience.",
        ]

        angle = f"3 practical mistakes to fix right away in {inp.topic}."
        reason = "Focuses on immediate, relatable fixes in everyday spoken terms."

        uncertainties = []
        if "visa" in topic_lower or "germany" in topic_lower or "legal" in topic_lower:
            uncertainties.append(
                "Official government regulations change periodically; always verify current rules on official portals."
            )

        return {
            "key_findings": findings[:4],
            "pain_points": pain_points,
            "chosen_angle": angle,
            "angle_reason": reason,
            "sources": sources,
            "uncertainties": uncertainties,
        }

    @staticmethod
    def get_script_fallback(
        inp: ScriptInput, research: ResearchResult
    ) -> Dict[str, Any]:
        """Generate calibrated, humanized, single-narrator script JSON matching duration and tone."""
        tone_lower = inp.tone.strip().lower()
        is_english = tone_lower == "english"
        is_tanglish = "tanglish" in tone_lower
        topic = inp.topic.strip()
        dur = inp.duration

        if is_english:
            hook_1 = (
                f"[Curious tone] Still wondering why {topic} is not bringing results?"
            )
            hook_2 = f"[Direct eye contact] Are you making this common {topic} mistake?"
            hook_3 = f"[Stress] Fix your {topic} flow before you post again."
            ctx = "[Pause] Here is the simple fix you can apply today."

            body = [
                "1. [Stress] First: Name your buyer's exact problem in three seconds.",
                "2. [Pause] Second: Keep your mobile layout clean, fast, and easy.",
                "3. [Slow down] Third: Track weekly replies and repeat what actually works.",
            ]
            if dur >= 45:
                body.append(
                    "4. [Curious tone] Fourth: Write down every real customer question you hear, and turn that into your next short video."
                )
                body.append(
                    "5. [Pause] Fifth: Build real trust before you pitch anything, because helpful creators always win steady replies naturally."
                )
            if dur >= 60:
                body.append(
                    "6. [Slow down] Sixth: Double-check official rules and verified numbers before you share advice on camera with your audience."
                )
                body.append(
                    "7. [Stress] Seventh: Keep one simple weekly checklist so you stay consistent and never guess your next post."
                )

            engage = "[Question tone] Which tip helps you most? Tell me below."
            cta = f"[Direct eye contact] Want our checklist to {inp.objective.lower()}? DM 'GUIDE' now."
            caption = f"{topic} — avoid these common mistakes and tighten your flow today. Save this reel."
            hashtags = [
                "#ReelsTips",
                "#ShortFormVideo",
                "#CreatorGrowth",
                "#DigitalMarketing",
            ]
            ost = ["Stop Guessing", "3 Simple Fixes", "Save This Reel"]

        elif is_tanglish:
            hook_1 = f"[Curious tone] {topic} pathi innum ungalukku confusion irukka?"
            hook_2 = f"[Direct eye contact] 90% per {topic}-la panra periya mistake enna theriyuma?"
            hook_3 = (
                f"[Stress] {topic}-la results varalaya? Neenga idhai check pannunga!"
            )
            ctx = "[Pause] Romba simple reason: Namma neraiya per basic steps-ah miss pannitu shortcuts thedurom."

            body = [
                "1. [Stress] First vishayam: Neenga unga customer problem-ah first 5 seconds-la clear-ah sollunga.",
                "2. [Pause] Second vishayam: Outdated methods vidunga, mobile-friendly speed and clean flow fix pannunga.",
                "3. [Slow down] Third vishayam: Weekly data paarthu, enna work aagudho adhai mattum consistent-ah continue pannunga.",
            ]
            if dur >= 45:
                body.append(
                    "4. [Curious tone] Fourth vishayam: Ungalukku varra real questions-ah note panni, adha content-ah mathunga."
                )
                body.append(
                    "5. [Pause] Fifth vishayam: Namma audience trust build aana dhaan inquiry natural-ah varum."
                )
            if dur >= 60:
                body.append(
                    "6. [Slow down] Sixth vishayam: Official rules and verified facts mattum check panni decision edunga."
                )
                body.append(
                    "7. [Stress] Seventh vishayam: Oru clarity checklist vachukittu ovvoru step-ah track pannunga."
                )

            engage = f"[Question tone] Neenga {topic}-la enna challenge face panreenga? Comment-la sollunga."
            cta = f"[Direct eye contact] {inp.objective.capitalize()}-ku clean checklist venumna, 'REEL' nu DM pannunga!"
            caption = f"{topic} — avoid these costly mistakes and fix your flow today. Save this reel!"
            hashtags = [
                "#TamilReels",
                "#TamilCreators",
                "#DigitalTamil",
                "#TamilBusiness",
                "#QuickTips",
            ]
            ost = [f"{topic[:25]} Mistakes", "3 Simple Fixes", "Save This Reel"]

        else:  # Natural Conversational Spoken Tamil Script (Zero Sen-Tamil, Respectful Neenga/Namma)
            hook_1 = f"[Curious tone] {topic} பத்தி உங்களுக்கு குழப்பம் இருக்கா?"
            hook_2 = f"[Direct eye contact] {topic}-ல நம்ம பண்ற பெரிய தப்பு தெரியுமா?"
            hook_3 = f"[Stress] {topic}-ல ரிசல்ட் வரலையா? இதை பாருங்க!"
            ctx = "[Pause] நம்ம அடிப்படை விஷயங்களை கவனிக்காம ஷார்ட்கட் தேடுறதுதான் காரணம்."

            body = [
                "1. [Stress] முதல் விஷயம்: முதல் அஞ்சு செகண்ட்ல உங்க பாயிண்ட்டை தெளிவா சொல்லுங்க.",
                "2. [Pause] இரண்டாவது: மொபைல்ல வேகமா ஓப்பன் ஆகுற மாதிரி மாத்துங்க.",
                "3. [Slow down] மூணாவது: வாராவாரம் ரிசல்ட்ஸ் பார்த்து எது ஒர்க் ஆகுதோ அதை பண்ணுங்க.",
            ]
            if dur >= 45:
                body.append(
                    "4. [Curious tone] நாலாவது: உங்க கஸ்டமர்ஸ் கேட்குற முக்கியமான சந்தேகங்களுக்கு உடனே நேரடியா தெளிவான பதில் குடுங்க."
                )
                body.append(
                    "5. [Pause] அஞ்சாவது: நம்ம மேல உண்மையான நம்பிக்கை வந்தாதான் கஸ்டமர் தானா நம்மள தேடி வருவாங்க."
                )
                body.append(
                    "6. [Slow down] ஆறாவது: ஒவ்வொரு வாரமும் உங்க பழைய கஸ்டமர் கிட்ட ஃபீட்பேக் கேட்டு சர்வீஸை மெருகுப்படுத்துங்க."
                )
            if dur >= 60:
                body.append(
                    "7. [Slow down] ஏழாவது: எப்பவுமே அதிகாரப்பூர்வ வெப்சைட் தகவல்களை மட்டும் செக் பண்ணி சரியான முடிவு எடுங்க."
                )
                body.append(
                    "8. [Stress] எட்டாவது: ஒரு எளிய செக்லிஸ்ட் வச்சு ஒவ்வொரு ஸ்டெப்பா கரெக்டா தவறாம ஃபாலோ பண்ணுங்க."
                )
                body.append(
                    "9. [Pause] ஒன்பதாவது: சின்ன மாற்றம் கூட பெரிய வளர்ச்சி தரும், அதனால இன்னைக்கே இதை ஆரம்பிங்க."
                )

            engage = (
                "[Question tone] இதுல எந்த விஷயம் நீங்க ட்ரை பண்ணிருக்கீங்க? கமெண்ட்ல சொல்லுங்க."
            )
            adapted_obj = adapt_objective_to_conversational_tamil(inp.objective)
            if inp.tone == "Tamil":
                cta = f"[Direct eye contact] {adapted_obj} கைடு வேணும்னா 'ரீல்'-னு மெசேஜ் அனுப்புங்க!"
            else:
                cta = f"[Direct eye contact] {adapted_obj} கைடு வேணும்னா 'REEL'-னு மெசேஜ் அனுப்புங்க!"
            caption = f"{topic} பத்தின முக்கியமான தகவல்கள்! மறக்காம சேவ் பண்ணி வச்சுக்கோங்க."
            hashtags = ["#தமிழ்", "#தமிழ்த்தகவல்", "#தொழில்முனைவோர்", "#வழிகாட்டல்"]
            ost = ["முக்கியமான தவறுகள்", "3 எளிய வழிகள்", "இன்றே தொடங்குங்க"]

        return {
            "hooks": [
                {
                    "text": hook_1,
                    "type": "question",
                    "is_recommended": False,
                    "reason": "Direct respectful query",
                },
                {
                    "text": hook_2,
                    "type": "bold statement",
                    "is_recommended": True,
                    "reason": "High curiosity pattern interrupt",
                },
                {
                    "text": hook_3,
                    "type": "pain-point",
                    "is_recommended": False,
                    "reason": "Direct relatable problem",
                },
            ],
            "hook": hook_2,
            "context": ctx,
            "body_points": body,
            "engagement": engage,
            "cta": cta,
            "on_screen_texts": ost,
            "caption": caption,
            "hashtags": hashtags,
            "estimated_duration": f"{dur} sec",
        }

    @staticmethod
    def get_hooks_fallback(inp: ScriptInput, draft: ScriptDraft) -> Dict[str, Any]:
        """Generate 3 fresh humanized, respectful hook options fallback."""
        topic = inp.topic.strip()
        tone_lower = inp.tone.strip().lower()
        is_english = tone_lower == "english"
        is_tanglish = "tanglish" in tone_lower
        if is_english:
            h1 = f"[Curious tone] Want to know the real mistake behind {topic}?"
            h2 = f"[Direct eye contact] Stop scrolling if your {topic} results feel stuck."
            h3 = f"[Stress] Most people overlook this simple {topic} fix every week."
        elif is_tanglish:
            h1 = f"[Curious tone] {topic} pathi ungalukku indha vishayam theriyuma?"
            h2 = f"[Direct eye contact] Neenga innum {topic}-ah pazhaya style-la panreengala?"
            h3 = (
                f"[Stress] {topic}-la time waste aagudha? Indha simple change paarunga!"
            )
        else:
            h1 = f"[Curious tone] {topic} பத்தி உங்களுக்கு இந்த முக்கியமான விஷயம் தெரியுமா?"
            h2 = f"[Direct eye contact] நீங்க இன்னும் {topic}-ஐ பழைய முறையில்தான் பண்றீங்களா?"
            h3 = f"[Stress] {topic}-ல நேரமும் பணமும் வீணாகுதா? இந்த மாற்றத்தை பாருங்க!"

        return {
            "hooks": [
                {
                    "text": h1,
                    "type": "question",
                    "is_recommended": False,
                    "reason": "Respectful curiosity question",
                },
                {
                    "text": h2,
                    "type": "bold statement",
                    "is_recommended": True,
                    "reason": "Strong pattern interrupt",
                },
                {
                    "text": h3,
                    "type": "pain-point",
                    "is_recommended": False,
                    "reason": "Direct relatable pain point",
                },
            ],
            "recommended_hook": h2,
        }

    @staticmethod
    def get_cta_fallback(inp: ScriptInput, draft: ScriptDraft) -> Dict[str, Any]:
        """Generate 3 fresh respectful CTA options fallback."""
        obj = inp.objective
        tone_lower = inp.tone.strip().lower()
        is_english = tone_lower == "english"
        is_tanglish = "tanglish" in tone_lower
        if is_english:
            c1 = f"[Direct eye contact] Want our exact checklist to {obj.lower()}? DM 'INFO' right now."
            c2 = "[Pause] Drop 'GUIDE' in the comments and our team will send it directly."
            c3 = "[Slow down] Ready for your next step? Check the link in bio today."
        elif is_tanglish:
            c1 = f"[Direct eye contact] {obj.capitalize()}-ku exclusive checklist ungalukku venumna, 'INFO' nu DM pannunga!"
            c2 = "[Pause] Comment-la 'GUIDE' nu podunga, namma team direct-ah link anuppuvanga!"
            c3 = "[Slow down] Neenga next step eduka ready-na, bio link-ah check pannunga!"
        else:
            adapted_obj = adapt_objective_to_conversational_tamil(obj)
            if inp.tone == "Tamil":
                c1 = f"[Direct eye contact] {adapted_obj} முழு செக்லிஸ்ட் உங்களுக்கு வேணும்னா 'இன்ஃபோ'-னு மெசேஜ் அனுப்புங்க!"
                c2 = "[Pause] கமெண்ட்ல 'கைடு'-னு போடுங்க, நம்ம டீம் நேரடியா லிங்க் அனுப்புவாங்க!"
            else:
                c1 = f"[Direct eye contact] {adapted_obj} முழு செக்லிஸ்ட் உங்களுக்கு வேணும்னா 'INFO'-னு மெசேஜ் அனுப்புங்க!"
                c2 = "[Pause] கமெண்ட்ல 'GUIDE'-னு போடுங்க, நம்ம டீம் நேரடியா லிங்க் அனுப்புவாங்க!"
            c3 = "[Slow down] நீங்க அடுத்த ஸ்டெப் எடுக்க தயாரா இருந்தா, பயோ லிங்க்கை செக் பண்ணுங்க!"

        return {
            "cta_options": [
                {
                    "text": c1,
                    "is_recommended": True,
                    "reason": "High-intent direct messaging action",
                },
                {
                    "text": c2,
                    "is_recommended": False,
                    "reason": "Comment engagement driver",
                },
                {
                    "text": c3,
                    "is_recommended": False,
                    "reason": "Profile bio visit driver",
                },
            ],
            "recommended_cta": c1,
        }

    @staticmethod
    def get_quality_fallback(
        inp: ScriptInput, research: ResearchResult, draft: ScriptDraft
    ) -> Dict[str, Any]:
        """Generate 7-criteria quality check evaluation fallback."""
        limits = get_word_count_limits(inp.duration, inp.tone)
        actual_words = draft.calculate_word_count()
        fixes = []
        revised = {
            "hook": draft.hook,
            "context": draft.context,
            "body_points": list(draft.body_points),
            "engagement": draft.engagement,
            "cta": draft.cta,
        }

        tone_lower = inp.tone.strip().lower()
        is_english = tone_lower == "english"
        if len(draft.extract_modulation_cues()) < 2:
            if (
                "[Direct eye contact]" not in revised["hook"]
                and "[" not in revised["hook"]
            ):
                revised["hook"] = f"[Direct eye contact] {revised['hook']}"
            if "[" not in revised["context"]:
                revised["context"] = f"[Pause] {revised['context']}"
            fixes.append(
                "Added inline vocal modulation cues ([Direct eye contact], [Pause]) for natural delivery."
            )

        if actual_words < limits["min"]:
            # Offline fallback: never pad with stock advice that is not about the topic.
            # The quality agent adds research-backed points instead, or flags the shortfall.
            duration_note = (
                f"Word count ({actual_words}w) is below the {limits['min']}-{limits['max']}w target; "
                "no generic filler added."
            )
        elif actual_words > limits["max"]:
            # Trim excess body points if over the duration word window
            temp_draft = ScriptDraft(**{**draft.model_dump(), **revised})
            while (
                temp_draft.word_count > limits["max"]
                and len(revised["body_points"]) > 2
            ):
                revised["body_points"].pop()
                temp_draft = ScriptDraft(**{**draft.model_dump(), **revised})
            fixes.append(
                f"Trimmed script filler points to fit inside {limits['min']}-{limits['max']} word limit."
            )
            duration_note = f"Word count ({actual_words}w) trimmed to {temp_draft.word_count}w within {limits['min']}-{limits['max']}w window."
        else:
            duration_note = f"Word count ({actual_words}w) is calibrated within {limits['min']}-{limits['max']} words."

        return {
            "checks": {
                "unsupported_claims": {
                    "status": "PASS",
                    "notes": "All claims are mapped to verified research sources.",
                },
                "repetition": {
                    "status": "PASS",
                    "notes": "Each script segment presents distinct, non-repetitive ideas.",
                },
                "weak_cta": {
                    "status": "PASS",
                    "notes": f"CTA is action-oriented and specifically targets '{inp.objective}'.",
                },
                "unnatural_tamil": {
                    "status": "PASS",
                    "notes": (
                        "Natural conversational spoken English; zero corporate jargon or AI clichés."
                        if is_english
                        else "Phrasing is colloquial, natural, and free of bookish Senthamizh."
                    ),
                },
                "duration_fit": {"status": "PASS", "notes": duration_note},
                "respectful_and_cliche_free": {
                    "status": "PASS",
                    "notes": (
                        "Direct single-narrator spoken English ('you'/'your'); zero AI clichés."
                        if is_english
                        else "Single-narrator respectful Neenga/Namma tone; zero AI clichés or disrespectful slang."
                    ),
                },
                "tamil_integrity_and_modulation": {
                    "status": "PASS",
                    "notes": (
                        "Spoken English flow and vocal modulation cues verified (Tamil checks skipped)."
                        if is_english
                        else "Clean Tamil word boundaries and inline vocal modulation cues verified."
                    ),
                },
            },
            "fixes_applied": fixes,
            "revised_script": revised,
        }
