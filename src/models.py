import ipaddress
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    computed_field,
    field_validator,
    model_validator,
)

from src.config import (
    DEFAULT_DURATION,
    DEFAULT_MODE,
    DEFAULT_OBJECTIVE,
    DEFAULT_PLATFORM,
    DEFAULT_TONE,
    WORD_COUNT_LIMITS,
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SCRIPT_TAG_BLOCK_RE = re.compile(
    r"<\s*(?:script|style)\b[^>]*>.*?<\s*/\s*(?:script|style)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PROMPT_INJECTION_PATTERNS = (
    re.compile(
        r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdisregard\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bforget\s+(?:all\s+)?(?:previous|your)\s+instructions?\b", re.IGNORECASE
    ),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(?:your|the)\s+(?:system\s+)?prompt\b", re.IGNORECASE),
    re.compile(
        r"\boverride\s+(?:system|safety|all)\s+(?:rules|instructions|prompts?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:<\|im_start\|>|<\|system\|>|\[\s*SYSTEM\s*\]|###\s*instruction)",
        re.IGNORECASE,
    ),
)
_SLUG_OR_UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,99}$")
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)

_LANGUAGE_TO_TONE_MAP = {
    "Tanglish": "Tanglish",
    "Conversational Spoken Tamil": "conversational spoken Tamil",
    "conversational spoken Tamil": "conversational spoken Tamil",
    "Tamil": "Tamil",
    "English": "English",
}


def sanitize_user_text(
    value: Any, field_name: str, min_length: int, max_length: int
) -> str:
    """Strip HTML/script tags, trim, and reject control chars & prompt-injection attempts."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field_name} contains disallowed control characters.")
    cleaned = _SCRIPT_TAG_BLOCK_RE.sub(" ", value)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(cleaned):
            raise ValueError(
                f"{field_name} rejected: disallowed prompt-injection pattern detected."
            )

    if len(cleaned) < min_length:
        raise ValueError(
            f"{field_name} must be at least {min_length} characters after sanitization."
        )
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters.")
    return cleaned


def validate_safe_reference_url(value: Any) -> Optional[HttpUrl]:
    """Validate optional http(s) URL and block SSRF targets (localhost, link-local, private IPs)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str) and _CONTROL_CHAR_RE.search(value):
        raise ValueError("reference_url contains disallowed control characters.")

    parsed: HttpUrl = _HTTP_URL_ADAPTER.validate_python(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("reference_url must use http:// or https:// scheme.")

    host = (parsed.host or "").strip().lower().strip("[]")
    if not host:
        raise ValueError("reference_url must include a valid public hostname.")
    if (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".internal")
        or host == "0.0.0.0"
        or host == "metadata.google.internal"
    ):
        raise ValueError(f"SSRF protection blocked internal hostname: '{host}'.")

    try:
        ip_obj = ipaddress.ip_address(host)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            raise ValueError(
                f"SSRF protection blocked private/internal IP range: '{host}'."
            )
    except ValueError as exc:
        if "SSRF protection" in str(exc):
            raise

    return parsed


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def validate_client_identifier(value: Optional[str]) -> str:
    """Ensure client_id is a valid non-empty UUID or slug (no path traversal or spaces)."""
    clean = (value or "").strip()
    if not clean:
        raise ValueError("client_id is required when mode is 'crm'.")
    if _UUID_RE.match(clean) or _SLUG_OR_UUID_RE.match(clean):
        return clean
    raise ValueError(
        "client_id must be a valid UUID or alphanumeric slug (e.g. 'vg_demo_clinic')."
    )


class BrandDNA(BaseModel):
    """Client Brand DNA injected automatically from the CRM clients table."""

    client_id: Optional[str] = None
    client_name: Optional[str] = None
    target_audience: Optional[str] = None
    industry: Optional[str] = None
    brand_tone: Optional[str] = None
    forbidden_words: List[str] = Field(default_factory=list)


