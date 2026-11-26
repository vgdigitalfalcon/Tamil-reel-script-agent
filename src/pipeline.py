"""Master Pipeline orchestrating sync/async 3-step ScriptFalcon execution & CRM quotas."""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from src.agents.quality_agent import QualityAgent
from src.agents.research_agent import ResearchAgent
from src.agents.script_agent import ScriptAgent
from src.config import FULL_SCRIPT_BUDGET_INR, REGENERATION_BUDGET_INR
from src.db import (
    ClientNotFoundError,
    CRMDatabase,
    DeliverableNotFoundError,
    build_dedup_key,
)
from src.llm import LLMClient, end_request_budget, start_request_budget
from src.models import FullDeliverable, ScriptInput

logger = logging.getLogger(__name__)

# Whole-request LLM time budget; keeps a run inside Cloudflare's ~100s and the gateway's 120s.
PIPELINE_TIME_BUDGET_S = float(os.getenv("PIPELINE_TIME_BUDGET_S", "85"))

AI_BUSY_WARNING = (
    "Gemini was busy, so part of this script uses a basic template instead of AI writing. "
    "Wait a minute and click Generate again for a full script."
)


def _fallback_warning(usages: List[Dict[str, Any]]) -> str:
    """Warn when any step fell back to template text because the LLM did not answer."""
    used_fallback = any(
        str((u or {}).get("finish_reason", "")).upper() == "FALLBACK" for u in usages
    )
    return AI_BUSY_WARNING if used_fallback else ""


