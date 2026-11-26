"""Configuration, pricing, budgets, and centralized guardrails for ScriptFalcon."""

import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

# Load .env file from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Spoken speed calibration
# Tamil / Tanglish: ~2.2 words per second
WORD_COUNT_LIMITS = {
    30: {"min": 60, "max": 75, "target": 68},
    45: {"min": 95, "max": 110, "target": 102},
    60: {"min": 125, "max": 145, "target": 135},
}

# English: ~2.3 - 2.5 words per second
ENGLISH_WORD_COUNT_LIMITS = {
    30: {"min": 65, "max": 80, "target": 72},
    45: {"min": 100, "max": 120, "target": 110},
    60: {"min": 130, "max": 155, "target": 142},
}


def get_word_count_limits(
    duration: int, tone: str = "conversational spoken Tamil"
) -> Dict[str, int]:
    """Return spoken word-count limits calibrated for the active duration and language mode."""
    table = (
        ENGLISH_WORD_COUNT_LIMITS
        if (tone or "").strip() == "English"
        else WORD_COUNT_LIMITS
    )
    return table.get(duration, table[30])


# Standard Prompt Defaults
DEFAULT_PLATFORM = "Instagram Reels"
DEFAULT_DURATION = 30
DEFAULT_TONE = "conversational spoken Tamil"
DEFAULT_OBJECTIVE = "awareness"
DEFAULT_MODE = "full_script"