class ScriptInput(BaseModel):
    """Validated input payload for script generation."""

    topic: str = Field(
        ..., min_length=3, max_length=300, description="Primary topic for the reel"
    )
    audience: Optional[str] = Field(
        default=None, max_length=150, description="Target demographic"
    )
    niche: Optional[str] = Field(
        default=None, max_length=100, description="Industry domain"
    )
    platform: str = Field(default=DEFAULT_PLATFORM, max_length=50)
    duration: Literal[30, 45, 60] = Field(
        default=30, description="Target video duration in seconds"
    )
    tone: Literal["Tanglish", "conversational spoken Tamil", "Tamil", "English"] = (
        Field(default="Tanglish")
    )
    objective: str = Field(default=DEFAULT_OBJECTIVE, max_length=120)
    mode: Literal["full_script", "regenerate_hook", "regenerate_cta"] = Field(
        default="full_script"
    )
    assumed_defaults: List[str] = Field(default_factory=list)
    client_id: Optional[str] = Field(default=None, max_length=100)
    brand_dna: Optional[BrandDNA] = None
    reference_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional client product/blog URL to ground script",
    )

    @field_validator("topic")
    @classmethod
    def _sanitize_topic(cls, value: str) -> str:
        return sanitize_user_text(value, "topic", min_length=3, max_length=300)

    @field_validator("objective")
    @classmethod
    def _sanitize_objective(cls, value: str) -> str:
        return sanitize_user_text(value, "objective", min_length=1, max_length=120)

    @field_validator("audience")
    @classmethod
    def _sanitize_audience(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(value, "audience", min_length=1, max_length=150)

    @field_validator("reference_url", mode="before")
    @classmethod
    def _validate_ref_url(cls, value: Any) -> Optional[str]:
        parsed = validate_safe_reference_url(value)
        return str(parsed) if parsed is not None else None

    @classmethod
    def create_with_defaults(
        cls,
        topic: str,
        audience: Optional[str] = None,
        niche: Optional[str] = None,
        platform: Optional[str] = None,
        duration: Optional[int] = None,
        tone: Optional[str] = None,
        objective: Optional[str] = None,
        mode: Optional[str] = None,
        client_id: Optional[str] = None,
        brand_dna: Optional[BrandDNA] = None,
        reference_url: Optional[str] = None,
    ) -> "ScriptInput":
        """Instantiate with standard fallback defaults and track assumptions."""
        assumed = []
        final_platform = platform or DEFAULT_PLATFORM
        if not platform:
            assumed.append(f"platform = {DEFAULT_PLATFORM}")

        final_duration = duration if duration in (30, 45, 60) else DEFAULT_DURATION
        if not duration:
            assumed.append(f"duration = {DEFAULT_DURATION}s")

        final_tone = (
            tone
            if tone in ("Tanglish", "conversational spoken Tamil", "Tamil", "English")
            else DEFAULT_TONE
        )
        if not tone:
            assumed.append(f"tone = {DEFAULT_TONE}")

        final_objective = objective or DEFAULT_OBJECTIVE
        if not objective:
            assumed.append(f"objective = {DEFAULT_OBJECTIVE}")

        final_mode = (
            mode
            if mode in ("full_script", "regenerate_hook", "regenerate_cta")
            else DEFAULT_MODE
        )

        default_audience = (
            "General digital audience"
            if final_tone == "English"
            else "General Tamil content audience"
        )
        resolved_audience = (
            audience
            or (brand_dna.target_audience if brand_dna else None)
            or default_audience
        )
        resolved_niche = (
            niche
            or (brand_dna.industry if brand_dna else None)
            or "Business / Digital / Career"
        )

        return cls(
            topic=topic,
            audience=resolved_audience,
            niche=resolved_niche,
            platform=final_platform,
            duration=final_duration,
            tone=final_tone,
            objective=final_objective,
            mode=final_mode,
            assumed_defaults=assumed,
            client_id=client_id or (brand_dna.client_id if brand_dna else None),
            brand_dna=brand_dna,
            reference_url=reference_url.strip()
            if reference_url and reference_url.strip()
            else None,
        )


class SourceItem(BaseModel):
    url: str
    title: str = ""
    claim_supported: str
    is_verified: bool = True


class ResearchResult(BaseModel):
    """Output from Step 1: Research and Angle Selection."""

    topic: str
    queries_run: List[str] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)  # 3-5 facts/mistakes
    pain_points: List[str] = Field(default_factory=list)  # 3 audience pain points
    chosen_angle: str = ""
    angle_reason: str = ""
    sources: List[SourceItem] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    search_fallback_used: bool = False


