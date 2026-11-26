"""Unified LLM client interface supporting Gemini, Anthropic, OpenAI/Groq, and simulation."""

import json
import logging
import os
import re
import threading
import time
from contextvars import ContextVar
from typing import Any, Dict, Optional

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_THINKING_LEVEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    MAX_OUTPUT_TOKENS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    calculate_cost_inr,
)

logger = logging.getLogger(__name__)


def clean_json_response(raw_text: str) -> Dict[str, Any]:
    """Clean markdown code fences and parse JSON safely."""
    text = raw_text.strip()

    # 1. Direct parse attempt
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract content within ```json ... ``` or ``` ... ``` code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        fence_content = fence_match.group(1).strip()
        try:
            return json.loads(fence_content)
        except json.JSONDecodeError:
            text = fence_content  # Fall through to brace extraction on fence content

    # 3. Robust substring extraction: outermost { to outermost }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    # 4. Fallback for array root if applicable
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(text[first_bracket : last_bracket + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to parse LLM response as JSON. Output was:\n{raw_text}")


def _estimate_tokens(text: str) -> int:
    """Estimate token count conservatively (~4 chars/token; higher density for Tamil Unicode)."""
    if not text:
        return 0
    tamil_chars = sum(1 for ch in text if "\u0b80" <= ch <= "\u0bff")
    other_chars = len(text) - tamil_chars
    return max(1, (tamil_chars // 2) + (other_chars // 4))


# Wall-clock budget for one script request. Cloudflare drops requests after ~100s and
# the PHP gateway after 120s, so a request must finish well inside that.
# A ContextVar (not thread-local) so asyncio.to_thread workers see the request's deadline.
_REQUEST_DEADLINE: ContextVar[Optional[float]] = ContextVar(
    "scriptfalcon_request_deadline", default=None
)
GEMINI_ATTEMPT_TIMEOUT_S = float(os.getenv("GEMINI_ATTEMPT_TIMEOUT_S", "30"))
_MIN_ATTEMPT_S = 5.0  # not worth starting a Gemini call with less time than this
_BUSY_RETRY_PAUSE_S = 1.5
# Backups after the configured model. Keep this list to models that exist for new keys.
_GEMINI_BACKUP_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
)


def start_request_budget(seconds: float):
    """Start a deadline for every LLM call made in this request; returns a reset token."""
    return _REQUEST_DEADLINE.set(time.monotonic() + seconds)


def end_request_budget(token) -> None:
    _REQUEST_DEADLINE.reset(token)


def _seconds_left() -> Optional[float]:
    deadline = _REQUEST_DEADLINE.get()
    return None if deadline is None else deadline - time.monotonic()


class LLMClient:
    """Unified LLM caller that routes to Gemini, Anthropic, OpenAI/Groq, or simulation."""

    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or LLM_PROVIDER).lower()
        self.gemini_client = None
        self.anthropic_client = None
        self.openai_client = None
        self._usage_local = threading.local()

        # 1. Google Gemini
        if GEMINI_API_KEY and self.provider in ("gemini", "auto"):
            try:
                from google import genai

                self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
                self.provider = "gemini"
            except ImportError:
                try:
                    import google.generativeai as genai

                    genai.configure(api_key=GEMINI_API_KEY)
                    self.gemini_client = genai.GenerativeModel(
                        GEMINI_MODEL or "gemini-3.5-flash-lite"
                    )
                    self.provider = "gemini"
                except Exception as e:
                    logger.warning(f"Could not initialize Gemini: {e}")
            except Exception as e:
                logger.warning(f"Could not initialize google-genai Client: {e}")

        # 2. Anthropic Claude
        if (
            not self.gemini_client
            and ANTHROPIC_API_KEY
            and self.provider in ("anthropic", "auto")
        ):
            try:
                import anthropic

                self.anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                self.provider = "anthropic"
            except Exception as e:
                logger.warning(f"Could not initialize Anthropic: {e}")

        # 3. OpenAI / Groq Compatible
        if (
            not self.gemini_client
            and not self.anthropic_client
            and OPENAI_API_KEY
            and self.provider in ("openai", "groq", "auto")
        ):
            try:
                import openai

                base_url = os.getenv("OPENAI_BASE_URL", None)
                self.openai_client = openai.OpenAI(
                    api_key=OPENAI_API_KEY, base_url=base_url
                )
                self.provider = "openai"
            except Exception as e:
                logger.warning(f"Could not initialize OpenAI/Groq: {e}")

        if not any([self.gemini_client, self.anthropic_client, self.openai_client]):
            if self.provider != "simulation":
                logger.info(
                    "No active API keys found; activating smart simulation generator."
                )
            self.provider = "simulation"

    @property
    def last_usage(self) -> Dict[str, Any]:
        """Usage of the most recent call made *on the current thread*.

        Thread-local so concurrent API requests sharing one client never read each other's
        token counts (which would mis-bill CRM quotas).
        """
        return getattr(self._usage_local, "value", {})

    @last_usage.setter
    def last_usage(self, value: Dict[str, Any]) -> None:
        self._usage_local.value = value

    def _record_usage(
        self,
        model_used: str,
        input_tokens: int,
        output_tokens: int,
        finish_reason: str = "STOP",
    ) -> Dict[str, Any]:
        """Store and return normalized usage and cost metadata."""
        # SDK enums stringify as "FinishReason.MAX_TOKENS"; normalise to the bare member name.
        finish_reason = (
            getattr(finish_reason, "name", None)
            or str(finish_reason).rsplit(".", 1)[-1]
        )
        # A FALLBACK means the real LLM failed and canned template text was used: it costs
        # nothing and must not count toward a user's daily token limit either.
        if finish_reason.upper() == "FALLBACK":
            input_tokens = output_tokens = 0
        total_tokens = max(0, input_tokens) + max(0, output_tokens)
        cost_inr = (
            calculate_cost_inr(model_used, input_tokens, output_tokens)
            if total_tokens
            else 0.0
        )
        is_truncated = finish_reason.upper() in ("MAX_TOKENS", "LENGTH", "MAX_TOKEN")
        if is_truncated:
            logger.warning(
                f"LLM response truncated ({finish_reason}) on model {model_used}."
            )
        usage = {
            "model_used": model_used,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_inr": cost_inr,
            "finish_reason": str(finish_reason),
            "is_truncated": is_truncated,
        }
        self.last_usage = usage
        return usage

    def generate_json_with_meta(
        self,
        system_prompt: str,
        user_prompt: str,
        default_fallback: Optional[Dict[str, Any]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Invoke LLM and return parsed JSON along with token/cost/truncation metadata."""
        tokens_limit = max_output_tokens or MAX_OUTPUT_TOKENS
        temp = LLM_TEMPERATURE if temperature is None else temperature

        if self.provider == "gemini" and self.gemini_client:
            combined_prompt = f"{system_prompt}\n\nUSER REQUEST:\n{user_prompt}\n\nOutput strictly valid JSON only."
            primary = GEMINI_MODEL or _GEMINI_BACKUP_MODELS[0]
            seen_models = {primary}
            backups = [
                m
                for m in _GEMINI_BACKUP_MODELS
                if not (m in seen_models or seen_models.add(m))
            ]
            # The primary gets one quick retry: its busy spells (503) are usually seconds long.
            models_to_try = [primary, primary, *backups]

            last_error = None
            for attempt, model_name in enumerate(models_to_try):
                left = _seconds_left()
                if left is not None and left < _MIN_ATTEMPT_S:
                    logger.warning(
                        "Request time budget used up; skipping remaining Gemini attempts."
                    )
                    break
                if attempt == 1:
                    time.sleep(_BUSY_RETRY_PAUSE_S)
                timeout_s = GEMINI_ATTEMPT_TIMEOUT_S
                if left is not None:
                    timeout_s = max(_MIN_ATTEMPT_S, min(timeout_s, left - 1.0))
                try:
                    if hasattr(self.gemini_client, "models"):  # google-genai SDK
                        from google.genai import types

                        thinking_cfg = None
                        if GEMINI_THINKING_LEVEL and hasattr(types, "ThinkingConfig"):
                            try:
                                thinking_cfg = types.ThinkingConfig(
                                    thinking_level=GEMINI_THINKING_LEVEL
                                )
                            except Exception:
                                thinking_cfg = None
                        http_opts = types.HttpOptions(timeout=int(timeout_s * 1000))
                        gen_config = types.GenerateContentConfig(
                            temperature=temp,
                            max_output_tokens=tokens_limit,
                            thinking_config=thinking_cfg,
                            http_options=http_opts,
                        )
                        try:
                            response = self.gemini_client.models.generate_content(
                                model=model_name,
                                contents=combined_prompt,
                                config=gen_config,
                            )
                        except Exception as cfg_err:
                            # Fallback without thinking_config if model rejects thinking_level
                            if (
                                thinking_cfg is not None
                                and "thinking" in str(cfg_err).lower()
                            ):
                                response = self.gemini_client.models.generate_content(
                                    model=model_name,
                                    contents=combined_prompt,
                                    config=types.GenerateContentConfig(
                                        temperature=temp,
                                        max_output_tokens=tokens_limit,
                                        http_options=http_opts,
                                    ),
                                )
                            else:
                                raise
                        usage_meta = getattr(response, "usage_metadata", None)
                        in_tok = getattr(
                            usage_meta, "prompt_token_count", None
                        ) or _estimate_tokens(combined_prompt)
                        out_tok = getattr(
                            usage_meta, "candidates_token_count", None
                        ) or _estimate_tokens(response.text or "")
                        candidates = getattr(response, "candidates", None) or []
                        finish_reason = (
                            getattr(candidates[0], "finish_reason", "STOP")
                            if candidates
                            else "STOP"
                        )
                        data = clean_json_response(response.text)
                        meta = self._record_usage(
                            model_name, int(in_tok), int(out_tok), str(finish_reason)
                        )
                        return {"data": data, **meta}
                    else:  # google.generativeai legacy SDK
                        response = self.gemini_client.generate_content(
                            combined_prompt,
                            generation_config={
                                "temperature": temp,
                                "max_output_tokens": tokens_limit,
                            },
                        )
                        in_tok = _estimate_tokens(combined_prompt)
                        out_tok = _estimate_tokens(response.text or "")
                        data = clean_json_response(response.text)
                        meta = self._record_usage(model_name, in_tok, out_tok, "STOP")
                        return {"data": data, **meta}
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        logger.warning(
                            f"Model {model_name} temporarily busy (503). Retrying / trying alternative model..."
                        )
                    elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        logger.warning(
                            f"Model {model_name} rate limited (429). Trying alternative model..."
                        )
                    else:
                        logger.warning(
                            f"Model {model_name} failed ({type(e).__name__}: {err_str[:300]}). Trying alternative model..."
                        )
                    continue

            if last_error:
                logger.error(
                    f"All Gemini models failed; {'using template fallback (not billed)' if default_fallback is not None else 'raising'}. "
                    f"Last error: {last_error}"
                )
            if default_fallback is not None:
                in_tok = _estimate_tokens(combined_prompt)
                out_tok = _estimate_tokens(
                    json.dumps(default_fallback, ensure_ascii=False)
                )
                meta = self._record_usage("simulation", in_tok, out_tok, "FALLBACK")
                return {"data": default_fallback, **meta}
            if last_error:
                raise last_error

        elif self.provider == "anthropic" and self.anthropic_client:
            try:
                response = self.anthropic_client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=tokens_limit,
                    temperature=temp,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                usage = getattr(response, "usage", None)
                in_tok = getattr(usage, "input_tokens", None) or _estimate_tokens(
                    system_prompt + user_prompt
                )
                out_tok = getattr(usage, "output_tokens", None) or _estimate_tokens(
                    response.content[0].text
                )
                finish_reason = getattr(response, "stop_reason", "end_turn")
                data = clean_json_response(response.content[0].text)
                meta = self._record_usage(
                    ANTHROPIC_MODEL, int(in_tok), int(out_tok), str(finish_reason)
                )
                return {"data": data, **meta}
            except Exception as e:
                logger.error(f"Anthropic API call failed: {e}")
                if default_fallback is not None:
                    in_tok = _estimate_tokens(system_prompt + user_prompt)
                    out_tok = _estimate_tokens(
                        json.dumps(default_fallback, ensure_ascii=False)
                    )
                    meta = self._record_usage("simulation", in_tok, out_tok, "FALLBACK")
                    return {"data": default_fallback, **meta}
                raise

        elif self.provider in ("openai", "groq") and self.openai_client:
            try:
                response = self.openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    temperature=temp,
                    max_tokens=tokens_limit,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                usage = getattr(response, "usage", None)
                in_tok = getattr(usage, "prompt_tokens", None) or _estimate_tokens(
                    system_prompt + user_prompt
                )
                out_tok = getattr(usage, "completion_tokens", None) or _estimate_tokens(
                    response.choices[0].message.content or ""
                )
                finish_reason = getattr(response.choices[0], "finish_reason", "stop")
                data = clean_json_response(response.choices[0].message.content)
                meta = self._record_usage(
                    OPENAI_MODEL, int(in_tok), int(out_tok), str(finish_reason)
                )
                return {"data": data, **meta}
            except Exception as e:
                logger.error(f"OpenAI/Groq API call failed: {e}")
                if default_fallback is not None:
                    in_tok = _estimate_tokens(system_prompt + user_prompt)
                    out_tok = _estimate_tokens(
                        json.dumps(default_fallback, ensure_ascii=False)
                    )
                    meta = self._record_usage("simulation", in_tok, out_tok, "FALLBACK")
                    return {"data": default_fallback, **meta}
                raise

        elif self.provider == "simulation":
            if default_fallback is not None:
                in_tok = _estimate_tokens(system_prompt + user_prompt)
                out_tok = _estimate_tokens(
                    json.dumps(default_fallback, ensure_ascii=False)
                )
                meta = self._record_usage("simulation", in_tok, out_tok, "SIMULATION")
                return {"data": default_fallback, **meta}
            raise RuntimeError(
                "Simulation provider requested but no fallback handler was provided."
            )

        raise RuntimeError(f"Unsupported or unconfigured LLM provider: {self.provider}")

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        default_fallback: Optional[Dict[str, Any]] = None,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Invoke LLM and return parsed JSON object (records metadata on self.last_usage)."""
        result = self.generate_json_with_meta(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            default_fallback=default_fallback,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        return result["data"]