def _aggregate_usage(usages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum token counts and INR cost across executed pipeline agent steps."""
    input_tokens = sum(int(u.get("input_tokens", 0) or 0) for u in usages)
    output_tokens = sum(int(u.get("output_tokens", 0) or 0) for u in usages)
    total_tokens = sum(int(u.get("total_tokens", 0) or 0) for u in usages)
    cost_inr = round(sum(float(u.get("cost_inr", 0.0) or 0.0) for u in usages), 4)
    models = [u.get("model_used") for u in usages if u.get("model_used")]
    model_used = models[-1] if models else ""
    return {
        "model_used": model_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens_used": total_tokens,
        "cost_inr": cost_inr,
    }


class TamilReelScriptPipeline:
    """Orchestrates Research -> Scriptwriting -> 7-Criteria Audit & 0-LLM Fast-Path Regen."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    # Agents keep per-run state (last_usage), so each run gets its own instances.
    # The API shares one pipeline across concurrent requests; shared agents would mix up costs.
    @property
    def research_agent(self) -> ResearchAgent:
        return ResearchAgent(self.llm)

    @property
    def script_agent(self) -> ScriptAgent:
        return ScriptAgent(self.llm)

    @property
    def quality_agent(self) -> QualityAgent:
        return QualityAgent(self.llm)

    def run(
        self, inp: ScriptInput, previous_deliverable: Optional[FullDeliverable] = None
    ) -> FullDeliverable:
        """Synchronously execute generation pipeline based on mode, inside the time budget."""
        token = start_request_budget(PIPELINE_TIME_BUDGET_S)
        try:
            return self._run_mode(inp, previous_deliverable)
        finally:
            end_request_budget(token)

    def _run_mode(
        self, inp: ScriptInput, previous_deliverable: Optional[FullDeliverable] = None
    ) -> FullDeliverable:
        logger.info(f"Running pipeline for topic: '{inp.topic}' | Mode: '{inp.mode}'")

        if inp.mode == "regenerate_hook":
            if not previous_deliverable:
                inp.mode = "full_script"
                base = self._run_full(inp)
                inp.mode = "regenerate_hook"
                return self._regenerate_hook(inp, base)
            return self._regenerate_hook(inp, previous_deliverable)

        elif inp.mode == "regenerate_cta":
            if not previous_deliverable:
                inp.mode = "full_script"
                base = self._run_full(inp)
                inp.mode = "regenerate_cta"
                return self._regenerate_cta(inp, base)
            return self._regenerate_cta(inp, previous_deliverable)

        else:
            return self._run_full(inp)

    async def arun(
        self, inp: ScriptInput, previous_deliverable: Optional[FullDeliverable] = None
    ) -> FullDeliverable:
        """Non-blocking async pipeline execution, inside the time budget."""
        token = start_request_budget(PIPELINE_TIME_BUDGET_S)
        try:
            return await self._arun_mode(inp, previous_deliverable)
        finally:
            end_request_budget(token)

    async def _arun_mode(
        self, inp: ScriptInput, previous_deliverable: Optional[FullDeliverable] = None
    ) -> FullDeliverable:
        logger.info(f"Async pipeline for topic: '{inp.topic}' | Mode: '{inp.mode}'")

        if inp.mode == "regenerate_hook":
            if not previous_deliverable:
                inp.mode = "full_script"
                base = await self._arun_full(inp)
                inp.mode = "regenerate_hook"
                return await asyncio.to_thread(self._regenerate_hook, inp, base)
            return await asyncio.to_thread(
                self._regenerate_hook, inp, previous_deliverable
            )

        elif inp.mode == "regenerate_cta":
            if not previous_deliverable:
                inp.mode = "full_script"
                base = await self._arun_full(inp)
                inp.mode = "regenerate_cta"
                return await asyncio.to_thread(self._regenerate_cta, inp, base)
            return await asyncio.to_thread(
                self._regenerate_cta, inp, previous_deliverable
            )

        else:
            return await self._arun_full(inp)

    def _prepare_crm_inputs(
        self,
        inp: ScriptInput,
        db: CRMDatabase,
        client_id: str,
        previous_deliverable_id: Optional[str],
        previous_deliverable: Optional[FullDeliverable],
    ):
        """Inject Client Brand DNA and load saved state for fast-path regeneration."""
        brand_dna = db.get_client_brand_dna(client_id)
        if not brand_dna:
            raise ClientNotFoundError(
                f"Client '{client_id}' not found in CRM database."
            )

        enriched_inp = inp.model_copy(deep=True)
        enriched_inp.client_id = client_id
        enriched_inp.brand_dna = brand_dna
        if (
            not enriched_inp.audience
            or enriched_inp.audience == "General Tamil content audience"
        ) and brand_dna.target_audience:
            enriched_inp.audience = brand_dna.target_audience
        if (
            not enriched_inp.niche
            or enriched_inp.niche == "Business / Digital / Career"
        ) and brand_dna.industry:
            enriched_inp.niche = brand_dna.industry

        if (
            enriched_inp.mode in ("regenerate_hook", "regenerate_cta")
            and previous_deliverable is None
        ):
            if not previous_deliverable_id:
                raise DeliverableNotFoundError(
                    "deliverable_id is required for CRM hook/CTA regeneration."
                )
            previous_deliverable = db.get_deliverable(previous_deliverable_id)
            if not previous_deliverable:
                raise DeliverableNotFoundError(
                    f"Deliverable '{previous_deliverable_id}' not found."
                )

        return enriched_inp, previous_deliverable

    def run_for_crm(
        self,
        inp: ScriptInput,
        db: CRMDatabase,
        client_id: str,
        user_id: str,
        previous_deliverable_id: Optional[str] = None,
        previous_deliverable: Optional[FullDeliverable] = None,
        is_admin: bool = False,
        enable_dedup: bool = True,
    ) -> FullDeliverable:
        """Synchronously execute pipeline with Brand DNA, dual quotas, dedup lock, and persistence."""
        enriched_inp, prev_del = self._prepare_crm_inputs(
            inp, db, client_id, previous_deliverable_id, previous_deliverable
        )

        budget_inr = (
            REGENERATION_BUDGET_INR
            if enriched_inp.mode in ("regenerate_hook", "regenerate_cta")
            else FULL_SCRIPT_BUDGET_INR
        )
        dedup_key = (
            build_dedup_key(
                client_id,
                user_id,
                enriched_inp.topic,
                enriched_inp.duration,
                enriched_inp.mode,
            )
            if enable_dedup
            else None
        )
        reservation_id = db.reserve_quota(
            client_id=client_id,
            user_id=user_id,
            operation=enriched_inp.mode,
            amount_inr=budget_inr,
            dedup_key=dedup_key,
            is_admin=is_admin,
        )

        try:
            deliverable = self.run(enriched_inp, previous_deliverable=prev_del)
            deliverable.client_id = client_id
            deliverable.user_id = user_id
            deliverable.deliverable_id = None

            db.settle_quota(
                reservation_id=reservation_id,
                actual_cost_inr=deliverable.cost_inr,
                input_tokens=deliverable.input_tokens,
                output_tokens=deliverable.output_tokens,
                tokens_used=deliverable.tokens_used,
                deliverable_id=None,
            )
            deliverable_id = db.save_deliverable(
                deliverable=deliverable,
                client_id=client_id,
                user_id=user_id,
                parent_deliverable_id=previous_deliverable_id,
            )
            db.link_run_deliverable(
                reservation_id=reservation_id, deliverable_id=deliverable_id
            )
            return deliverable
        except Exception:
            db.refund_quota(reservation_id)
            raise

    async def arun_for_crm(
        self,
        inp: ScriptInput,
        db: CRMDatabase,
        client_id: str,
        user_id: str,
        previous_deliverable_id: Optional[str] = None,
        previous_deliverable: Optional[FullDeliverable] = None,
        is_admin: bool = False,
        enable_dedup: bool = True,
    ) -> FullDeliverable:
        """Non-blocking async CRM execution for FastAPI routes."""
        enriched_inp, prev_del = await asyncio.to_thread(
            self._prepare_crm_inputs,
            inp,
            db,
            client_id,
            previous_deliverable_id,
            previous_deliverable,
        )

        budget_inr = (
            REGENERATION_BUDGET_INR
            if enriched_inp.mode in ("regenerate_hook", "regenerate_cta")
            else FULL_SCRIPT_BUDGET_INR
        )
        dedup_key = (
            build_dedup_key(
                client_id,
                user_id,
                enriched_inp.topic,
                enriched_inp.duration,
                enriched_inp.mode,
            )
            if enable_dedup
            else None
        )
        reservation_id = await asyncio.to_thread(
            db.reserve_quota,
            client_id=client_id,
            user_id=user_id,
            operation=enriched_inp.mode,
            amount_inr=budget_inr,
            dedup_key=dedup_key,
            is_admin=is_admin,
        )

        try:
            deliverable = await self.arun(enriched_inp, previous_deliverable=prev_del)
            deliverable.client_id = client_id
            deliverable.user_id = user_id
            deliverable.deliverable_id = None

            await asyncio.to_thread(
                db.settle_quota,
                reservation_id=reservation_id,
                actual_cost_inr=deliverable.cost_inr,
                input_tokens=deliverable.input_tokens,
                output_tokens=deliverable.output_tokens,
                tokens_used=deliverable.tokens_used,
            )
            deliverable_id = await asyncio.to_thread(
                db.save_deliverable,
                deliverable=deliverable,
                client_id=client_id,
                user_id=user_id,
                parent_deliverable_id=previous_deliverable_id,
            )
            await asyncio.to_thread(
                db.link_run_deliverable,
                reservation_id=reservation_id,
                deliverable_id=deliverable_id,
            )
            return deliverable
        except Exception:
            await asyncio.to_thread(db.refund_quota, reservation_id)
            raise

    def _run_full(self, inp: ScriptInput) -> FullDeliverable:
        """Standard 3-Step Execution: Research -> Script -> 7-Criteria LLM Quality Audit."""
        research_agent, script_agent, quality_agent = (
            self.research_agent,
            self.script_agent,
            self.quality_agent,
        )
        logger.info("[Step 1/3] Executing Research Agent...")
        research = research_agent.execute(inp)

        logger.info(
            "[Step 2/3] Executing Script Agent for hooks and humanized script..."
        )
        draft = script_agent.execute(inp, research)

        logger.info("[Step 3/3] Executing 7-Criteria Quality Compliance Agent...")
        qc, certified_script = quality_agent.execute(inp, research, draft)

        usages = [
            research_agent.last_usage,
            script_agent.last_usage,
            quality_agent.last_usage,
        ]
        usage_summary = _aggregate_usage(usages)

        return FullDeliverable(
            input_data=inp,
            research=research,
            script=certified_script,
            quality_check=qc,
            client_id=inp.client_id,
            generation_warning=_fallback_warning(usages),
            **usage_summary,
        )

    async def _arun_full(self, inp: ScriptInput) -> FullDeliverable:
        """Non-blocking async 3-Step Execution."""
        research_agent, script_agent, quality_agent = (
            self.research_agent,
            self.script_agent,
            self.quality_agent,
        )
        research = await research_agent.aexecute(inp)
        draft = await asyncio.to_thread(script_agent.execute, inp, research)
        qc, certified_script = await asyncio.to_thread(
            quality_agent.execute, inp, research, draft
        )

        usages = [
            research_agent.last_usage,
            script_agent.last_usage,
            quality_agent.last_usage,
        ]
        usage_summary = _aggregate_usage(usages)

        return FullDeliverable(
            input_data=inp,
            research=research,
            script=certified_script,
            quality_check=qc,
            client_id=inp.client_id,
            generation_warning=_fallback_warning(usages),
            **usage_summary,
        )

    def _regenerate_hook(
        self, inp: ScriptInput, base: FullDeliverable
    ) -> FullDeliverable:
        """Fast-path hook regeneration: skips Step 1 search & Step 3 LLM audit (~75% token reduction)."""
        logger.info(
            "Executing fast-path regeneration for HOOKS (0-LLM Python audit)..."
        )
        script_agent = self.script_agent
        updated_draft = script_agent.regenerate_hooks(inp, base.script)
        qc, certified_script = self.quality_agent.audit_fast_path(
            inp, updated_draft, mode="regenerate_hook"
        )

        usages = [script_agent.last_usage]
        usage_summary = _aggregate_usage(usages)

        return FullDeliverable(
            input_data=inp,
            research=base.research,
            script=certified_script,
            quality_check=qc,
            client_id=inp.client_id or base.client_id,
            generation_warning=_fallback_warning(usages),
            **usage_summary,
        )

    def _regenerate_cta(
        self, inp: ScriptInput, base: FullDeliverable
    ) -> FullDeliverable:
        """Fast-path CTA regeneration: skips Step 1 search & Step 3 LLM audit (~75% token reduction)."""
        logger.info("Executing fast-path regeneration for CTA (0-LLM Python audit)...")
        script_agent = self.script_agent
        updated_draft = script_agent.regenerate_cta(inp, base.script)
        qc, certified_script = self.quality_agent.audit_fast_path(
            inp, updated_draft, mode="regenerate_cta"
        )

        usages = [script_agent.last_usage]
        usage_summary = _aggregate_usage(usages)

        return FullDeliverable(
            input_data=inp,
            research=base.research,
            script=certified_script,
            quality_check=qc,
            client_id=inp.client_id or base.client_id,
            generation_warning=_fallback_warning(usages),
            **usage_summary,
        )