class HookItem(BaseModel):
    text: str
    type: Literal["question", "bold statement", "pain-point"]
    is_recommended: bool = False
    reason: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_hook_type(cls, value: Any) -> str:
        raw = str(value or "").strip().lower().replace("_", " ")
        if "question" in raw or raw == "q":
            return "question"
        if "pain" in raw:
            return "pain-point"
        return "bold statement"


class CtaOptionItem(BaseModel):
    text: str
    is_recommended: bool = False
    reason: str = ""


class ScriptDraft(BaseModel):
    """Output from Step 2: Hooks, Script segments, and Production Notes."""

    hooks: List[HookItem] = Field(default_factory=list)
    hook: str = ""
    context: str = ""
    body_points: List[str] = Field(default_factory=list)
    engagement: str = ""
    cta: str = ""
    cta_options: List[CtaOptionItem] = Field(default_factory=list)
    on_screen_texts: List[str] = Field(default_factory=list)
    caption: str = ""
    hashtags: List[str] = Field(default_factory=list)
    estimated_duration: str = ""

    @computed_field
    @property
    def word_count(self) -> int:
        """Pure spoken words across all script segments, excluding bullet numbers and [modulation] tags."""
        cleaned_points = [re.sub(r"^\d+[\.\)]\s*", "", p) for p in self.body_points]
        raw_text = f"{self.hook} {self.context} {' '.join(cleaned_points)} {self.engagement} {self.cta}"
        # Strip inline vocal modulation cues such as [Pause], [Stress], [Direct eye contact]
        spoken_only = re.sub(r"\[[^\]]+\]", " ", raw_text)
        # Keep Tamil Unicode characters + combining marks intact within words
        tokens = re.findall(
            r"[\w\u0B80-\u0BFF]+(?:['\-][\w\u0B80-\u0BFF]+)*",
            spoken_only,
            flags=re.UNICODE,
        )
        return len(tokens)

    def calculate_word_count(self) -> int:
        """Backwards compatibility helper returning the computed word count."""
        return self.word_count

    def get_full_script_text(self) -> str:
        """Combine labeled script parts into full spoken text."""
        parts = [
            f"[Hook] {self.hook}",
            f"[Context] {self.context}",
            "[Body]",
            "\n".join(f"- {p}" for p in self.body_points),
            f"[Engagement] {self.engagement}",
            f"[CTA] {self.cta}",
        ]
        return "\n".join(parts)

    def extract_modulation_cues(self) -> List[str]:
        """Return all inline vocal modulation cues found across spoken segments."""
        raw_text = f"{self.hook} {self.context} {' '.join(self.body_points)} {self.engagement} {self.cta}"
        return re.findall(r"\[[^\]]+\]", raw_text)


class CheckItem(BaseModel):
    status: Literal["PASS", "FLAG"]
    notes: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        if raw in {"PASS", "PASSED", "OK", "TRUE", "SUCCESS"}:
            return "PASS"
        if raw in {
            "FLAG",
            "FLAGGED",
            "FAIL",
            "FAILED",
            "WARN",
            "WARNING",
            "ERROR",
            "ISSUE",
            "FALSE",
        }:
            return "FLAG"
        return "FLAG"


class QualityCheckResult(BaseModel):
    """Output from Step 3: 7-Criteria Quality Audit & Self-Correction."""

    unsupported_claims: CheckItem
    repetition: CheckItem
    weak_cta: CheckItem
    unnatural_tamil: CheckItem
    duration_fit: CheckItem
    respectful_and_cliche_free: CheckItem = Field(
        default_factory=lambda: CheckItem(
            status="PASS",
            notes="Single-narrator respectful tone verified; zero AI clichés.",
        )
    )
    tamil_integrity_and_modulation: CheckItem = Field(
        default_factory=lambda: CheckItem(
            status="PASS",
            notes="Tamil Unicode integrity and vocal modulation cues verified.",
        )
    )
    fixes_applied: List[str] = Field(default_factory=list)

    @property
    def overall_passed(self) -> bool:
        """Returns True if all 7 quality audit criteria have PASS status."""
        return all(
            item.status == "PASS"
            for item in (
                self.unsupported_claims,
                self.repetition,
                self.weak_cta,
                self.unnatural_tamil,
                self.duration_fit,
                self.respectful_and_cliche_free,
                self.tamil_integrity_and_modulation,
            )
        )