def _get_setting(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return val if val else default


# Token & Generation Hardening (Step 1)
# 3,000 output tokens prevents Tamil Unicode truncation mid-sentence.
MAX_OUTPUT_TOKENS = int(_get_setting("MAX_OUTPUT_TOKENS", "3000"))
REGENERATION_MAX_OUTPUT_TOKENS = int(
    _get_setting("REGENERATION_MAX_OUTPUT_TOKENS", "1000")
)
LLM_TEMPERATURE = float(_get_setting("LLM_TEMPERATURE", "0.4"))
GEMINI_THINKING_LEVEL = _get_setting("GEMINI_THINKING_LEVEL", "low")

# Model Configurations (Centralized — non-deprecated production snapshots only)
LLM_PROVIDER = _get_setting("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_API_KEY = _get_setting("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = _get_setting("OPENAI_API_KEY", "")
GEMINI_API_KEY = _get_setting("GEMINI_API_KEY", "")

_DEPRECATED_MODEL_UPGRADES = {
    "claude-3-5-sonnet-20241022": "claude-sonnet-4-20250514",
    "gemini-3.1-flash-lite": "gemini-3.5-flash-lite",
}

ANTHROPIC_MODEL = _DEPRECATED_MODEL_UPGRADES.get(
    _get_setting("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    _get_setting("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
)
OPENAI_MODEL = _get_setting("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = _DEPRECATED_MODEL_UPGRADES.get(
    _get_setting("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    _get_setting("GEMINI_MODEL", "gemini-3.5-flash-lite"),
)

# Currency & Live Model Pricing (USD per 1M tokens)
USD_TO_INR_RATE = float(_get_setting("USD_TO_INR_RATE", "85.0"))

MODEL_PRICING_USD_PER_1M: Dict[str, Dict[str, float]] = {
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.6-flash": {"input": 0.30, "output": 2.50},
    "gemini-3.8-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "simulation": {"input": 0.30, "output": 2.50},
    "default": {"input": 0.30, "output": 2.50},
}


def calculate_cost_inr(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Compute exact execution cost in INR from token counts and centralized pricing."""
    normalized = (model_name or "default").lower().strip()
    pricing = MODEL_PRICING_USD_PER_1M.get(normalized)
    if pricing is None:
        for key, val in MODEL_PRICING_USD_PER_1M.items():
            if key != "default" and key in normalized:
                pricing = val
                break
    if pricing is None:
        pricing = MODEL_PRICING_USD_PER_1M["default"]

    usd_cost = (max(0, input_tokens) / 1_000_000.0) * pricing["input"] + (
        max(0, output_tokens) / 1_000_000.0
    ) * pricing["output"]
    return round(usd_cost * USD_TO_INR_RATE, 4)


# CRM Quota & Cost Guardrails
DEFAULT_CLIENT_MONTHLY_BUDGET_INR = float(
    _get_setting("DEFAULT_CLIENT_MONTHLY_BUDGET_INR", "60.0")
)
CLIENT_MONTHLY_TOKEN_ESTIMATE = int(
    _get_setting("CLIENT_MONTHLY_TOKEN_ESTIMATE", "280000")
)
FULL_SCRIPT_BUDGET_INR = float(_get_setting("FULL_SCRIPT_BUDGET_INR", "0.50"))
REGENERATION_BUDGET_INR = float(_get_setting("REGENERATION_BUDGET_INR", "0.15"))
QUOTA_RESERVATION_TTL_SECONDS = int(
    _get_setting("QUOTA_RESERVATION_TTL_SECONDS", "300")
)
DAILY_USER_RUN_LIMIT = int(_get_setting("DAILY_USER_RUN_LIMIT", "25"))
DAILY_USER_TOKEN_LIMIT = int(_get_setting("DAILY_USER_TOKEN_LIMIT", "75000"))
DAILY_USER_SPEND_LIMIT_INR = float(_get_setting("DAILY_USER_SPEND_LIMIT_INR", "9.0"))
BONUS_RUNS_DEFAULT = int(_get_setting("BONUS_RUNS_DEFAULT", "10"))
DUPLICATE_SUBMIT_WINDOW_SECONDS = int(
    _get_setting("DUPLICATE_SUBMIT_WINDOW_SECONDS", "30")
)
LOW_BALANCE_WARNING_RATIO = float(_get_setting("LOW_BALANCE_WARNING_RATIO", "0.20"))

# CRM Persistence & Security
DATABASE_URL = _get_setting("DATABASE_URL", "")
SQLITE_DB_PATH = Path(_get_setting("SQLITE_DB_PATH", str(ROOT_DIR / "scriptfalcon.db")))
CRM_JWT_SECRET = _get_setting(
    "CRM_JWT_SECRET", "vg-digital-falcon-dev-secret-change-in-prod"
)
SUPABASE_JWT_SECRET = _get_setting("SUPABASE_JWT_SECRET", "")
CRM_ENV = _get_setting("CRM_ENV", "development").strip().lower()

_DEFAULT_JWT_SECRETS = {
    "vg-digital-falcon-dev-secret-change-in-prod",
    "change-this-in-production",
}
if (
    CRM_ENV == "production"
    and not SUPABASE_JWT_SECRET
    and CRM_JWT_SECRET in _DEFAULT_JWT_SECRETS
):
    raise RuntimeError(
        "CRM_ENV=production but CRM_JWT_SECRET is a public default. "
        "Set a long random CRM_JWT_SECRET (or SUPABASE_JWT_SECRET) before starting."
    )
CLIPFALCON_WEBHOOK_URL = _get_setting("CLIPFALCON_WEBHOOK_URL", "")

# Centralized Guardrail Lists (Single Source of Truth for Prompts & Quality Auditor)
BANNED_AI_CLICHES = (
    "game-changer",
    "game changer",
    "unlock your potential",
    "in today's fast-paced digital world",
    "in today's fast-paced world",
    "fast-paced world",
    "fast-paced digital world",
    "dive deep",
    "delve into",
    "let's dive in",
    "revolutionize",
    "skyrocket",
    "secret sauce",
    "paradigm shift",
    "unleash",
    "elevate your brand",
    "elevate your",
    "digital landscape",
    "stay ahead of the curve",
    "buckle up",
    "without further ado",
    "cutting-edge",
    "next level",
    "இன்றைய வேகமான உலகில்",
    "உங்கள் திறனை திறவுங்கள்",
    "ஆழமாக பார்ப்போம்",
    "கேம் சேஞ்சர்",
    "புரட்சிகரமான",
)

ENGLISH_CORPORATE_JARGON = (
    "synergy",
    "holistic approach",
    "low-hanging fruit",
    "thought leader",
    "streamline your workflow",
    "end-to-end solution",
    "actionable insights",
    "best-in-class",
    "mission-critical",
    "value proposition",
    "move the needle",
    "circle back",
)

ENGLISH_ADDRESS_MARKERS = (
    "you",
    "your",
    "you're",
    "we",
    "our",
)

DISRESPECTFUL_SLANG_BLACKLIST = (
    "avan",
    "ivan",
    "aval",
    "ival",
    "da",
    "di",
    "dei",
    "macha",
    "machan",
    "poda",
    "podi",
    "அவன்",
    "இவன்",
    "அவள்",
    "இவள்",
    "டா",
    "டேய்",
    "மச்சான்",
    "போடா",
)

TWO_PERSON_SKIT_MARKERS = (
    "person a",
    "person b",
    "character a",
    "character b",
    "friend 1",
    "friend 2",
    "speaker 1",
    "speaker 2",
    "customer:",
    "shopkeeper:",
    "interviewer:",
    "நபர் 1",
    "நபர் 2",
)

RESPECTFUL_ADDRESS_MARKERS = (
    "neenga",
    "ungalukku",
    "ungaloda",
    "unga",
    "namma",
    "நீங்க",
    "நீங்கள்",
    "உங்களுக்கு",
    "உங்க",
    "உங்களோட",
    "நம்ம",
    "நமது",
)

VOCAL_MODULATION_MARKERS = (
    "[Pause]",
    "[Stress]",
    "[Question tone]",
    "[Slow down]",
    "[Curious tone]",
    "[Direct eye contact]",
)

# Browser origins allowed to call the API directly (comma-separated).
# Not needed for the bundled frontend (same origin) or the PHP proxy (server-to-server).
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in _get_setting(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]

DELIVERABLES_DIR = ROOT_DIR / "deliverables"
DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
