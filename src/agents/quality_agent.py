"""Step 3: 7-Criteria Quality Auditor, Mode Purity, & Self-Correction Agent."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.config import (
    BANNED_AI_CLICHES,
    DISRESPECTFUL_SLANG_BLACKLIST,
    ENGLISH_ADDRESS_MARKERS,
    ENGLISH_CORPORATE_JARGON,
    MAX_OUTPUT_TOKENS,
    RESPECTFUL_ADDRESS_MARKERS,
    TWO_PERSON_SKIT_MARKERS,
    VOCAL_MODULATION_MARKERS,
    get_word_count_limits,
)
from src.llm import LLMClient
from src.models import (
    CheckItem,
    QualityCheckResult,
    ResearchResult,
    ScriptDraft,
    ScriptInput,
)
from src.prompts import QUALITY_CHECK_SYSTEM_PROMPT
from src.simulation import SimulationProvider, adapt_objective_to_conversational_tamil

logger = logging.getLogger(__name__)

# Tamil Unicode ranges:
# Dependent vowel signs (matras), virama (pulli), anusvara, length marks
_TAMIL_COMBINING_MARKS = r"\u0B82\u0BBE-\u0BCD\u0BD7"
_TAMIL_CONSONANTS = r"\u0B95-\u0BB9"
_VALID_DECOMPOSED_VOWELS = {"\u0bc6\u0bbe", "\u0bc7\u0bbe", "\u0bc6\u0bd7"}

# Romanized colloquial Tamil words -> exact Tamil script (forbidden in both Tamil & Spoken Tamil modes)
_ROMANIZED_TAMIL_TO_SCRIPT: Dict[str, str] = {
    "namma": "நம்ம",
    "naama": "நாம",
    "neenga": "நீங்க",
    "neengalum": "நீங்களும்",
    "unga": "உங்க",
    "ungalukku": "உங்களுக்கு",
    "ungaluku": "உங்களுக்கு",
    "ungala": "உங்களை",
    "ungaloda": "உங்களோட",
    "ungaludaiya": "உங்களுடைய",
    "enga": "எங்க",
    "engalukku": "எங்களுக்கு",
    "engaloda": "எங்களோட",
    "avanga": "அவங்க",
    "ivanga": "இவங்க",
    "ellam": "எல்லாம்",
    "ellarum": "எல்லாரும்",
    "yaar": "யார்",
    "yarum": "யாரும்",
    "yaarum": "யாரும்",
    "pannunga": "பண்ணுங்க",
    "panna": "பண்ண",
    "pannalam": "பண்ணலாம்",
    "panni": "பண்ணி",
    "pannitu": "பண்ணிட்டு",
    "panra": "பண்ற",
    "panrom": "பண்றோம்",
    "panreenga": "பண்றீங்க",
    "panringa": "பண்றீங்க",
    "pannuvanga": "பண்ணுவாங்க",
    "pannuvom": "பண்ணுவோம்",
    "seiyunga": "செய்யுங்க",
    "sollunga": "சொல்லுங்க",
    "solra": "சொல்ற",
    "solren": "சொல்றேன்",
    "solrom": "சொல்றோம்",
    "solreenga": "சொல்றீங்க",
    "solrathilla": "சொல்றதில்ல",
    "paarunga": "பாருங்க",
    "parunga": "பாருங்க",
    "paarthu": "பார்த்து",
    "parthu": "பார்த்து",
    "paakalaam": "பார்க்கலாம்",
    "paakalam": "பார்க்கலாம்",
    "paarkalam": "பார்க்கலாம்",
    "venumna": "வேணும்னா",
    "venum": "வேணும்",
    "vendam": "வேண்டாம்",
    "vendaam": "வேண்டாம்",
    "irukku": "இருக்கு",
    "irukka": "இருக்கா",
    "irukeenga": "இருக்கீங்க",
    "irukkeenga": "இருக்கீங்க",
    "irukkanum": "இருக்கணும்",
    "irukanum": "இருக்கணும்",
    "irukkum": "இருக்கும்",
    "irukum": "இருக்கும்",
    "irundha": "இருந்தா",
    "irundhu": "இருந்து",
    "irunthu": "இருந்து",
    "varudhu": "வருது",
    "varuthu": "வருது",
    "varalaya": "வரலையா",
    "varalai": "வரலை",
    "varala": "வரல",
    "varum": "வரும்",
    "vandha": "வந்தா",
    "vantha": "வந்தா",
    "vandhu": "வந்து",
    "theriyuma": "தெரியுமா",
    "theriyum": "தெரியும்",
    "theriyadhu": "தெரியாது",
    "theriyala": "தெரியல",
    "therinjikonga": "தெரிஞ்சிக்கோங்க",
    "puriyala": "புரியல",
    "puriyudha": "புரியுதா",
    "purinjikonga": "புரிஞ்சிக்கோங்க",
    "kaththukonga": "கத்துக்கோங்க",
    "podunga": "போடுங்க",
    "podurom": "போடுறோம்",
    "anuppunga": "அனுப்புங்க",
    "anuppurom": "அனுப்புறோம்",
    "anuppuvanga": "அனுப்புவாங்க",
    "kudunga": "குடுங்க",
    "kodunga": "கொடுங்க",
    "edunga": "எடுங்க",
    "edukurathu": "எடுக்குறது",
    "vidunga": "விடுங்க",
    "aagum": "ஆகும்",
    "aagudhu": "ஆகுது",
    "aagudha": "ஆகுதா",
    "aaga": "ஆக",
    "aachu": "ஆச்சு",
    "kedaikum": "கிடைக்கும்",
    "kidaikkum": "கிடைக்கும்",
    "poga": "போக",
    "pogalam": "போகலாம்",
    "poyidum": "போயிடும்",
    "ponga": "போங்க",
    "vaanga": "வாங்க",
    "kelunga": "கேளுங்க",
    "kettu": "கேட்டு",
    "kekka": "கேட்க",
    "kekura": "கேட்குற",
    "pesalam": "பேசலாம்",
    "paesalam": "பேசலாம்",
    "pesunga": "பேசுங்க",
    "pesurom": "பேசுறோம்",
    "solli": "சொல்லி",
    "vechu": "வச்சு",
    "vachu": "வச்சு",
    "vachukittu": "வச்சுக்கிட்டு",
    "vaichukonga": "வச்சுக்கோங்க",
    "aarambinga": "ஆரம்பிங்க",
    "mudiyum": "முடியும்",
    "mudiyadhu": "முடியாது",
    "nenachinga": "நினைச்சீங்க",
    "ninaikireenga": "நினைக்கிறீங்க",
    "theduvanga": "தேடுவாங்க",
    "thedurom": "தேடுறோம்",
    "paathukonga": "பார்த்துக்கோங்க",
    "marakkama": "மறக்காம",
    "marakama": "மறக்காம",
    "serndhu": "சேர்ந்து",
    "sethu": "சேர்ந்து",
    "udhavum": "உதவும்",
    "idhu": "இது",
    "ithu": "இது",
    "adhu": "அது",
    "athu": "அது",
    "idhai": "இதை",
    "ithai": "இதை",
    "adhai": "அதை",
    "athai": "அதை",
    "atha": "அதை",
    "indha": "இந்த",
    "intha": "இந்த",
    "andha": "அந்த",
    "antha": "அந்த",
    "athukku": "அதுக்கு",
    "adhukku": "அதுக்கு",
    "ithukku": "இதுக்கு",
    "idhukku": "இதுக்கு",
    "epdi": "எப்படி",
    "eppadi": "எப்படி",
    "eppdi": "எப்படி",
    "enna": "என்ன",
    "ennanu": "என்னனு",
    "ethukku": "எதுக்கு",
    "edhukku": "எதுக்கு",
    "edhu": "எது",
    "romba": "ரொம்ப",
    "konjam": "கொஞ்சம்",
    "oru": "ஒரு",
    "mathiri": "மாதிரி",
    "maadhiri": "மாதிரி",
    "maari": "மாதிரி",
    "summa": "சும்மா",
    "naduvula": "நடுவுல",
    "thandi": "தாண்டி",
    "vazhi": "வழி",
    "avasiyam": "அவசியம்",
    "avasiyanga": "அவசியங்க",
    "innum": "இன்னும்",
    "aana": "ஆனா",
    "aanaa": "ஆனா",
    "aanal": "ஆனால்",
    "mattum": "மட்டும்",
    "matum": "மட்டும்",
    "mattumae": "மட்டுமே",
    "dhaan": "தான்",
    "kooda": "கூட",
    "kuda": "கூட",
    "illa": "இல்ல",
    "illai": "இல்லை",
    "illaya": "இல்லையா",
    "nalla": "நல்ல",
    "periya": "பெரிய",
    "chinna": "சின்ன",
    "pazhaya": "பழைய",
    "pudhu": "புது",
    "mukkiyam": "முக்கியம்",
    "mukkiyama": "முக்கியமா",
    "vishayam": "விஷயம்",
    "vishayanga": "விஷயங்க",
    "neraiya": "நிறைய",
    "niraiya": "நிறைய",
    "udane": "உடனே",
    "ippo": "இப்போ",
    "appo": "அப்போ",
    "eppo": "எப்போ",
    "inga": "இங்க",
    "anga": "அங்க",
    "kitta": "கிட்ட",
    "mela": "மேல",
    "keela": "கீழ",
    "ulla": "உள்ள",
    "veliya": "வெளிய",
    "munnadi": "முன்னாடி",
    "pinnadi": "பின்னாடி",
    "apram": "அப்புறம்",
    "appuram": "அப்புறம்",
    "aprom": "அப்புறம்",
    "thevai": "தேவை",
    "thappu": "தப்பு",
    "seri": "சரி",
    "kaaranam": "காரணம்",
    "karanam": "காரணம்",
    "nambikkai": "நம்பிக்கை",
    "valarchi": "வளர்ச்சி",
    "mudivu": "முடிவு",
    "thavaru": "தவறு",
    "kelvi": "கேள்வி",
    "badhil": "பதில்",
    "padhil": "பதில்",
    "kandippa": "கண்டிப்பா",
    "pathi": "பத்தி",
    "patti": "பத்தி",
}

# Marketing, tech & everyday English -> Tamil script loanword dictionary for Pure Tamil mode
_ENGLISH_TO_TAMIL_LOANWORDS: Dict[str, str] = {
    "website": "வெப்சைட்",
    "websites": "வெப்சைட்ஸ்",
    "dm": "டிஎம்",
    "views": "வியூஸ்",
    "view": "வியூ",
    "audit": "ஆடிட்",
    "reel": "ரீல்",
    "reels": "ரீல்ஸ்",
    "lead": "லீட்",
    "leads": "லீட்ஸ்",
    "instagram": "இன்ஸ்டாகிராம்",
    "youtube": "யூடியூப்",
    "facebook": "ஃபேஸ்புக்",
    "google": "கூகுள்",
    "seo": "எஸ்இஓ",
    "whatsapp": "வாட்ஸ்அப்",
    "bio": "பயோ",
    "link": "லிங்க்",
    "links": "லிங்க்ஸ்",
    "comment": "கமெண்ட்",
    "comments": "கமெண்ட்ஸ்",
    "follow": "ஃபாலோ",
    "video": "வீடியோ",
    "videos": "வீடியோஸ்",
    "business": "பிசினஸ்",
    "businesses": "பிசினஸ்",
    "marketing": "மார்க்கெட்டிங்",
    "digital": "டிஜிட்டல்",
    "agency": "ஏஜென்சி",
    "customer": "கஸ்டமர்",
    "customers": "கஸ்டமர்ஸ்",
    "client": "கிளையண்ட்",
    "clients": "கிளையண்ட்ஸ்",
    "funnel": "ஃபன்னல்",
    "click": "கிளிக்",
    "demo": "டெமோ",
    "info": "இன்ஃபோ",
    "guide": "கைடு",
    "free": "ஃப்ரீ",
    "online": "ஆன்லைன்",
    "mobile": "மொபைல்",
    "speed": "ஸ்பீட்",
    "content": "கன்டென்ட்",
    "offer": "ஆஃபர்",
    "brand": "பிராண்ட்",
    "page": "பேஜ்",
    "post": "போஸ்ட்",
    "share": "ஷேர்",
    "save": "சேவ்",
    "check": "செக்",
    "tips": "டிப்ஸ்",
    "tip": "டிப்",
    "shop": "ஷாப்",
    "shops": "ஷாப்ஸ்",
    "chennai": "சென்னை",
    "billing": "பில்லிங்",
    "visa": "விசா",
    "germany": "ஜெர்மனி",
    "chancenkarte": "சான்சன்கார்ட்டே",
    "brochure": "பிரோஷர்",
    "path": "பாத்",
    "clear": "கிளியர்",
    "direct": "டைரக்ட்",
    "message": "மெசேஜ்",
    "enquiry": "என்கொயரி",
    "enquiries": "என்கொயரீஸ்",
    "inquiry": "என்கொயரி",
    "inquiries": "என்கொயரீஸ்",
    "cta": "சிடிஏ",
    "roi": "ஆர்ஓஐ",
    "ads": "ஆட்ஸ்",
    "ad": "ஆட்",
    "ai": "ஏஐ",
    "app": "ஆப்",
    "shorts": "ஷார்ட்ஸ்",
    "profile": "புரொஃபைல்",
    "reach": "ரீச்",
    "growth": "குரோத்",
    "sale": "சேல்",
    "sales": "சேல்ஸ்",
    "conversion": "கன்வர்ஷன்",
    "traffic": "டிராஃபிக்",
    "hosting": "ஹோஸ்டிங்",
    "image": "இமேஜ்",
    "size": "சைஸ்",
    "compress": "கம்ப்ரஸ்",
    "layout": "லேஅவுட்",
    "response": "ரெஸ்பான்ஸ்",
    "time": "டைம்",
    "load": "லோட்",
    "second": "செகண்ட்",
    "seconds": "செகண்ட்ஸ்",
    "first": "ஃபர்ஸ்ட்",
    "third": "தேர்ட்",
    "order": "ஆர்டர்",
    "orders": "ஆர்டர்ஸ்",
    "repeat": "ரிப்பீட்",
    "local": "லோக்கல்",
    "root": "ரூட்",
    "canal": "கனால்",
    "dental": "டென்டல்",
    "checkup": "செக்கப்",
    "book": "புக்",
    "test": "டெஸ்ட்",
    "for": "ஃபார்",
    "get": "கெட்",
    "request": "ரிக்வெஸ்ட்",
    "requests": "ரிக்வெஸ்ட்ஸ்",
}

_STANDALONE_VOWELS = {
    "a": "அ",
    "aa": "ஆ",
    "e": "எ",
    "ee": "ஈ",
    "i": "இ",
    "o": "ஒ",
    "oo": "ஊ",
    "u": "உ",
    "ai": "ஐ",
    "au": "ஔ",
}
_VOWEL_MATRAS = {
    "a": "",
    "aa": "ா",
    "e": "ெ",
    "ee": "ீ",
    "i": "ி",
    "o": "ொ",
    "oo": "ூ",
    "u": "ு",
    "ai": "ை",
    "au": "ௌ",
}
_CONSONANT_MAP = {
    "ch": "ச",
    "sh": "ஷ",
    "th": "த",
    "ph": "ஃப",
    "ng": "ங",
    "k": "க",
    "c": "க",
    "g": "க",
    "j": "ஜ",
    "t": "ட",
    "d": "ட",
    "n": "ன",
    "p": "ப",
    "b": "ப",
    "f": "ஃப",
    "m": "ம",
    "y": "ய",
    "r": "ர",
    "l": "ல",
    "v": "வ",
    "w": "வ",
    "s": "ச",
    "z": "ஸ",
    "h": "ஹ",
    "q": "க",
    "x": "க்ச",
}


def _phonetic_latin_to_tamil(word: str) -> str:
    """Fallback phonetic transliterator so unknown Roman words convert cleanly to Tamil script."""
    lower = word.lower()
    if lower in _ROMANIZED_TAMIL_TO_SCRIPT:
        return _ROMANIZED_TAMIL_TO_SCRIPT[lower]
    if lower in _ENGLISH_TO_TAMIL_LOANWORDS:
        return _ENGLISH_TO_TAMIL_LOANWORDS[lower]

    out: List[str] = []
    i = 0
    n = len(lower)
    while i < n:
        # Check 2-char consonant digraphs
        two = lower[i : i + 2]
        if two in _CONSONANT_MAP:
            cons = _CONSONANT_MAP[two]
            i += 2
            vow2 = lower[i : i + 2]
            vow1 = lower[i : i + 1]
            if vow2 in _VOWEL_MATRAS:
                out.append(cons + _VOWEL_MATRAS[vow2])
                i += 2
            elif vow1 in _VOWEL_MATRAS:
                out.append(cons + _VOWEL_MATRAS[vow1])
                i += 1
            else:
                out.append(cons + "்")
            continue

        ch = lower[i]
        if ch in _CONSONANT_MAP:
            cons = _CONSONANT_MAP[ch]
            i += 1
            vow2 = lower[i : i + 2]
            vow1 = lower[i : i + 1]
            if vow2 in _VOWEL_MATRAS:
                out.append(cons + _VOWEL_MATRAS[vow2])
                i += 2
            elif vow1 in _VOWEL_MATRAS:
                out.append(cons + _VOWEL_MATRAS[vow1])
                i += 1
            else:
                out.append(cons + "்")
            continue

        if two in _STANDALONE_VOWELS:
            out.append(_STANDALONE_VOWELS[two])
            i += 2
            continue

        if ch in _STANDALONE_VOWELS:
            out.append(_STANDALONE_VOWELS[ch])
            i += 1
            continue

        i += 1

    result = "".join(out) or word
    # Ensure no double pulli or invalid vowel sequences
    result = re.sub(r"\u0BCD{2,}", "\u0bcd", result)
    return result


def find_non_bracketed_latin_words(text: str) -> List[str]:
    """Return all English/Roman words outside [vocal modulation] brackets."""
    if not text:
        return []
    without_cues = re.sub(r"\[[^\]]+\]", " ", text)
    return re.findall(r"(?<![0-9])[A-Za-z]+", without_cues)


def transliterate_text_preserving_cues(text: str) -> Tuple[str, List[str]]:
    """Transliterate non-bracketed Roman/English words into Tamil script, keeping [cues] intact."""
    if not text:
        return text, []

    converted_words: List[str] = []
    parts = re.split(r"(\[[^\]]+\])", text)
    out_parts: List[str] = []

    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            out_parts.append(part)
            continue

        def _replace_word(match: re.Match) -> str:
            word = match.group(0)
            tamil = _phonetic_latin_to_tamil(word)
            converted_words.append(f"{word}->{tamil}")
            return tamil

        replaced = re.sub(r"(?<![0-9])[A-Za-z]+", _replace_word, part)
        out_parts.append(replaced)

    return "".join(out_parts), converted_words


_ROMANIZED_TAMIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9\u0B80-\u0BFF])("
    + "|".join(sorted(_ROMANIZED_TAMIL_TO_SCRIPT.keys(), key=len, reverse=True))
    + r")(?![A-Za-z0-9\u0B80-\u0BFF])",
    re.IGNORECASE,
)


def find_romanized_tamil_words(text: str) -> List[str]:
    """Detect Romanized Tamil words (e.g. namma, unga, pannunga) outside [vocal cues]."""
    if not text:
        return []
    without_cues = re.sub(r"\[[^\]]+\]", " ", text)
    return _ROMANIZED_TAMIL_PATTERN.findall(without_cues)


def convert_romanized_tamil_words(text: str) -> Tuple[str, List[str]]:
    """Replace Romanized Tamil words outside [vocal cues] with proper Tamil Unicode words."""
    if not text:
        return text, []

    converted: List[str] = []
    parts = re.split(r"(\[[^\]]+\])", text)
    out_parts: List[str] = []

    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            out_parts.append(part)
            continue

        def _replace_tamil(match: re.Match) -> str:
            tok = match.group(1)
            tamil = _ROMANIZED_TAMIL_TO_SCRIPT.get(tok.lower(), tok)
            if tamil != tok:
                converted.append(f"{tok}->{tamil}")
            return tamil

        out_parts.append(_ROMANIZED_TAMIL_PATTERN.sub(_replace_tamil, part))

    return "".join(out_parts), converted


def has_verbatim_english_objective_in_cta(cta_text: str, objective: str) -> bool:
    """Detect if a multi-word English Conversion Objective was pasted verbatim into a Tamil CTA."""
    obj_clean = (objective or "").strip()
    if not cta_text or not obj_clean:
        return False
    if any("\u0b80" <= ch <= "\u0bff" for ch in obj_clean):
        return False
    if len(re.findall(r"[A-Za-z]{2,}", obj_clean)) < 2:
        return False
    without_cues = re.sub(r"\[[^\]]+\]", " ", cta_text)
    return bool(
        re.search(
            rf"(?<![A-Za-z]){re.escape(obj_clean)}(?![A-Za-z])",
            without_cues,
            re.IGNORECASE,
        )
    )


def rewrite_verbatim_objective_in_cta(
    cta_text: str, objective: str, tone: str
) -> Tuple[str, bool]:
    """Replace verbatim English objective pasted into a Tamil/Spoken Tamil CTA with natural Tamil."""
    if tone not in ("Tamil", "conversational spoken Tamil"):
        return cta_text, False
    if not has_verbatim_english_objective_in_cta(cta_text, objective):
        return cta_text, False

    obj_clean = objective.strip()
    adapted = adapt_objective_to_conversational_tamil(obj_clean)
    pattern = re.compile(
        rf"(?<![A-Za-z]){re.escape(obj_clean)}(?:\s*[-\s]?(?:kku|ku|க்கு|பத்தி))?(?=\s|$|[,.!?])",
        re.IGNORECASE,
    )
    parts = re.split(r"(\[[^\]]+\])", cta_text)
    changed = False
    out_parts: List[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            out_parts.append(part)
            continue
        replaced, count = pattern.subn(adapted, part)
        if count > 0:
            changed = True
        out_parts.append(replaced)

    return "".join(out_parts), changed


def clean_hybrid_suffixes(text: str) -> str:
    """Convert hybrid Roman suffixes (like 'AUDIT' nu or website-ku) into Tamil script suffixes."""
    if not text:
        return text

    out = text
    # Convert trailing Roman 'nu' after quoted tokens, Tamil words, or hyphenated English words -> '-னு'
    out = re.sub(
        r"(['\"][^'\"]+['\"])\s*[-\s]\s*nu\b", r"\1-னு", out, flags=re.IGNORECASE
    )
    out = re.sub(r"(['\"][^'\"]+['\"])\s+னு\b", r"\1-னு", out)
    out = re.sub(r"([A-Za-z]+)\s*-\s*nu\b", r"\1-னு", out, flags=re.IGNORECASE)
    out = re.sub(
        r"([\u0B80-\u0BFF]+)\s*[-\s]\s*nu\b", r"\1-னு", out, flags=re.IGNORECASE
    )

    # Convert common hyphenated Roman case suffixes after English, Tamil, or quoted terms
    out = re.sub(
        r"([A-Za-z\u0B80-\u0BFF'\"]+)-kitta\b", r"\1-கிட்ட", out, flags=re.IGNORECASE
    )
    out = re.sub(r"([A-Za-z\u0B80-\u0BFF'\"]+)-la\b", r"\1-ல", out, flags=re.IGNORECASE)
    out = re.sub(
        r"([A-Za-z\u0B80-\u0BFF'\"]+)-k?kum\b", r"\1-க்கும்", out, flags=re.IGNORECASE
    )
    out = re.sub(
        r"([A-Za-z\u0B80-\u0BFF'\"]+)-k?ku\b", r"\1-க்கு", out, flags=re.IGNORECASE
    )
    out = re.sub(
        r"([A-Za-z\u0B80-\u0BFF'\"]+)-oda\b", r"\1-ஓட", out, flags=re.IGNORECASE
    )
    out = re.sub(r"([A-Za-z\u0B80-\u0BFF'\"]+)-ah\b", r"\1-ஆ", out, flags=re.IGNORECASE)
    return out


def fix_tanglish_spelling_slips(text: str) -> str:
    """Normalize ambiguous Tanglish spellings (e.g., namma sethu -> namma serndhu)."""
    if not text:
        return text

    def _replace_namma_sethu(match: re.Match) -> str:
        prefix = match.group(1)
        sethu_tok = match.group(2)
        replacement = "Serndhu" if sethu_tok[0].isupper() else "serndhu"
        return f"{prefix} {replacement}"

    out = re.sub(
        r"\b(namma|naama|naam|ellam)\s+(sethu)\b",
        _replace_namma_sethu,
        text,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\b(sethu)(?=\s+(?:fix|panna|pannalam|pannunga|work|poga|pogalam|solla|sollunga|build|grow|start)\b)",
        lambda m: "Serndhu" if m.group(1)[0].isupper() else "serndhu",
        out,
        flags=re.IGNORECASE,
    )
    return out


def _term_pattern(term: str) -> re.Pattern:
    """Build Unicode-aware word-boundary regex for Latin or Tamil terms."""
    escaped = re.escape(term.strip())
    return re.compile(
        rf"(?<![\w\u0B80-\u0BFF]){escaped}(?![\w\u0B80-\u0BFF])", re.IGNORECASE
    )


def find_banned_cliches(
    text: str, extra_forbidden: Optional[List[str]] = None
) -> List[str]:
    """Detect banned AI buzzwords/cliches and client-specific forbidden words."""
    hits: List[str] = []
    candidates = list(BANNED_AI_CLICHES) + [
        w for w in (extra_forbidden or []) if w and w.strip()
    ]
    for phrase in candidates:
        if _term_pattern(phrase).search(text):
            hits.append(phrase)
    return hits


def find_corporate_jargon(text: str) -> List[str]:
    """Detect stiff corporate jargon phrases in English scripts."""
    hits: List[str] = []
    for phrase in ENGLISH_CORPORATE_JARGON:
        if _term_pattern(phrase).search(text):
            hits.append(phrase)
    return hits


def find_disrespectful_slang_and_skits(text: str) -> Dict[str, List[str]]:
    """Detect disrespectful third-person pronouns/slang and 2-person skit dialogue markers."""
    slang_hits = [
        term
        for term in DISRESPECTFUL_SLANG_BLACKLIST
        if _term_pattern(term).search(text)
    ]
    lowered = text.lower()
    skit_hits = [marker for marker in TWO_PERSON_SKIT_MARKERS if marker in lowered]
    return {"slang": slang_hits, "skits": skit_hits}


def has_respectful_address(text: str, tone: str = "Tanglish") -> bool:
    """Verify presence of respectful single-narrator direct address."""
    markers = (
        ENGLISH_ADDRESS_MARKERS
        if (tone or "").strip() == "English"
        else RESPECTFUL_ADDRESS_MARKERS
    )
    return any(_term_pattern(marker).search(text) for marker in markers)


def check_tamil_unicode_integrity(text: str) -> List[str]:
    """Check Tamil text for broken uyirmei splits, orphan matras, invalid marks, or truncation."""
    issues: List[str] = []
    if not text:
        return issues

    if "\ufffd" in text:
        issues.append(
            "Unicode replacement character (U+FFFD) detected; output may be corrupted."
        )

    orphan_matches = re.findall(rf"(?:^|[\s\"'(\[])([{_TAMIL_COMBINING_MARKS}])", text)
    if orphan_matches:
        issues.append(
            f"Orphan Tamil combining sign detected at word start: {orphan_matches[:3]}"
        )

    split_matches = re.findall(
        rf"([{_TAMIL_CONSONANTS}]\s+[{_TAMIL_COMBINING_MARKS}])", text
    )
    if split_matches:
        issues.append(
            f"Broken Tamil uyirmei split across whitespace: {split_matches[:3]}"
        )

    if "\u0bcd\u0bcd" in text:
        issues.append("Invalid consecutive Tamil virama (pulli) sequence detected.")
    for match in re.finditer(rf"[{_TAMIL_COMBINING_MARKS}]{{2,}}", text):
        seq = match.group(0)
        if seq not in _VALID_DECOMPOSED_VOWELS:
            issues.append(
                f"Invalid Tamil combining mark sequence detected: {repr(seq)}"
            )
            break

    if text.count("[") != text.count("]"):
        issues.append("Unclosed bracket tag detected; script may be truncated.")

    return issues


def repair_tamil_splits(text: str) -> str:
    """Deterministically rejoin accidentally spaced Tamil uyirmei combining marks."""
    if not text:
        return text
    return re.sub(
        rf"([{_TAMIL_CONSONANTS}])\s+([{_TAMIL_COMBINING_MARKS}])", r"\1\2", text
    )


_SEN_TAMIL_TO_SPOKEN: Dict[str, str] = {
    "எளிது": "ஈஸி",
    "எளிதாக": "ஈஸியா",
    "எளிமையான": "ஈஸியான",
    "விடுங்கள்": "விடுங்க",
    "மற்றும்": "அப்புறம்",
    "உங்களுக்கான": "உங்களுக்கு",
    "செய்யுங்கள்": "பண்ணுங்க",
    "பண்ணுங்கள்": "பண்ணுங்க",
    "உள்ளதா": "இருக்கா",
    "பின்பற்றுங்கள்": "ஃபாலோ பண்ணுங்க",
    "வருகிறது": "வருது",
    "குறித்து": "பத்தி",
    "பாருங்கள்": "பாருங்க",
    "சொல்லுங்கள்": "சொல்லுங்க",
    "எடுங்கள்": "எடுங்க",
    "அனுப்புங்கள்": "அனுப்புங்க",
    "போடுங்கள்": "போடுங்க",
    "தொடங்குங்கள்": "ஆரம்பிங்க",
    "வாருங்கள்": "வாங்க",
}

_SEN_TAMIL_PATTERN = re.compile(
    r"(?<![\w\u0B80-\u0BFF])("
    + "|".join(sorted(_SEN_TAMIL_TO_SPOKEN.keys(), key=len, reverse=True))
    + r")(?![\w\u0B80-\u0BFF])"
)


def find_sen_tamil_words(text: str) -> List[str]:
    """Detect formal/bookish Sen-Tamil words & connectors (e.g. எளிது, விடுங்கள், மற்றும், உங்களுக்கான)."""
    if not text:
        return []
    without_cues = re.sub(r"\[[^\]]+\]", " ", text)
    return _SEN_TAMIL_PATTERN.findall(without_cues)


def replace_sen_tamil_with_spoken(text: str) -> Tuple[str, List[str]]:
    """Replace formal Sen-Tamil words/connectors with everyday conversational Tamil equivalents."""
    if not text:
        return text, []

    converted: List[str] = []
    parts = re.split(r"(\[[^\]]+\])", text)
    out_parts: List[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            out_parts.append(part)
            continue

        def _repl(match: re.Match) -> str:
            tok = match.group(1)
            spoken = _SEN_TAMIL_TO_SPOKEN.get(tok, tok)
            if spoken != tok:
                converted.append(f"{tok}->{spoken}")
            return spoken

        out_parts.append(_SEN_TAMIL_PATTERN.sub(_repl, part))

    return "".join(out_parts), converted


# Non-Tamil Indic scripts (Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Telugu, Kannada,
# Malayalam, Sinhala). LLMs occasionally leak these into Tamil/Tanglish output (e.g. Bengali "লাভ").
_FOREIGN_INDIC_RANGES = "\u0900-\u0b7f\u0c00-\u0dff"
# Any word containing at least one foreign-Indic letter (used for detection / flagging).
_FOREIGN_INDIC_WORD_RE = re.compile(rf"[^\s\[\]]*[{_FOREIGN_INDIC_RANGES}][^\s\[\]]*")
# A word made up *entirely* of foreign-Indic letters (plus combining marks), with the one
# space before it. Only these are deleted; a mixed word (e.g. one Telugu letter inside a
# Tamil word) is left in place and flagged, because deleting it would drop the verb.
_PURE_FOREIGN_WORD_RE = re.compile(
    rf"[ \t]?(?<![^\s\[\]])[{_FOREIGN_INDIC_RANGES}]+(?![^\s\[\].,!?;:'\"])"
)

_ALLOWED_CUES = {m.strip("[]").lower(): m for m in VOCAL_MODULATION_MARKERS}
# Common LLM-invented cues mapped onto the approved teleprompter set.
_CUE_SYNONYMS = {
    "bold": "[Stress]",
    "emphasis": "[Stress]",
    "emphatic": "[Stress]",
    "excited": "[Stress]",
    "excited tone": "[Stress]",
    "confident tone": "[Stress]",
    "beat": "[Pause]",
    "short pause": "[Pause]",
    "long pause": "[Pause]",
    "sigh": "[Pause]",
    "frustrated sigh": "[Pause]",
    "slow": "[Slow down]",
    "slowly": "[Slow down]",
    "question": "[Question tone]",
    "questioning tone": "[Question tone]",
    "curious": "[Curious tone]",
    "eye contact": "[Direct eye contact]",
    "look at camera": "[Direct eye contact]",
}
# Script section / hook-type labels the LLM sometimes echoes into spoken text. A presenter
# would read these aloud from the teleprompter, so they are removed.
_SECTION_LABELS = {
    "hook",
    "context",
    "body",
    "engagement",
    "cta",
    "call to action",
    "caption",
    "bold statement",
    "pain-point",
    "pain point",
    "question hook",
    "intro",
    "outro",
}
_CUE_RE = re.compile(r"\[([^\[\]]{1,40})\]")


def find_foreign_indic_words(text: str) -> List[str]:
    """Return words written in a non-Tamil Indic script (Bengali, Devanagari, Telugu, ...)."""
    return _FOREIGN_INDIC_WORD_RE.findall(text or "")


def strip_foreign_indic_words(text: str) -> Tuple[str, List[str]]:
    """Delete words written wholly in a non-Tamil Indic script (with their leading space).

    Mixed words are kept (the deterministic audit still flags them); surrounding text and
    punctuation are not touched.
    """
    if not text:
        return text, []
    removed: List[str] = []

    def _drop(match: re.Match) -> str:
        removed.append(match.group(0).strip())
        return ""

    return _PURE_FOREIGN_WORD_RE.sub(_drop, text), removed


def normalize_modulation_cues(text: str) -> Tuple[str, List[str]]:
    """Map invented cues (e.g. [Bold]) to approved ones and drop section labels ([Hook], [CTA]).

    Any other bracketed text (e.g. [Smile], a bracketed Tamil phrase) is left untouched.
    """
    changed: List[str] = []

    def _repl(match: re.Match) -> str:
        key = " ".join(match.group(1).lower().split())
        if key in _ALLOWED_CUES:
            canonical = _ALLOWED_CUES[key]
            if canonical != match.group(0):
                changed.append(match.group(0))
            return canonical
        if key in _CUE_SYNONYMS:
            changed.append(match.group(0))
            return _CUE_SYNONYMS[key]
        if key in _SECTION_LABELS:
            changed.append(match.group(0))
            return ""
        return match.group(0)

    if not text:
        return text, changed
    result = _CUE_RE.sub(_repl, text)
    if changed:
        # Only collapse the gap left where a label was removed.
        result = re.sub(r"(?<=\S) {2,}(?=\S)", " ", result).strip()
    return result, changed


def run_deterministic_audit(draft: ScriptDraft, inp: ScriptInput) -> Dict[str, Any]:
    """Run deterministic pre/post checks across all script text and hooks."""
    spoken_text = " ".join(
        [
            draft.hook,
            draft.context,
            " ".join(draft.body_points),
            draft.engagement,
            draft.cta,
        ]
    )
    all_text = f"{spoken_text} {' '.join(h.text for h in draft.hooks)}"
    extra_forbidden = inp.brand_dna.forbidden_words if inp.brand_dna else []
    is_english = (inp.tone or "").strip() == "English"

    cliche_hits = find_banned_cliches(all_text, extra_forbidden=extra_forbidden)
    english_jargon_hits = find_corporate_jargon(all_text) if is_english else []
    tone_violations = find_disrespectful_slang_and_skits(all_text)
    respectful_present = has_respectful_address(spoken_text, tone=inp.tone)
    if is_english:
        tamil_issues = (
            ["Unclosed bracket tag detected; script may be truncated."]
            if all_text.count("[") != all_text.count("]")
            else []
        )
    else:
        tamil_issues = check_tamil_unicode_integrity(all_text)
    foreign_words = find_foreign_indic_words(all_text)
    if foreign_words:
        tamil_issues = tamil_issues + [
            f"Non-Tamil Indic script detected: {foreign_words[:3]}"
        ]
    modulation_cues = draft.extract_modulation_cues()
    latin_words_in_tamil = (
        find_non_bracketed_latin_words(spoken_text) if inp.tone == "Tamil" else []
    )
    romanized_tamil_words = (
        find_romanized_tamil_words(all_text)
        if inp.tone in ("Tamil", "conversational spoken Tamil")
        else []
    )
    sen_tamil_hits = (
        find_sen_tamil_words(all_text)
        if inp.tone in ("Tamil", "conversational spoken Tamil")
        else []
    )
    verbatim_obj_in_cta = (
        has_verbatim_english_objective_in_cta(draft.cta, inp.objective)
        if inp.tone in ("Tamil", "conversational spoken Tamil")
        else False
    )

    return {
        "cliche_hits": cliche_hits,
        "english_jargon_hits": english_jargon_hits,
        "slang_hits": tone_violations["slang"],
        "skit_hits": tone_violations["skits"],
        "respectful_present": respectful_present,
        "tamil_issues": tamil_issues,
        "modulation_cues": modulation_cues,
        "latin_words_in_tamil": latin_words_in_tamil,
        "romanized_tamil_words": romanized_tamil_words,
        "sen_tamil_hits": sen_tamil_hits,
        "verbatim_obj_in_cta": verbatim_obj_in_cta,
    }


def _apply_mode_post_cleanup(
    updated_draft: ScriptDraft,
    inp: ScriptInput,
    fixes_applied: List[str],
) -> Optional[str]:
    """Apply final deterministic mode purity cleanup, Tamil CTA adaptation & Criterion 4 checks.

    Returns a Criterion 4 flag note if Romanized Tamil words, verbatim English CTA objectives,
    or non-bracketed English words in Pure Tamil mode were detected and auto-corrected.
    """
    flag_notes: List[str] = []

    def _transform_all_fields(fn) -> bool:
        changed = False
        for attr in ("hook", "context", "engagement", "cta"):
            val = getattr(updated_draft, attr)
            new_val = fn(val)
            if new_val != val:
                setattr(updated_draft, attr, new_val)
                changed = True
        new_pts = [fn(p) for p in updated_draft.body_points]
        if new_pts != updated_draft.body_points:
            updated_draft.body_points = new_pts
            changed = True
        for h in updated_draft.hooks:
            nh = fn(h.text)
            if nh != h.text:
                h.text = nh
                changed = True
        for c in updated_draft.cta_options:
            nc = fn(c.text)
            if nc != c.text:
                c.text = nc
                changed = True
        return changed

    # 0a. Strip words leaked in other Indic scripts (Bengali, Devanagari, ...) — all tones.
    detected_foreign: List[str] = []

    def _foreign_fn(txt: str) -> str:
        res, found = strip_foreign_indic_words(txt)
        detected_foreign.extend(found)
        return res

    if _transform_all_fields(_foreign_fn):
        sample = ", ".join(detected_foreign[:6])
        fixes_applied.append(
            f"Removed words written in a non-Tamil Indic script: {sample}."
        )
        flag_notes.append(
            f"Detected non-Tamil Indic script ({sample}); removed from script."
        )

    # 0b. Normalise vocal modulation cues to the approved teleprompter set — all tones.
    detected_cues: List[str] = []

    def _cue_fn(txt: str) -> str:
        res, changed_cues = normalize_modulation_cues(txt)
        detected_cues.extend(changed_cues)
        return res

    if _transform_all_fields(_cue_fn):
        sample = ", ".join(dict.fromkeys(detected_cues))
        fixes_applied.append(
            f"Normalised non-standard vocal cues to the approved set: {sample}."
        )

    if inp.tone in ("Tamil", "conversational spoken Tamil"):
        # 1. Replace raw pasted English Conversion Objective in CTA / CTA options with natural Tamil
        cta_obj_fixed = False
        rewritten_cta, changed_main = rewrite_verbatim_objective_in_cta(
            updated_draft.cta, inp.objective, inp.tone
        )
        if changed_main:
            updated_draft.cta = rewritten_cta
            cta_obj_fixed = True
        for c in updated_draft.cta_options:
            rewritten_opt, changed_opt = rewrite_verbatim_objective_in_cta(
                c.text, inp.objective, inp.tone
            )
            if changed_opt:
                c.text = rewritten_opt
                cta_obj_fixed = True
        if cta_obj_fixed:
            fixes_applied.append(
                f"Adapted raw English objective ('{inp.objective}') into natural conversational Tamil CTA phrasing."
            )
            flag_notes.append(
                f"Raw English objective ('{inp.objective}') was pasted verbatim in Tamil CTA; adapted to natural Tamil."
            )

        # 2. Replace formal Sen-Tamil words & connectors (எளிது, விடுங்கள், மற்றும், உங்களுக்கான) even in Pure Tamil
        detected_sen_tamil: List[str] = []

        def _sen_tamil_fn(txt: str) -> str:
            res, conv = replace_sen_tamil_with_spoken(txt)
            detected_sen_tamil.extend(conv)
            return res

        if _transform_all_fields(_sen_tamil_fn):
            sample = ", ".join(detected_sen_tamil[:6])
            fixes_applied.append(
                f"Replaced formal Sen-Tamil words with spoken equivalents: {sample}."
            )
            flag_notes.append(
                f"Detected formal Sen-Tamil words in {inp.tone} mode ({sample}); replaced with spoken equivalents."
            )

        # 3. Convert any Romanized Tamil words (namma, unga, pannunga, etc.) to Tamil script
        detected_roman_tamil: List[str] = []

        def _roman_tamil_fn(txt: str) -> str:
            res, conv = convert_romanized_tamil_words(txt)
            detected_roman_tamil.extend(conv)
            return res

        if _transform_all_fields(_roman_tamil_fn):
            sample = ", ".join(detected_roman_tamil[:6])
            fixes_applied.append(
                f"Converted Romanized Tamil words to Tamil script: {sample}."
            )
            flag_notes.append(
                f"Detected Romanized Tamil words in {inp.tone} mode ({sample}); converted to Tamil script."
            )

        # 4. Convert hybrid Roman suffixes ('AUDIT' nu -> 'AUDIT'-னு, website-la -> website-ல)
        if _transform_all_fields(clean_hybrid_suffixes):
            fixes_applied.append(
                "Converted hybrid Roman suffixes (e.g. 'AUDIT' nu -> 'AUDIT'-னு) into Tamil script."
            )

    if inp.tone == "Tanglish":
        if _transform_all_fields(fix_tanglish_spelling_slips):
            fixes_applied.append(
                "Corrected ambiguous Tanglish spellings (e.g. namma sethu -> namma serndhu)."
            )

    if inp.tone == "Tamil":
        detected_latin: List[str] = []

        def _translit_fn(txt: str) -> str:
            res, conv = transliterate_text_preserving_cues(txt)
            detected_latin.extend(conv)
            return res

        if _transform_all_fields(_translit_fn):
            sample = ", ".join(detected_latin[:6])
            fixes_applied.append(
                f"Transliterated non-bracketed English words into Tamil script: {sample}."
            )
            flag_notes.append(
                f"Detected non-bracketed English words in Tamil mode ({sample}); "
                "transliterated to Tamil script."
            )

    return "; ".join(flag_notes) if flag_notes else None


def _count_tip_spoken_words(tip: str) -> int:
    """Count pure spoken words inside a candidate body tip."""
    spoken = re.sub(r"\[[^\]]+\]", " ", tip)
    return len(
        re.findall(
            r"[\w\u0B80-\u0BFF]+(?:['\-][\w\u0B80-\u0BFF]+)*", spoken, flags=re.UNICODE
        )
    )


def _enforce_45s_60s_word_minimum(
    updated_draft: ScriptDraft,
    inp: ScriptInput,
    fixes_applied: List[str],
) -> Optional[str]:
    """Ensure 45s and 60s scripts meet their strict minimum spoken word count by expanding body_points."""
    if inp.duration not in (45, 60):
        return None
    limits = get_word_count_limits(inp.duration, inp.tone)
    before_wc = updated_draft.word_count
    if before_wc >= limits["min"]:
        return None

    tone_lower = (inp.tone or "").strip().lower()
    if tone_lower == "english":
        tip_pool = [
            "[Slow down] Ask your existing customers for quick feedback each week so you improve what actually matters.",
            "[Pause] Keep doing what brings real replies, and cut out extra steps that waste your time.",
            "[Stress] Say your main point in the first five seconds so viewers stay until the end.",
            "[Curious tone] Answer one common question directly in every reel, because clear help builds trust fast.",
            "[Slow down] Keep a short weekly checklist so your next post stays consistent.",
            "[Pause] Small steady tweaks bring better results once you start tracking today.",
            "[Stress] Review your replies weekly before making your next move.",
            "[Pause] Try this simple change today.",
        ]
    elif "tanglish" in tone_lower:
        tip_pool = [
            "[Slow down] Unga old customers kitta weekly feedback kettu chinna changes panna kooda periya growth varum.",
            "[Pause] Edhu nalla work aagudho adhai mattum continue pannunga, thevai illadha steps-ah dhairiyama vidunga.",
            "[Stress] First 5 seconds-laye unga point-ah clear-ah sonna dhaan viewers last varaikkum paarpaanga.",
            "[Curious tone] Customers kekura chinna doubts-kum direct-ah badhil kudutha trust easy-ah build aagum.",
            "[Slow down] Oru simple checklist vachu ovvoru step-ah regular-ah follow pannunga.",
            "[Pause] Chinna change kooda nalla results tharum, innaike start pannunga.",
            "[Stress] Weekly results check panni next step edunga.",
            "[Pause] Innaike idhai try pannunga.",
        ]
    else:
        tip_pool = [
            "[Slow down] உங்க பழைய கஸ்டமர் கிட்ட வாராவாரம் ஃபீட்பேக் கேட்டு சின்ன மாற்றம் பண்ணா கூட பெரிய வளர்ச்சி வரும்.",
            "[Pause] எது நல்லா ஒர்க் ஆகுதோ அதை மட்டும் தொடர்ந்து பண்ணுங்க, தேவையில்லாத விஷயங்களை தைரியமா விடுங்க.",
            "[Stress] முதல் அஞ்சு செகண்ட்லயே உங்க பாயிண்ட்டை தெளிவா சொன்னாதான் பாக்குறவங்க கடைசி வரைக்கும் நிப்பாங்க.",
            "[Curious tone] மக்கள் கேட்குற சின்ன சந்தேகங்களுக்கு கூட நேரடியா பதில் குடுத்தா நம்பிக்கை ஈஸியா வளரும்.",
            "[Slow down] ஒரு எளிய செக்லிஸ்ட் வச்சு ஒவ்வொரு ஸ்டெப்பா கரெக்டா ஃபாலோ பண்ணுங்க.",
            "[Pause] சின்ன மாற்றம் கூட பெரிய ரிசல்ட்ஸ் தரும், இன்னைக்கே ஆரம்பிங்க.",
            "[Stress] வாராவாரம் ரிசல்ட்ஸ் செக் பண்ணி அடுத்த ஸ்டெப் எடுங்க.",
            "[Pause] இன்னைக்கே இதை ட்ரை பண்ணுங்க.",
        ]

    used_indices = set()
    existing_joined = " ".join(updated_draft.body_points).lower()
    while updated_draft.word_count < limits["min"]:
        current_wc = updated_draft.word_count
        headroom = limits["max"] - current_wc
        chosen_idx = None
        for idx, tip in enumerate(tip_pool):
            if idx in used_indices:
                continue
            if tip.lower()[:24] in existing_joined:
                continue
            if _count_tip_spoken_words(tip) <= headroom:
                chosen_idx = idx
                break
        if chosen_idx is None:
            # Pick shortest unused tip if remaining headroom is tight
            remaining = [
                (idx, _count_tip_spoken_words(tip))
                for idx, tip in enumerate(tip_pool)
                if idx not in used_indices
            ]
            if not remaining:
                break
            chosen_idx = min(remaining, key=lambda pair: pair[1])[0]

        used_indices.add(chosen_idx)
        next_num = len(updated_draft.body_points) + 1
        updated_draft.body_points.append(f"{next_num}. {tip_pool[chosen_idx]}")
        if updated_draft.word_count >= limits["max"]:
            break

    after_wc = updated_draft.word_count
    fixes_applied.append(
        f"Auto-expanded body tips from {before_wc}w to {after_wc}w to meet {inp.duration}s target ({limits['min']}-{limits['max']}w)."
    )
    return f"Expanded body tips from {before_wc}w to {after_wc}w within {limits['min']}-{limits['max']}w range."


class QualityAgent:
    """Rigorous 7-criteria quality auditor with deterministic checks and self-correction."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.last_usage: Dict[str, Any] = {}

    def execute(
        self, inp: ScriptInput, research: ResearchResult, draft: ScriptDraft
    ) -> Tuple[QualityCheckResult, ScriptDraft]:
        """Evaluate 7 criteria, auto-fix any flagged defect, and return (QualityCheckResult, updated_draft)."""
        is_english = (inp.tone or "").strip() == "English"
        limits = get_word_count_limits(inp.duration, inp.tone)
        actual_words = draft.calculate_word_count()
        pre_audit = run_deterministic_audit(draft, inp)

        pre_check_notes = []
        if pre_audit["cliche_hits"]:
            pre_check_notes.append(
                f"BANNED AI CLICHES / FORBIDDEN WORDS FOUND: {pre_audit['cliche_hits']}"
            )
        if pre_audit["english_jargon_hits"]:
            pre_check_notes.append(
                f"CORPORATE JARGON FOUND IN ENGLISH MODE: {pre_audit['english_jargon_hits']}. "
                "Rewrite using everyday spoken English with short 8-12 word breath lines."
            )
        if pre_audit["slang_hits"]:
            pre_check_notes.append(
                f"DISRESPECTFUL SLANG FOUND: {pre_audit['slang_hits']}"
            )
        if pre_audit["skit_hits"]:
            pre_check_notes.append(
                f"TWO-PERSON SKIT MARKERS FOUND: {pre_audit['skit_hits']}"
            )
        if pre_audit["tamil_issues"]:
            pre_check_notes.append(
                f"TAMIL UNICODE INTEGRITY ISSUES: {pre_audit['tamil_issues']}"
            )
        if len(pre_audit["modulation_cues"]) < 2:
            pre_check_notes.append(
                f"LOW VOCAL MODULATION CUES ({len(pre_audit['modulation_cues'])} found; need >= 2 such as [Pause], [Stress], [Direct eye contact])."
            )
        if inp.tone in ("Tamil", "conversational spoken Tamil"):
            spoken_check = f"{draft.hook} {draft.context} {' '.join(draft.body_points)} {draft.engagement} {draft.cta}"
            tamil_char_count = sum(
                1 for ch in spoken_check if "\u0b80" <= ch <= "\u0bff"
            )
            if tamil_char_count < 15:
                pre_check_notes.append(
                    "LANGUAGE SCRIPT MISMATCH: Tone requires Tamil Unicode script (தமிழ்), but draft is in Romanized Tanglish. Rewrite all spoken lines in conversational Tamil Unicode script."
                )
        if pre_audit["latin_words_in_tamil"]:
            pre_check_notes.append(
                f"PURE TAMIL MODE VIOLATION: Non-bracketed English words found {pre_audit['latin_words_in_tamil'][:8]}. "
                "Transliterate ALL loanwords into Tamil script (e.g., வெப்சைட், டிஎம், வியூஸ்); keep only [Pause]/[Stress] cues in English."
            )
        if pre_audit["romanized_tamil_words"]:
            pre_check_notes.append(
                f"ROMANIZED TAMIL WORDS VIOLATION ({inp.tone}): Tamil words written in Roman letters {pre_audit['romanized_tamil_words'][:8]}. "
                "Convert ALL Tamil words into Tamil script (e.g., namma->நம்ம, unga->உங்க, pannunga->பண்ணுங்க)."
            )
        if pre_audit["verbatim_obj_in_cta"]:
            pre_check_notes.append(
                f"RAW ENGLISH OBJECTIVE IN TAMIL CTA: Objective '{inp.objective}' was pasted verbatim into Tamil CTA. "
                "Naturally translate/adapt it into conversational Tamil (e.g., 'உங்க ஏஜென்சிக்கு லீட்ஸ் வர கைடு வேணும்னா')."
            )
        if pre_audit["sen_tamil_hits"]:
            pre_check_notes.append(
                f"FORMAL SEN-TAMIL WORDS DETECTED ({inp.tone}): {pre_audit['sen_tamil_hits'][:8]}. "
                "Replace with everyday spoken Tamil (எளிது->ஈஸி, விடுங்கள்->விடுங்க, மற்றும்->அப்புறம், உங்களுக்கான->உங்களுக்கு)."
            )
        if inp.duration in (45, 60) and actual_words < limits["min"]:
            pre_check_notes.append(
                f"UNDER-LENGTH {inp.duration}s SCRIPT: Spoken count is {actual_words}w, below minimum {limits['min']}w. "
                f"Expand body_points with concrete tips until spoken words reach {limits['min']}-{limits['max']}w."
            )

        pre_check_block = (
            "\n".join(f"- {note}" for note in pre_check_notes)
            if pre_check_notes
            else "None"
        )

        user_prompt = f"""Topic: {inp.topic}
Audience: {inp.audience}
Duration: {inp.duration}s (Strict spoken target: {limits["min"]}-{limits["max"]} words | Actual spoken words: {actual_words})
Tone: {inp.tone}
Objective: {inp.objective}

DETERMINISTIC PRE-CHECK FLAGS:
{pre_check_block}

RESEARCH SOURCES:
{chr(10).join(f"- {s.claim_supported} ({s.url})" for s in research.sources)}

DRAFT SCRIPT TO AUDIT:
[Hook] {draft.hook}
[Context] {draft.context}
[Body]
{chr(10).join(f"- {p}" for p in draft.body_points)}
[Engagement] {draft.engagement}
[CTA] {draft.cta}

Perform the 7-criteria quality audit. If ANY criterion or pre-check flag fails, rewrite the defective script segments under 'revised_script' and log fixes under 'fixes_applied'.
"""

        fallback = SimulationProvider.get_quality_fallback(inp, research, draft)
        self.llm.last_usage = {}
        data = self.llm.generate_json(
            system_prompt=QUALITY_CHECK_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            default_fallback=fallback,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        self.last_usage = dict(getattr(self.llm, "last_usage", {}) or {})

        has_structured_checks = "checks" in data and isinstance(data["checks"], dict)
        checks_data = data.get("checks", {}) if has_structured_checks else {}
        raw_fixes = data.get("fixes_applied", [])
        if isinstance(raw_fixes, str):
            fixes_applied = [raw_fixes] if raw_fixes.strip() else []
        else:
            fixes_applied = list(raw_fixes or [])
        revised = data.get("revised_script")

        def _check_entry(key: str, default_notes: str) -> Dict[str, str]:
            entry = checks_data.get(key)
            if isinstance(entry, dict):
                return {
                    "status": str(entry.get("status", "PASS")),
                    "notes": str(entry.get("notes", default_notes)),
                }
            if isinstance(entry, str):
                return {"status": entry, "notes": default_notes}
            return {"status": "PASS", "notes": default_notes}

        updated_draft = draft.model_copy(deep=True)
        if revised and isinstance(revised, dict):
            if revised.get("hook"):
                revised_hook_text = revised["hook"].strip()
                updated_draft.hook = revised_hook_text
                found_rec = False
                for h in updated_draft.hooks:
                    if h.is_recommended:
                        h.text = revised_hook_text
                        h.reason = (
                            "Revised by Quality Auditor for tone/duration compliance."
                        )
                        found_rec = True
                        break
                if not found_rec and updated_draft.hooks:
                    updated_draft.hooks[0].text = revised_hook_text
                    updated_draft.hooks[0].is_recommended = True

            if revised.get("context"):
                updated_draft.context = revised["context"]
            if revised.get("body_points"):
                bp = revised["body_points"]
                if isinstance(bp, str):
                    updated_draft.body_points = [
                        ln.strip() for ln in bp.splitlines() if ln.strip()
                    ]
                else:
                    updated_draft.body_points = [str(x) for x in bp]
            if revised.get("engagement"):
                updated_draft.engagement = revised["engagement"]
            if revised.get("cta"):
                updated_draft.cta = revised["cta"]

        # Deterministic post-audit repair for Tamil uyirmei split spaces (skipped in English mode)
        if not is_english:
            repaired_hook = repair_tamil_splits(updated_draft.hook)
            if repaired_hook != updated_draft.hook:
                updated_draft.hook = repaired_hook
                fixes_applied.append(
                    "Repaired spaced Tamil uyirmei combining mark in hook."
                )
            repaired_context = repair_tamil_splits(updated_draft.context)
            if repaired_context != updated_draft.context:
                updated_draft.context = repaired_context
                fixes_applied.append(
                    "Repaired spaced Tamil uyirmei combining mark in context."
                )
            repaired_points = [
                repair_tamil_splits(p) for p in updated_draft.body_points
            ]
            if repaired_points != updated_draft.body_points:
                updated_draft.body_points = repaired_points
                fixes_applied.append(
                    "Repaired spaced Tamil uyirmei combining marks in body points."
                )
            updated_draft.engagement = repair_tamil_splits(updated_draft.engagement)
            updated_draft.cta = repair_tamil_splits(updated_draft.cta)

        # Final deterministic mode purity cleanup (hybrid suffixes, Tanglish slips, Pure Tamil transliteration, Sen-Tamil)
        c4_flag_note = _apply_mode_post_cleanup(updated_draft, inp, fixes_applied)

        # Deterministic Step 3 minimum word-count enforcement for 45s & 60s scripts
        duration_expanded_note = _enforce_45s_60s_word_minimum(
            updated_draft, inp, fixes_applied
        )

        # Post-audit deterministic verification
        post_audit = run_deterministic_audit(updated_draft, inp)

        # Criterion 6: Respectful Single-Narrator & Anti-AI Cliché
        c6_default = (
            "Direct single-narrator spoken English verified; zero AI clichés."
            if is_english
            else "Single-narrator respectful tone verified; zero AI clichés."
        )
        c6_raw = _check_entry("respectful_and_cliche_free", c6_default)
        c6_status = c6_raw["status"]
        c6_notes = c6_raw["notes"]

        c6_failures = []
        if post_audit["cliche_hits"]:
            c6_failures.append(
                f"Banned clichés/forbidden words remain: {', '.join(post_audit['cliche_hits'])}"
            )
        if post_audit["slang_hits"]:
            c6_failures.append(
                f"Disrespectful slang remains: {', '.join(post_audit['slang_hits'])}"
            )
        if post_audit["skit_hits"]:
            c6_failures.append(
                f"2-person skit markers remain: {', '.join(post_audit['skit_hits'])}"
            )
        if c6_failures:
            c6_status = "FLAG"
            c6_notes = "; ".join(c6_failures)

        # Criterion 7: Tamil Word Integrity & Vocal Modulation (English skips Tamil integrity checks)
        c7_default = (
            "Spoken English flow and vocal modulation cues verified (Tamil checks skipped)."
            if is_english
            else "Tamil Unicode integrity and vocal modulation cues verified."
        )
        c7_raw = _check_entry("tamil_integrity_and_modulation", c7_default)
        c7_status = c7_raw["status"]
        c7_notes = c7_raw["notes"]

        c7_failures = []
        if post_audit["tamil_issues"]:
            c7_failures.extend(post_audit["tamil_issues"])
        if has_structured_checks and len(post_audit["modulation_cues"]) < 2:
            c7_failures.append(
                f"Insufficient vocal modulation cues ({len(post_audit['modulation_cues'])} found; need >= 2)."
            )
        if c7_failures:
            c7_status = "FLAG"
            c7_notes = "; ".join(c7_failures)

        c1 = _check_entry("unsupported_claims", "Verified.")
        c2 = _check_entry("repetition", "No repetition found.")
        c3 = _check_entry("weak_cta", "Specific and aligned.")
        c4_default = (
            "Natural conversational spoken English; zero corporate jargon or AI clichés."
            if is_english
            else "Natural spoken phrasing."
        )
        c4 = _check_entry("unnatural_tamil", c4_default)
        if is_english:
            c4_english_issues = []
            if post_audit["cliche_hits"]:
                c4_english_issues.append(
                    f"AI clichés in English output: {', '.join(post_audit['cliche_hits'])}"
                )
            if post_audit["english_jargon_hits"]:
                c4_english_issues.append(
                    f"Corporate jargon in English output: {', '.join(post_audit['english_jargon_hits'])}"
                )
            if c4_english_issues:
                c4["status"] = "FLAG"
                c4["notes"] = "; ".join(c4_english_issues)
        elif c4_flag_note:
            c4["status"] = "FLAG"
            c4["notes"] = c4_flag_note
        c5 = _check_entry(
            "duration_fit", f"Word count ({updated_draft.word_count}w) calibrated."
        )
        if duration_expanded_note:
            final_wc = updated_draft.word_count
            c5["status"] = (
                "PASS" if limits["min"] <= final_wc <= limits["max"] else "FLAG"
            )
            c5["notes"] = duration_expanded_note

        qc_result = QualityCheckResult(
            unsupported_claims=CheckItem(status=c1["status"], notes=c1["notes"]),
            repetition=CheckItem(status=c2["status"], notes=c2["notes"]),
            weak_cta=CheckItem(status=c3["status"], notes=c3["notes"]),
            unnatural_tamil=CheckItem(status=c4["status"], notes=c4["notes"]),
            duration_fit=CheckItem(status=c5["status"], notes=c5["notes"]),
            respectful_and_cliche_free=CheckItem(status=c6_status, notes=c6_notes),
            tamil_integrity_and_modulation=CheckItem(status=c7_status, notes=c7_notes),
            fixes_applied=fixes_applied,
        )

        return qc_result, updated_draft

    def audit_fast_path(
        self,
        inp: ScriptInput,
        draft: ScriptDraft,
        mode: str = "regenerate_hook",
    ) -> Tuple[QualityCheckResult, ScriptDraft]:
        """Zero-LLM deterministic audit for hook/CTA regeneration (~75% token reduction)."""
        self.last_usage = {}
        is_english = (inp.tone or "").strip() == "English"
        updated_draft = draft.model_copy(deep=True)
        fixes_applied: List[str] = []
        extra_forbidden = inp.brand_dna.forbidden_words if inp.brand_dna else []

        if not is_english:
            repaired_hook = repair_tamil_splits(updated_draft.hook)
            if repaired_hook != updated_draft.hook:
                updated_draft.hook = repaired_hook
                fixes_applied.append(
                    "Repaired spaced Tamil uyirmei combining mark in regenerated hook."
                )

            repaired_cta = repair_tamil_splits(updated_draft.cta)
            if repaired_cta != updated_draft.cta:
                updated_draft.cta = repaired_cta
                fixes_applied.append(
                    "Repaired spaced Tamil uyirmei combining mark in regenerated CTA."
                )

            for h in updated_draft.hooks:
                h.text = repair_tamil_splits(h.text)
            for c in updated_draft.cta_options:
                c.text = repair_tamil_splits(c.text)

        def _is_clean_candidate(text: str) -> bool:
            if not text or not text.strip():
                return False
            if find_banned_cliches(text, extra_forbidden=extra_forbidden):
                return False
            if is_english and find_corporate_jargon(text):
                return False
            slang_skits = find_disrespectful_slang_and_skits(text)
            if slang_skits["slang"] or slang_skits["skits"]:
                return False
            if is_english:
                if text.count("[") != text.count("]"):
                    return False
            elif check_tamil_unicode_integrity(text):
                return False
            return True

        if mode == "regenerate_hook" and not _is_clean_candidate(updated_draft.hook):
            for h in updated_draft.hooks:
                if _is_clean_candidate(h.text):
                    updated_draft.hook = h.text
                    for item in updated_draft.hooks:
                        item.is_recommended = item is h
                    fixes_applied.append(
                        "Swapped active hook to clean guardrail-compliant hook option."
                    )
                    break

        if mode == "regenerate_cta" and not _is_clean_candidate(updated_draft.cta):
            for c in updated_draft.cta_options:
                if _is_clean_candidate(c.text):
                    updated_draft.cta = c.text
                    for item in updated_draft.cta_options:
                        item.is_recommended = item is c
                    fixes_applied.append(
                        "Swapped active CTA to clean guardrail-compliant CTA option."
                    )
                    break

        hook_spoken_only = re.sub(r"\[[^\]]+\]", " ", updated_draft.hook)
        hook_words = len(
            re.findall(
                r"[\w\u0B80-\u0BFF]+(?:['\-][\w\u0B80-\u0BFF]+)*", hook_spoken_only
            )
        )
        if mode == "regenerate_hook" and hook_words > 12:
            for h in updated_draft.hooks:
                h_spoken = re.sub(r"\[[^\]]+\]", " ", h.text)
                h_wc = len(
                    re.findall(
                        r"[\w\u0B80-\u0BFF]+(?:['\-][\w\u0B80-\u0BFF]+)*", h_spoken
                    )
                )
                if h_wc <= 12 and _is_clean_candidate(h.text):
                    updated_draft.hook = h.text
                    for item in updated_draft.hooks:
                        item.is_recommended = item is h
                    fixes_applied.append(
                        f"Selected <=12-word hook option ({h_wc}w) for punchy pacing."
                    )
                    break

        c4_flag_note = _apply_mode_post_cleanup(updated_draft, inp, fixes_applied)

        post_audit = run_deterministic_audit(updated_draft, inp)
        c6_failures = []
        if post_audit["cliche_hits"]:
            c6_failures.append(
                f"Banned clichés/forbidden words: {', '.join(post_audit['cliche_hits'])}"
            )
        if post_audit["slang_hits"]:
            c6_failures.append(
                f"Disrespectful slang: {', '.join(post_audit['slang_hits'])}"
            )
        if post_audit["skit_hits"]:
            c6_failures.append(
                f"2-person skit markers: {', '.join(post_audit['skit_hits'])}"
            )

        c7_failures = list(post_audit["tamil_issues"])
        if len(post_audit["modulation_cues"]) < 2:
            c7_failures.append(
                f"Insufficient vocal modulation cues ({len(post_audit['modulation_cues'])} found; need >= 2)."
            )

        c4_status = "PASS"
        c4_notes = "Conversational spoken Tamil/Tanglish mode rules enforced."
        if is_english:
            eng_c4_issues = []
            if post_audit["cliche_hits"]:
                eng_c4_issues.append(
                    f"Banned AI clichés: {', '.join(post_audit['cliche_hits'])}"
                )
            if post_audit["english_jargon_hits"]:
                eng_c4_issues.append(
                    f"Corporate jargon: {', '.join(post_audit['english_jargon_hits'])}"
                )
            if eng_c4_issues:
                c4_status = "FLAG"
                c4_notes = "; ".join(eng_c4_issues)
            else:
                c4_notes = "Fast-path Python audit: Natural spoken English rhythm verified; zero AI clichés or corporate jargon."
        elif c4_flag_note:
            c4_status = "FLAG"
            c4_notes = c4_flag_note

        c7_ok_note = (
            "Fast-path Python audit: Spoken English flow & vocal modulation cues verified (Tamil checks skipped)."
            if is_english
            else "Fast-path Python audit: Tamil Unicode integrity & modulation cues verified."
        )

        limits = get_word_count_limits(inp.duration, inp.tone)
        actual_words = updated_draft.word_count
        duration_ok = (limits["min"] - 5) <= actual_words <= (limits["max"] + 5)

        qc_result = QualityCheckResult(
            unsupported_claims=CheckItem(
                status="PASS",
                notes="Preserved verified research from base deliverable.",
            ),
            repetition=CheckItem(
                status="PASS",
                notes="Fast-path Python audit: body preserved without duplication.",
            ),
            weak_cta=CheckItem(
                status="PASS" if updated_draft.cta.strip() else "FLAG",
                notes="CTA specific and preserved."
                if updated_draft.cta.strip()
                else "Empty CTA.",
            ),
            unnatural_tamil=CheckItem(
                status=c4_status,
                notes=c4_notes,
            ),
            duration_fit=CheckItem(
                status="PASS" if duration_ok else "FLAG",
                notes=f"Spoken word count ({actual_words}w) vs {limits['min']}-{limits['max']}w target.",
            ),
            respectful_and_cliche_free=CheckItem(
                status="FLAG" if c6_failures else "PASS",
                notes="; ".join(c6_failures)
                if c6_failures
                else "Fast-path Python audit: single-narrator respectful tone; zero AI clichés.",
            ),
            tamil_integrity_and_modulation=CheckItem(
                status="FLAG" if c7_failures else "PASS",
                notes="; ".join(c7_failures) if c7_failures else c7_ok_note,
            ),
            fixes_applied=fixes_applied,
        )
        return qc_result, updated_draft