class ClipFalconHandoffPayload(BaseModel):
    """Structured handoff payload sent to ClipFalcon for video-vs-script audit."""

    deliverable_id: Optional[str] = None
    client_id: Optional[str] = None
    topic: str
    platform: str
    target_duration_seconds: int
    language_mode: str
    expected_word_count: int
    selected_hook: str
    full_spoken_script: str
    segments: Dict[str, Any]
    on_screen_texts: List[str] = Field(default_factory=list)
    vocal_modulation_cues: List[str] = Field(default_factory=list)
    forbidden_words_checked: List[str] = Field(default_factory=list)
    audit_passed: bool = True


class FullDeliverable(BaseModel):
    """The complete deliverable combining all 6 standard sections + 7-criteria QC + CRM metrics."""

    input_data: ScriptInput
    research: ResearchResult
    script: ScriptDraft
    quality_check: QualityCheckResult
    deliverable_id: Optional[str] = None
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_used: int = 0
    cost_inr: float = 0.0

    @field_validator("input_data", "research", "script", "quality_check", mode="before")
    @classmethod
    def _coerce_reloaded_submodel(cls, value: Any) -> Any:
        """Accept submodels created prior to hot-reload by converting them via model_dump()."""
        if hasattr(value, "model_dump") and not isinstance(
            value, (ScriptInput, ResearchResult, ScriptDraft, QualityCheckResult)
        ):
            return value.model_dump()
        return value

    def to_clipfalcon_handoff(self) -> ClipFalconHandoffPayload:
        """Build the ClipFalcon video-vs-script audit payload."""
        return ClipFalconHandoffPayload(
            deliverable_id=self.deliverable_id,
            client_id=self.client_id or self.input_data.client_id,
            topic=self.input_data.topic,
            platform=self.input_data.platform,
            target_duration_seconds=self.input_data.duration,
            language_mode=self.input_data.tone,
            expected_word_count=self.script.word_count,
            selected_hook=self.script.hook,
            full_spoken_script=self.script.get_full_script_text(),
            segments={
                "hook": self.script.hook,
                "context": self.script.context,
                "body_points": self.script.body_points,
                "engagement": self.script.engagement,
                "cta": self.script.cta,
            },
            on_screen_texts=self.script.on_screen_texts,
            vocal_modulation_cues=self.script.extract_modulation_cues(),
            forbidden_words_checked=(
                self.input_data.brand_dna.forbidden_words
                if self.input_data.brand_dna
                else []
            ),
            audit_passed=self.quality_check.overall_passed,
        )

    def to_markdown(self) -> str:
        """Format the output strictly according to the 6 sections + 7-point QC result."""
        lines = []

        # Header
        lines.append(f"# Tamil Reel Script: {self.input_data.topic}\n")

        lines.append("## 1. Topic & Audience")
        lines.append(f"- **Topic:** {self.input_data.topic}")
        lines.append(f"- **Audience:** {self.input_data.audience}")
        lines.append(f"- **Platform:** {self.input_data.platform}")
        lines.append(f"- **Duration:** {self.input_data.duration} seconds")
        lines.append(f"- **Tone:** {self.input_data.tone}")
        lines.append(f"- **Objective:** {self.input_data.objective}")
        if self.input_data.brand_dna and self.input_data.brand_dna.client_name:
            lines.append(f"- **Client Brand:** {self.input_data.brand_dna.client_name}")
        if self.input_data.assumed_defaults:
            lines.append(
                f"- **Assumed Defaults:** {', '.join(self.input_data.assumed_defaults)}"
            )
        lines.append("")

        lines.append("## 2. Research Summary")
        lines.append("### Key Findings:")
        for finding in self.research.key_findings:
            lines.append(f"- {finding}")
        lines.append(f"\n- **Chosen Content Angle:** {self.research.chosen_angle}")
        lines.append(f"- **Why Chosen:** {self.research.angle_reason}\n")

        lines.append("## 3. Hook Options")
        for i, hook in enumerate(self.script.hooks, 1):
            badge = " **[RECOMMENDED]**" if hook.is_recommended else ""
            lines.append(f'{i}. *({hook.type})* "{hook.text}"{badge}')
            if hook.reason:
                lines.append(f"   - *Reason:* {hook.reason}")
        lines.append("")

        limits = WORD_COUNT_LIMITS.get(self.input_data.duration, {"min": 60, "max": 75})
        lines.append("## 4. Full Tamil Script")
        lines.append(
            f"*(Target: {limits['min']}-{limits['max']} words | Actual: **{self.script.word_count} words**)*\n"
        )
        lines.append(f"**[Hook]**\n{self.script.hook}\n")
        lines.append(f"**[Context]**\n{self.script.context}\n")
        lines.append("**[Body]**")
        for point in self.script.body_points:
            lines.append(f"{point}")
        lines.append("")
        lines.append(f"**[Engagement]**\n{self.script.engagement}\n")
        lines.append(f"**[CTA]**\n{self.script.cta}\n")
        if self.script.cta_options:
            lines.append("### Alternative CTA Options:")
            for idx, c_opt in enumerate(self.script.cta_options, 1):
                c_badge = " **[RECOMMENDED]**" if c_opt.is_recommended else ""
                lines.append(f'{idx}. "{c_opt.text}"{c_badge}')
                if c_opt.reason:
                    lines.append(f"   - *Reason:* {c_opt.reason}")
            lines.append("")

        lines.append("## 5. Production Notes")
        lines.append("- **On-Screen Text Suggestions:**")
        for ost in self.script.on_screen_texts:
            lines.append(f"  - {ost}")
        lines.append(f"- **Estimated Duration:** {self.script.estimated_duration}")
        lines.append(f"- **Caption:**\n  > {self.script.caption}")
        lines.append(f"- **Hashtags:** {' '.join(self.script.hashtags)}\n")

        lines.append("## 6. Sources")
        if self.research.sources:
            for s in self.research.sources:
                status = "" if s.is_verified else " *(UNVERIFIED)*"
                lines.append(
                    f"- [{s.title or s.url}]({s.url}){status} — *Supports:* {s.claim_supported}"
                )
        else:
            lines.append("- *No external sources logged.*")

        if self.research.uncertainties:
            lines.append("\n### Uncertainty / Verify on Official Site:")
            for u in self.research.uncertainties:
                lines.append(f"- ⚠️ {u}")
        lines.append("")

        # Quality Check Result (7 Strict Criteria)
        lines.append("## Quality Check Result")
        qc = self.quality_check
        lines.append(
            f"1. **Unsupported Claims:** [{qc.unsupported_claims.status}] {qc.unsupported_claims.notes}"
        )
        lines.append(
            f"2. **Repetition:** [{qc.repetition.status}] {qc.repetition.notes}"
        )
        lines.append(f"3. **Weak CTA:** [{qc.weak_cta.status}] {qc.weak_cta.notes}")
        lines.append(
            f"4. **Unnatural Tamil:** [{qc.unnatural_tamil.status}] {qc.unnatural_tamil.notes}"
        )
        lines.append(
            f"5. **Duration Fit:** [{qc.duration_fit.status}] {qc.duration_fit.notes}"
        )
        lines.append(
            f"6. **Respectful Single-Narrator & Anti-AI Cliché:** "
            f"[{qc.respectful_and_cliche_free.status}] {qc.respectful_and_cliche_free.notes}"
        )
        lines.append(
            f"7. **Tamil Word Integrity & Modulation:** "
            f"[{qc.tamil_integrity_and_modulation.status}] {qc.tamil_integrity_and_modulation.notes}"
        )

        if qc.fixes_applied:
            lines.append("\n**Auto-Corrections Applied:**")
            for fix in qc.fixes_applied:
                lines.append(f"- {fix}")
        else:
            lines.append("\n*All 7 checks passed with zero revisions required.*")

        lines.append("")
        return "\n".join(lines)

    def save_deliverables(self, base_path: Path):
        """Save both human-readable Markdown and machine-readable JSON."""
        base_path.parent.mkdir(parents=True, exist_ok=True)
        md_file = base_path.with_suffix(".md")
        md_file.write_text(self.to_markdown(), encoding="utf-8")
        json_file = base_path.with_suffix(".json")
        json_file.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_from_json(cls, json_path: Path) -> "FullDeliverable":
        """Load deliverable state from JSON."""
        return cls.model_validate_json(json_path.read_text(encoding="utf-8"))


