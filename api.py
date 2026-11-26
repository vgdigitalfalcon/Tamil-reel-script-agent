"""FastAPI REST service for ScriptFalcon & VG Digital Falcon CRM Integration (Async v2.0)."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.auth import AuthenticatedUser, require_employee_user
from src.config import (
    ANTHROPIC_API_KEY,
    BONUS_RUNS_DEFAULT,
    CLIPFALCON_WEBHOOK_URL,
    CORS_ALLOWED_ORIGINS,
    DELIVERABLES_DIR,
    GEMINI_API_KEY,
    LLM_PROVIDER,
    OPENAI_API_KEY,
)
from src.db import (
    ClientNotFoundError,
    CRMDatabase,
    DailyLimitExceededError,
    DeliverableNotFoundError,
    DuplicateRequestError,
    InsufficientQuotaError,
)
from src.models import (
    ClipFalconHandoffPayload,
    FullDeliverable,
    GenerateScriptRequest,
    RegenerateSectionRequest,
    ScriptInput,
    sanitize_user_text,
    validate_client_identifier,
    validate_safe_reference_url,
)
from src.pipeline import TamilReelScriptPipeline

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ScriptFalcon — Tamil Reel Script Agent API",
    description="Async RESTful API for humanized, research-backed Tamil & Tanglish short-form video scripts and CRM integration.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

pipeline = TamilReelScriptPipeline()
_crm_db: Optional[CRMDatabase] = None


def get_crm_db() -> CRMDatabase:
    """Lazily initialize and return the CRM database repository."""
    global _crm_db
    if _crm_db is None:
        _crm_db = CRMDatabase()
    return _crm_db


def _persist_standalone(deliverable: FullDeliverable) -> None:
    """Save a standalone deliverable to the database so it survives redeploys.

    A storage failure is logged but never fails the request: the user still gets their script.
    """
    try:
        get_crm_db().save_standalone_deliverable(deliverable)
    except Exception:
        logger.exception("Failed to persist standalone deliverable")


class GenerateResponse(BaseModel):
    success: bool
    deliverable: FullDeliverable
    markdown: str


class RegenerateHookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deliverable: FullDeliverable


class RegenerateCtaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deliverable: FullDeliverable
    new_objective: Optional[str] = None

    @field_validator("new_objective")
    @classmethod
    def _clean_new_obj(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(value, "new_objective", min_length=3, max_length=120)


class CRMGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(..., min_length=1, max_length=100)
    topic: str = Field(..., min_length=5, max_length=250)
    duration: Literal[30, 45, 60] = 30
    tone: Literal["Tanglish", "conversational spoken Tamil", "Tamil", "English"] = (
        "conversational spoken Tamil"
    )
    objective: str = Field(default="awareness", max_length=120)
    platform: str = Field(default="Instagram Reels", max_length=50)
    audience: Optional[str] = Field(default=None, max_length=150)
    niche: Optional[str] = Field(default=None, max_length=100)
    reference_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("client_id")
    @classmethod
    def _clean_client_id(cls, value: str) -> str:
        return validate_client_identifier(value)

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, value: str) -> str:
        return sanitize_user_text(value, "topic", min_length=5, max_length=250)

    @field_validator("objective")
    @classmethod
    def _clean_objective(cls, value: str) -> str:
        return sanitize_user_text(value, "objective", min_length=3, max_length=120)

    @field_validator("audience")
    @classmethod
    def _clean_audience(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(value, "audience", min_length=1, max_length=150)

    @field_validator("reference_url", mode="before")
    @classmethod
    def _clean_ref_url(cls, value: Any) -> Optional[str]:
        parsed = validate_safe_reference_url(value)
        return str(parsed) if parsed is not None else None


class CRMRegenerateHookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(..., min_length=1, max_length=100)
    deliverable_id: str = Field(..., min_length=1, max_length=100)

    @field_validator("client_id")
    @classmethod
    def _clean_client_id(cls, value: str) -> str:
        return validate_client_identifier(value)


class CRMRegenerateCtaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(..., min_length=1, max_length=100)
    deliverable_id: str = Field(..., min_length=1, max_length=100)
    new_objective: Optional[str] = Field(default=None, max_length=120)

    @field_validator("client_id")
    @classmethod
    def _clean_client_id(cls, value: str) -> str:
        return validate_client_identifier(value)

    @field_validator("new_objective")
    @classmethod
    def _clean_new_obj(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return sanitize_user_text(value, "new_objective", min_length=3, max_length=120)


class AdminBonusRunsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(..., min_length=1, max_length=100)
    bonus_runs: int = Field(default=BONUS_RUNS_DEFAULT, ge=1, le=50)

    @field_validator("user_id")
    @classmethod
    def _clean_user_id(cls, value: str) -> str:
        return validate_client_identifier(value)


class CRMScriptResponse(BaseModel):
    success: bool
    deliverable_id: str
    deliverable: FullDeliverable
    markdown: str
    quota_status: Dict[str, Any]
    low_balance_warning: bool = False
    low_balance_message: Optional[str] = None
    clipfalcon_handoff: ClipFalconHandoffPayload


class CRMHistoryResponse(BaseModel):
    success: bool
    client_id: str
    items: List[Dict[str, Any]]


class ClipFalconHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deliverable_id: str = Field(..., min_length=1, max_length=100)


class ClipFalconHandoffResponse(BaseModel):
    success: bool
    target: str = "ClipFalcon"
    dispatched: bool = False
    handoff_payload: ClipFalconHandoffPayload


def _is_provider_connected() -> bool:
    if LLM_PROVIDER == "gemini":
        return bool(GEMINI_API_KEY)
    if LLM_PROVIDER == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    if LLM_PROVIDER in ("openai", "groq"):
        return bool(OPENAI_API_KEY)
    return False


@app.get("/", include_in_schema=False)
def serve_frontend():
    """Serve the ScriptFalcon dark SaaS HTML/CSS/JS studio."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    return FileResponse(str(index_path))


