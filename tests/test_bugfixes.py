"""Regression tests for bugs found during the live end-to-end review."""

import threading
from unittest.mock import patch

from src.agents.quality_agent import (
    find_foreign_indic_words,
    normalize_modulation_cues,
    strip_foreign_indic_words,
)
from src.llm import LLMClient
from src.search_tool import _is_public_url, fetch_reference_url


def test_gemini_enum_finish_reason_detected_as_truncated():
    llm = LLMClient(provider="simulation")
    meta = llm._record_usage("gemini-3.5-flash-lite", 10, 10, "FinishReason.MAX_TOKENS")
    assert meta["is_truncated"] is True
    assert meta["finish_reason"] == "MAX_TOKENS"
    assert llm._record_usage("x", 1, 1, "FinishReason.STOP")["is_truncated"] is False
    assert llm._record_usage("x", 1, 1, "length")["is_truncated"] is True


def test_last_usage_is_isolated_per_thread():
    llm = LLMClient(provider="simulation")
    results = {}
    barrier = threading.Barrier(2)

    def worker(name, fallback):
        barrier.wait()
        llm.generate_json(
            "sys", "user " * (50 if name == "a" else 500), default_fallback=fallback
        )
        barrier.wait()  # both calls finished before either reads
        results[name] = llm.last_usage["input_tokens"]

    threads = [
        threading.Thread(target=worker, args=("a", {"x": 1})),
        threading.Thread(target=worker, args=("b", {"x": 2})),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results["a"] < results["b"]


def test_invented_cues_are_normalised():
    text, changed = normalize_modulation_cues(
        "[Bold] Google-la [frustrated sigh] illa [Pause]"
    )
    assert text == "[Stress] Google-la [Pause] illa [Pause]"
    assert "[Bold]" in changed


def test_section_labels_removed_but_other_brackets_kept():
    text, changed = normalize_modulation_cues(
        "[Hook] [Smile] Hello [Laugh] [கவனிங்க] there [CTA]"
    )
    assert text == "[Smile] Hello [Laugh] [கவனிங்க] there"
    assert changed == ["[Hook]", "[CTA]"]


def test_foreign_indic_script_detected_and_removed():
    leaked = "[Curious tone] sonthha kadai লাভ varalaya?"
    assert find_foreign_indic_words(leaked) == ["লাভ"]
    cleaned, found = strip_foreign_indic_words(leaked)
    assert cleaned == "[Curious tone] sonthha kadai varalaya?"
    assert found
    assert find_foreign_indic_words("உங்க business-ku Tanglish ok") == []


def test_mixed_script_word_is_flagged_not_deleted():
    # One Telugu letter inside a Tamil verb: keep the word (audit flags it), don't drop the verb.
    mixed = "சர்வீஸை மெ" + "ర" + "ுகுப்படுத்துங்க, ok ?"
    cleaned, removed = strip_foreign_indic_words(mixed)
    assert cleaned == mixed  # untouched, including the unrelated " ?" spacing
    assert removed == []
    assert find_foreign_indic_words(mixed)  # still detected for the audit


def test_reference_url_blocks_internal_targets():
    for url in (
        "http://localhost:8000/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://10.1.2.3/",
        "http://[::1]/",
        "ftp://example.com/",
    ):
        assert _is_public_url(url) is False, url


class _FakeStream:
    """Minimal stand-in for httpx's streaming response context manager."""

    def __init__(self, redirect_to=None, body=b"", chunk=65536):
        self.is_redirect = redirect_to is not None
        self.headers = {"location": redirect_to} if redirect_to else {}
        self.encoding = "utf-8"
        self._body, self._chunk, self.bytes_read = body, chunk, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        for i in range(0, len(self._body), self._chunk):
            piece = self._body[i : i + self._chunk]
            self.bytes_read += len(piece)
            yield piece


def _fake_resolve(url):
    from src.search_tool import _PinnedTarget

    if "127.0.0.1" in url:
        return None
    return _PinnedTarget(
        "https://93.184.215.14/", "public.example.com", "public.example.com"
    )


def test_reference_url_redirect_to_internal_is_blocked():
    with (
        patch("src.search_tool._resolve_public", side_effect=_fake_resolve),
        patch(
            "httpx.Client.stream",
            return_value=_FakeStream(redirect_to="http://127.0.0.1/admin"),
        ) as mock_stream,
    ):
        assert fetch_reference_url("https://public.example.com/") is None
        assert (
            mock_stream.call_count == 1
        )  # never requested the internal redirect target


def test_reference_fetch_connects_to_vetted_ip_with_original_host():
    page = _FakeStream(
        body=b"<html><title>Offer</title><body>Clinic offer details</body></html>"
    )
    with (
        patch("src.search_tool._resolve_public", side_effect=_fake_resolve),
        patch("httpx.Client.stream", return_value=page) as mock_stream,
    ):
        result = fetch_reference_url("https://public.example.com/")
    method, url = mock_stream.call_args.args
    kwargs = mock_stream.call_args.kwargs
    assert url == "https://93.184.215.14/"  # pinned: no second DNS lookup by httpx
    assert kwargs["headers"]["Host"] == "public.example.com"
    assert kwargs["extensions"]["sni_hostname"] == "public.example.com"
    assert result["title"] == "Offer" and result["url"] == "https://public.example.com/"


def test_reference_fetch_stops_reading_at_size_cap():
    from src.search_tool import _MAX_FETCH_BYTES

    huge = _FakeStream(body=b"<p>" + b"x" * (_MAX_FETCH_BYTES * 3), chunk=100_000)
    with (
        patch("src.search_tool._resolve_public", side_effect=_fake_resolve),
        patch("httpx.Client.stream", return_value=huge),
    ):
        fetch_reference_url("https://public.example.com/")
    assert (
        huge.bytes_read < _MAX_FETCH_BYTES + 100_000
    )  # stopped early, didn't buffer 6 MB


def test_llm_failure_fallback_is_not_billed():
    llm = LLMClient(provider="simulation")
    assert llm._record_usage("simulation", 5000, 1500, "FALLBACK")["cost_inr"] == 0.0
    # Deliberate simulation mode keeps its estimated cost (used for quota demos/tests).
    assert llm._record_usage("simulation", 5000, 1500, "SIMULATION")["cost_inr"] > 0.0


def test_fallback_counts_zero_tokens_toward_daily_limit():
    meta = LLMClient(provider="simulation")._record_usage(
        "simulation", 5000, 1500, "FALLBACK"
    )
    assert (
        meta["total_tokens"] == 0
        and meta["input_tokens"] == 0
        and meta["output_tokens"] == 0
    )


def test_regenerated_hook_matches_single_recommended_flag():
    from src.agents.script_agent import ScriptAgent
    from src.models import ScriptDraft, ScriptInput

    llm = LLMClient(provider="simulation")
    reply = {
        "hooks": [
            {"text": "Hook one", "type": "question"},
            {"text": "Hook two"},
            {"text": "Hook three"},
        ],
        "recommended_hook": "Hook three",
    }
    inp = ScriptInput.create_with_defaults(
        topic="Hook consistency test topic", tone="Tanglish"
    )
    draft = ScriptDraft(
        hook="old", hooks=[], body_points=["point"], context="", engagement="", cta=""
    )
    with patch.object(llm, "generate_json", return_value=reply):
        updated = ScriptAgent(llm).regenerate_hooks(inp, draft)
    flagged = [h.text for h in updated.hooks if h.is_recommended]
    assert flagged == ["Hook three"] and updated.hook == "Hook three"