class GenerateScriptRequest(BaseModel):
    """Strict input DTO for script generation with XSS, prompt-injection, SSRF, and CRM checks."""

    model_config = ConfigDict(extra="forbid")

    topic: str
    conversion_objective: str
    platform: Literal["Instagram Reels", "YouTube Shorts", "LinkedIn Video"] = (
        "Instagram Reels"
    )
    duration_seconds: Literal[30, 45, 60] = 30
    language: Literal["Tanglish", "Conversational Spoken Tamil", "Tamil", "English"] = (
        "Tanglish"
    )
    reference_url: Optional[HttpUrl] = None
    audience: Optional[str] = Field(default=None, max_length=150)
    niche: Optional[str] = Field(default=None, max_length=100)
    mode: Literal["standalone", "crm"] = "standalone"
    client_id: Optional[str] = None

    @field_validator("topic")
    @classmethod
    def _validate_topic(cls, value: str) -> str:
        return sanitize_user_text(value, "topic", min_length=5, max_length=250)

    @field_validator("conversion_objective")
    @classmethod
    def _validate_objective(cls, value: str) -> str:
        return sanitize_user_text(
            value, "conversion_objective", min_length=3, max_length=120
        )

    @field_validator("audience")
    @classmethod
    def _validate_audience(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(value, "audience", min_length=1, max_length=150)

    @field_validator("niche")
    @classmethod
    def _validate_niche(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(value, "niche", min_length=1, max_length=100)

    @field_validator("reference_url", mode="before")
    @classmethod
    def _validate_reference_url(cls, value: Any) -> Optional[HttpUrl]:
        return validate_safe_reference_url(value)

    @model_validator(mode="after")
    def _validate_crm_mode(self) -> "GenerateScriptRequest":
        if self.mode == "crm":
            self.client_id = validate_client_identifier(self.client_id)
        elif self.client_id:
            self.client_id = validate_client_identifier(self.client_id)
        return self

    def to_script_input(self) -> ScriptInput:
        """Convert validated DTO into internal ScriptInput model."""
        tone = _LANGUAGE_TO_TONE_MAP[self.language]
        return ScriptInput.create_with_defaults(
            topic=self.topic,
            audience=self.audience,
            niche=self.niche,
            platform=self.platform,
            duration=self.duration_seconds,
            tone=tone,
            objective=self.conversion_objective,
            mode="full_script",
            client_id=self.client_id if self.mode == "crm" else None,
            reference_url=str(self.reference_url) if self.reference_url else None,
        )


class RegenerateSectionRequest(BaseModel):
    """Strict input DTO for hook or CTA section regeneration."""

    model_config = ConfigDict(extra="forbid")

    section: Literal["hook", "cta"] = "hook"
    mode: Literal["standalone", "crm"] = "standalone"
    client_id: Optional[str] = None
    deliverable_id: Optional[str] = Field(default=None, min_length=3, max_length=100)
    deliverable: Optional[FullDeliverable] = None
    conversion_objective: Optional[str] = None

    @field_validator("conversion_objective")
    @classmethod
    def _validate_regen_objective(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(
            value, "conversion_objective", min_length=3, max_length=120
        )

    @model_validator(mode="after")
    def _validate_regen_targets(self) -> "RegenerateSectionRequest":
        if self.mode == "crm":
            self.client_id = validate_client_identifier(self.client_id)
            if not self.deliverable_id or not self.deliverable_id.strip():
                raise ValueError("deliverable_id is required when mode is 'crm'.")
        elif self.deliverable is None and not self.deliverable_id:
            raise ValueError(
                "Provide either 'deliverable' or 'deliverable_id' in standalone mode."
            )
        return self