@app.get("/api/v1/health", tags=["System"])
def health_check():
    """Verify backend health and active LLM configuration."""
    return {
        "status": "healthy",
        "active_provider": LLM_PROVIDER,
        "provider_connected": _is_provider_connected(),
        "service": "ScriptFalcon — Tamil Reel Script Agent",
        "version": "2.0.0",
    }


@app.get("/api/v1/scripts/recent", tags=["Script Generation"])
def list_recent_scripts(limit: int = 5):
    """List recent standalone deliverables from the database, topped up with bundled samples."""
    limit = min(max(1, limit), 15)
    items: List[Dict[str, Any]] = []
    try:
        items = get_crm_db().list_standalone_deliverables(limit)
    except Exception:
        logger.exception("Failed to list standalone deliverables")
    if len(items) >= limit or not DELIVERABLES_DIR.exists():
        return {"items": items[:limit]}
    files = sorted(
        DELIVERABLES_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files[: limit - len(items)]:
        try:
            d = FullDeliverable.load_from_json(path)
            items.append(
                {
                    "stem": path.stem,
                    "topic": d.input_data.topic,
                    "platform": d.input_data.platform,
                    "duration": d.input_data.duration,
                    "tone": d.input_data.tone,
                    "word_count": d.script.word_count,
                }
            )
        except Exception:
            continue
    return {"items": items}


@app.get(
    "/api/v1/scripts/recent/{stem}",
    response_model=GenerateResponse,
    tags=["Script Generation"],
)
def get_recent_script(stem: str):
    """Load a saved deliverable by ID (database) or by bundled sample file stem."""
    safe_stem = Path(stem).name
    deliverable: Optional[FullDeliverable] = None
    try:
        deliverable = get_crm_db().get_standalone_deliverable(safe_stem)
    except Exception:
        logger.exception("Failed to load standalone deliverable '%s'", safe_stem)
    if deliverable is None:
        target = DELIVERABLES_DIR / f"{safe_stem}.json"
        if not target.exists():
            raise HTTPException(
                status_code=404, detail=f"Saved script '{safe_stem}' not found."
            )
        deliverable = FullDeliverable.load_from_json(target)
    return GenerateResponse(
        success=True,
        deliverable=deliverable,
        markdown=deliverable.to_markdown(),
    )


@app.post(
    "/api/v1/scripts/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Script Generation"],
)
def generate_full_script(payload: ScriptInput):
    """Generate a complete 6-section research-backed script deliverable."""
    try:
        payload.mode = "full_script"
        deliverable = pipeline.run(payload)
        _persist_standalone(deliverable)
        return GenerateResponse(
            success=True,
            deliverable=deliverable,
            markdown=deliverable.to_markdown(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline generation failed: {str(e)}",
        )


@app.post(
    "/api/v1/scripts/regenerate-hook",
    response_model=GenerateResponse,
    tags=["Regeneration"],
)
def regenerate_hook(payload: RegenerateHookRequest):
    """Regenerate 3 new hook options without re-searching or rewriting the body."""
    try:
        inp = payload.deliverable.input_data.model_copy(deep=True)
        inp.mode = "regenerate_hook"
        updated = pipeline.run(inp, previous_deliverable=payload.deliverable)
        _persist_standalone(updated)
        return GenerateResponse(
            success=True,
            deliverable=updated,
            markdown=updated.to_markdown(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hook regeneration failed: {str(e)}",
        )


@app.post(
    "/api/v1/scripts/regenerate-cta",
    response_model=GenerateResponse,
    tags=["Regeneration"],
)
def regenerate_cta(payload: RegenerateCtaRequest):
    """Regenerate 3 new CTA options matching the objective."""
    try:
        inp = payload.deliverable.input_data.model_copy(deep=True)
        if payload.new_objective:
            inp.objective = payload.new_objective
        inp.mode = "regenerate_cta"
        updated = pipeline.run(inp, previous_deliverable=payload.deliverable)
        _persist_standalone(updated)
        return GenerateResponse(
            success=True,
            deliverable=updated,
            markdown=updated.to_markdown(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CTA regeneration failed: {str(e)}",
        )


script_falcon_router = APIRouter(
    prefix="/api/v1/script-falcon",
    tags=["ScriptFalcon CRM"],
    dependencies=[Depends(require_employee_user)],
)


def _handle_crm_exception(exc: Exception) -> None:
    if isinstance(exc, (ClientNotFoundError, DeliverableNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, InsufficientQuotaError):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
        )
    if isinstance(exc, DailyLimitExceededError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        )
    if isinstance(exc, DuplicateRequestError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"ScriptFalcon CRM execution failed: {str(exc)}",
    )


@script_falcon_router.post(
    "/generate",
    response_model=CRMScriptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crm_generate_script(
    payload: CRMGenerateRequest,
    user: AuthenticatedUser = Depends(require_employee_user),
    db: CRMDatabase = Depends(get_crm_db),
):
    """Async Brand-DNA-injected generation with dual-tier quota & 30s dedup lock."""
    try:
        inp = ScriptInput.create_with_defaults(
            topic=payload.topic,
            audience=payload.audience,
            niche=payload.niche,
            platform=payload.platform,
            duration=payload.duration,
            tone=payload.tone,
            objective=payload.objective,
            mode="full_script",
            client_id=payload.client_id,
            reference_url=payload.reference_url,
        )
        deliverable = await pipeline.arun_for_crm(
            inp=inp,
            db=db,
            client_id=payload.client_id,
            user_id=user.user_id,
            is_admin=(user.role == "admin"),
        )
        quota_status = await asyncio.to_thread(
            db.get_quota_status, payload.client_id, user.user_id
        )
        return CRMScriptResponse(
            success=True,
            deliverable_id=deliverable.deliverable_id or "",
            deliverable=deliverable,
            markdown=deliverable.to_markdown(),
            quota_status=quota_status,
            low_balance_warning=bool(quota_status.get("low_balance_warning", False)),
            low_balance_message=quota_status.get("low_balance_message"),
            clipfalcon_handoff=deliverable.to_clipfalcon_handoff(),
        )
    except Exception as exc:
        _handle_crm_exception(exc)


@script_falcon_router.post("/regenerate-hook", response_model=CRMScriptResponse)
async def crm_regenerate_hook(
    payload: CRMRegenerateHookRequest,
    user: AuthenticatedUser = Depends(require_employee_user),
    db: CRMDatabase = Depends(get_crm_db),
):
    """Fast-path hook regeneration (~75% fewer tokens; 0-LLM Python audit)."""
    try:
        base_deliverable = await asyncio.to_thread(
            db.get_deliverable, payload.deliverable_id
        )
        if not base_deliverable:
            raise DeliverableNotFoundError(
                f"Deliverable '{payload.deliverable_id}' not found."
            )
        if (
            base_deliverable.client_id
            and base_deliverable.client_id != payload.client_id
        ):
            raise DeliverableNotFoundError(
                f"Deliverable '{payload.deliverable_id}' does not belong to client '{payload.client_id}'."
            )

        inp = base_deliverable.input_data.model_copy(deep=True)
        inp.mode = "regenerate_hook"
        updated = await pipeline.arun_for_crm(
            inp=inp,
            db=db,
            client_id=payload.client_id,
            user_id=user.user_id,
            previous_deliverable_id=payload.deliverable_id,
            previous_deliverable=base_deliverable,
            is_admin=(user.role == "admin"),
        )
        quota_status = await asyncio.to_thread(
            db.get_quota_status, payload.client_id, user.user_id
        )
        return CRMScriptResponse(
            success=True,
            deliverable_id=updated.deliverable_id or "",
            deliverable=updated,
            markdown=updated.to_markdown(),
            quota_status=quota_status,
            low_balance_warning=bool(quota_status.get("low_balance_warning", False)),
            low_balance_message=quota_status.get("low_balance_message"),
            clipfalcon_handoff=updated.to_clipfalcon_handoff(),
        )
    except Exception as exc:
        _handle_crm_exception(exc)


@script_falcon_router.post("/regenerate-cta", response_model=CRMScriptResponse)
async def crm_regenerate_cta(
    payload: CRMRegenerateCtaRequest,
    user: AuthenticatedUser = Depends(require_employee_user),
    db: CRMDatabase = Depends(get_crm_db),
):
    """Fast-path CTA regeneration (~75% fewer tokens; 0-LLM Python audit)."""
    try:
        base_deliverable = await asyncio.to_thread(
            db.get_deliverable, payload.deliverable_id
        )
        if not base_deliverable:
            raise DeliverableNotFoundError(
                f"Deliverable '{payload.deliverable_id}' not found."
            )
        if (
            base_deliverable.client_id
            and base_deliverable.client_id != payload.client_id
        ):
            raise DeliverableNotFoundError(
                f"Deliverable '{payload.deliverable_id}' does not belong to client '{payload.client_id}'."
            )

        inp = base_deliverable.input_data.model_copy(deep=True)
        if payload.new_objective:
            inp.objective = payload.new_objective
        inp.mode = "regenerate_cta"
        updated = await pipeline.arun_for_crm(
            inp=inp,
            db=db,
            client_id=payload.client_id,
            user_id=user.user_id,
            previous_deliverable_id=payload.deliverable_id,
            previous_deliverable=base_deliverable,
            is_admin=(user.role == "admin"),
        )
        quota_status = await asyncio.to_thread(
            db.get_quota_status, payload.client_id, user.user_id
        )
        return CRMScriptResponse(
            success=True,
            deliverable_id=updated.deliverable_id or "",
            deliverable=updated,
            markdown=updated.to_markdown(),
            quota_status=quota_status,
            low_balance_warning=bool(quota_status.get("low_balance_warning", False)),
            low_balance_message=quota_status.get("low_balance_message"),
            clipfalcon_handoff=updated.to_clipfalcon_handoff(),
        )
    except Exception as exc:
        _handle_crm_exception(exc)


@script_falcon_router.get("/history/{client_id}", response_model=CRMHistoryResponse)
async def crm_client_history(
    client_id: str,
    limit: int = 20,
    db: CRMDatabase = Depends(get_crm_db),
):
    """Retrieve persisted ScriptFalcon script history for a CRM client."""
    brand_dna = await asyncio.to_thread(db.get_client_brand_dna, client_id)
    if not brand_dna:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    items = await asyncio.to_thread(
        db.get_client_history, client_id, min(max(1, limit), 100)
    )
    return CRMHistoryResponse(success=True, client_id=client_id, items=items)


@script_falcon_router.post("/admin/grant-bonus-runs")
async def crm_admin_grant_bonus_runs(
    payload: AdminBonusRunsRequest,
    user: AuthenticatedUser = Depends(require_employee_user),
    db: CRMDatabase = Depends(get_crm_db),
):
    """Admin override: grant +N (default +10) bonus daily runs for urgent campaigns."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to grant bonus teammate runs.",
        )
    updated_usage = await asyncio.to_thread(
        db.grant_bonus_runs, payload.user_id, payload.bonus_runs
    )
    return {"success": True, "granted_by": user.user_id, "daily_usage": updated_usage}


@script_falcon_router.post(
    "/send-to-clipfalcon", response_model=ClipFalconHandoffResponse
)
async def send_to_clipfalcon(
    payload: ClipFalconHandoffRequest,
    db: CRMDatabase = Depends(get_crm_db),
):
    """Build and asynchronously dispatch the ClipFalcon video-vs-script audit payload."""
    deliverable = await asyncio.to_thread(db.get_deliverable, payload.deliverable_id)
    if not deliverable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deliverable '{payload.deliverable_id}' not found.",
        )

    handoff = deliverable.to_clipfalcon_handoff()
    dispatched = False
    if CLIPFALCON_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    CLIPFALCON_WEBHOOK_URL, json=handoff.model_dump()
                )
                dispatched = 200 <= resp.status_code < 300
        except Exception as exc:
            logger.warning(f"ClipFalcon webhook dispatch failed: {exc}")

    return ClipFalconHandoffResponse(
        success=True,
        target="ClipFalcon",
        dispatched=dispatched,
        handoff_payload=handoff,
    )


@app.post(
    "/api/v2/scripts/generate",
    status_code=status.HTTP_201_CREATED,
    tags=["Script Generation v2 (Strict DTO)"],
)
async def generate_script_strict_v2(
    payload: GenerateScriptRequest,
    authorization: Optional[str] = Header(default=None),
    db: CRMDatabase = Depends(get_crm_db),
):
    """Strict DTO endpoint enforcing sanitization, SSRF guard, JWT user_id binding, and dual quotas."""
    inp = payload.to_script_input()
    if payload.mode == "crm":
        # Always verify authenticated employee/admin JWT and ignore any client-supplied user_id headers.
        user = require_employee_user(authorization=authorization)
        try:
            deliverable = await pipeline.arun_for_crm(
                inp=inp,
                db=db,
                client_id=payload.client_id or "",
                user_id=user.user_id,
                is_admin=(user.role == "admin"),
            )
            quota_status = await asyncio.to_thread(
                db.get_quota_status, payload.client_id or "", user.user_id
            )
            return CRMScriptResponse(
                success=True,
                deliverable_id=deliverable.deliverable_id or "",
                deliverable=deliverable,
                markdown=deliverable.to_markdown(),
                quota_status=quota_status,
                low_balance_warning=bool(
                    quota_status.get("low_balance_warning", False)
                ),
                low_balance_message=quota_status.get("low_balance_message"),
                clipfalcon_handoff=deliverable.to_clipfalcon_handoff(),
            )
        except Exception as exc:
            _handle_crm_exception(exc)

    try:
        deliverable = await pipeline.arun(inp)
        await asyncio.to_thread(_persist_standalone, deliverable)
        return GenerateResponse(
            success=True,
            deliverable=deliverable,
            markdown=deliverable.to_markdown(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline generation failed: {str(exc)}",
        )


@app.post(
    "/api/v2/scripts/regenerate",
    tags=["Script Generation v2 (Strict DTO)"],
)
async def regenerate_section_strict_v2(
    payload: RegenerateSectionRequest,
    authorization: Optional[str] = Header(default=None),
    db: CRMDatabase = Depends(get_crm_db),
):
    """Strict DTO section regeneration for hook or CTA in standalone or CRM mode."""
    target_mode = "regenerate_hook" if payload.section == "hook" else "regenerate_cta"
    if payload.mode == "crm":
        user = require_employee_user(authorization=authorization)
        try:
            base_deliverable = await asyncio.to_thread(
                db.get_deliverable, payload.deliverable_id or ""
            )
            if not base_deliverable:
                raise DeliverableNotFoundError(
                    f"Deliverable '{payload.deliverable_id}' not found."
                )
            if (
                base_deliverable.client_id
                and base_deliverable.client_id != payload.client_id
            ):
                raise DeliverableNotFoundError(
                    f"Deliverable '{payload.deliverable_id}' does not belong to client '{payload.client_id}'."
                )
            inp = base_deliverable.input_data.model_copy(deep=True)
            if payload.section == "cta" and payload.conversion_objective:
                inp.objective = payload.conversion_objective
            inp.mode = target_mode
            updated = await pipeline.arun_for_crm(
                inp=inp,
                db=db,
                client_id=payload.client_id or "",
                user_id=user.user_id,
                previous_deliverable_id=payload.deliverable_id,
                previous_deliverable=base_deliverable,
                is_admin=(user.role == "admin"),
            )
            quota_status = await asyncio.to_thread(
                db.get_quota_status, payload.client_id or "", user.user_id
            )
            return CRMScriptResponse(
                success=True,
                deliverable_id=updated.deliverable_id or "",
                deliverable=updated,
                markdown=updated.to_markdown(),
                quota_status=quota_status,
                low_balance_warning=bool(
                    quota_status.get("low_balance_warning", False)
                ),
                low_balance_message=quota_status.get("low_balance_message"),
                clipfalcon_handoff=updated.to_clipfalcon_handoff(),
            )
        except Exception as exc:
            _handle_crm_exception(exc)

    base = payload.deliverable
    if base is None and payload.deliverable_id:
        base = await asyncio.to_thread(
            db.get_standalone_deliverable, payload.deliverable_id
        )
        if not base:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deliverable not found."
            )
    inp = base.input_data.model_copy(deep=True)
    if payload.section == "cta" and payload.conversion_objective:
        inp.objective = payload.conversion_objective
    inp.mode = target_mode
    updated = await pipeline.arun(inp, previous_deliverable=base)
    await asyncio.to_thread(_persist_standalone, updated)
    return GenerateResponse(
        success=True, deliverable=updated, markdown=updated.to_markdown()
    )


app.include_router(script_falcon_router)
