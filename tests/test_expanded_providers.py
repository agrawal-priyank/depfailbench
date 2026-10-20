"""Wire-format, lost-output, billing and restart controls. No live credentials."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from benchmark.expanded.planning import allocation, assets_root, prompt
from benchmark.expanded.provider_dry_run import fixture, sse_bytes, stream_events
from benchmark.expanded.provider_generation import OfflineGenerator, retry_delay
from benchmark.expanded.providers import ENDPOINTS, TokenRates, build_request, normalise_usage, parse_response
from benchmark.expanded.provider_streams import ResponseAssembler, SSEDecoder
from benchmark.expanded.spending import DispatchPaused, SpendingLedger


DESIGN = json.loads((assets_root() / "study.json").read_text())
CONFIGS = {c["id"]: c for c in DESIGN["configurations"]}
SOURCE = json.loads((assets_root() / "provider_fixtures.json").read_text())["source"]
RATES = {c["model_id"]: TokenRates("2", "10", "synthetic://not-actual-prices", "2026-10-19") for c in CONFIGS.values()}


def selected(provider, count=1):
    return [s for s in allocation()[1] if s["provider"] == provider][:count]


def generator(tmp_path, handler, *, limit="10", sleep=asyncio.sleep):
    ledger = SpendingLedger(tmp_path / "ledger.sqlite", limit_usd=limit)
    return OfflineGenerator(output=tmp_path / "artifacts", ledger=ledger,
                            transport=httpx.MockTransport(handler), rates=RATES, sleep=sleep)


@pytest.mark.parametrize("config", list(CONFIGS.values()), ids=list(CONFIGS))
def test_exact_selected_request_and_omissions(config):
    text = prompt("E6", "C1")
    r = build_request(config, text)
    b, provider = r["body"], config["provider"]
    assert r["url"] == ENDPOINTS[provider][1]
    assert b["model"] == config["model_id"] and b["stream"] is True
    assert "Authorization" not in r["headers"] and "x-api-key" not in r["headers"]
    assert "system" not in b and "instructions" not in b and "previous_response_id" not in b
    if provider in {"OpenAI", "xAI", "Google"}:
        assert b["input"] == text and b["store"] is False
    else:
        assert b["messages"] == [{"role": "user", "content": text}]
    if provider == "OpenAI":
        assert b["reasoning"] == {"mode": "standard", "effort": config["generation_settings"]["reasoning_effort"]}
        assert b["max_output_tokens"] == 32000 and b["service_tier"] == "default"
    elif provider == "Anthropic":
        assert b["thinking"] == {"type": "adaptive"} and b["output_config"] == {"effort": "high"}
        assert b["max_tokens"] == 32000 and r["headers"]["anthropic-version"] == "2023-06-01"
    elif provider == "Google":
        assert b["generation_config"] == {"max_output_tokens": 32000, "thinking_level": "medium"}
        assert "contents" not in b and "generationConfig" not in b
    elif provider == "xAI":
        assert b["reasoning"] == {"effort": "high"} and b["temperature"] == .7 and b["top_p"] == .95
        assert r["output_limit_semantics"] == "visible_only_reasoning_excluded"
    elif provider == "Mistral":
        assert b["temperature"] == config["generation_settings"]["temperature"]
        assert b["top_p"] == 1 and b["n"] == 1 and b["safe_prompt"] is False
        assert "reasoning_effort" not in b
    if provider in {"OpenAI", "Anthropic", "Google"}:
        assert all(k not in b for k in ("temperature", "top_p", "top_k"))


def test_unknown_parameter_or_changed_api_fails_instead_of_silently_dropping_it():
    c = deepcopy(CONFIGS["gemini_3_8_flash"])
    c["api"] = "GenerateContent"
    with pytest.raises(ValueError, match="API"):
        build_request(c, "hello")
    c["api"] = "Interactions"
    c["generation_settings"]["invented_setting"] = "high"
    with pytest.raises(ValueError, match="unrecognised"):
        build_request(c, "hello")


@pytest.mark.parametrize("provider", list(ENDPOINTS))
def test_provider_accounting_and_reasoning_exclusion_from_source(provider):
    parsed = parse_response(provider, fixture(provider))
    assert parsed["generation_status"] == "completed" and parsed["source"] == SOURCE
    assert parsed["usage"]["complete"]
    assert parsed["usage"]["input_tokens"] == 100
    assert parsed["usage"]["billable_output_tokens"] == (20 if provider == "Mistral" else 60)
    assert "THINKING" not in parsed["source"]


@pytest.mark.parametrize("provider", list(ENDPOINTS))
def test_streamed_provider_shapes_with_every_byte_split(provider):
    decoder, assembler = SSEDecoder(), ResponseAssembler(provider)
    for value in sse_bytes(stream_events(provider, fixture(provider))):
        for event in decoder.feed(bytes([value])):
            assembler.add(event)
    decoder.feed(b"", final=True)
    parsed = parse_response(provider, assembler.response(), stream_complete=assembler.terminal)
    assert assembler.terminal and assembler.content_received
    assert parsed["source"] == SOURCE and parsed["generation_status"] == "completed"
    assert parsed["usage"]["billable_output_tokens"] == (20 if provider == "Mistral" else 60)


def test_sse_unicode_crlf_comments_and_incomplete_frames():
    decoder = SSEDecoder()
    data = ': heartbeat\r\ndata: {"text":\r\ndata: "café"}\r\n\r\n'.encode()
    events = []
    for chunk in data:
        events.extend(decoder.feed(bytes([chunk])))
    assert json.loads(events[0]) == {"text": "café"}
    decoder.feed(b"", final=True)
    with pytest.raises(ValueError, match="unterminated"):
        SSEDecoder().feed(b'data: {"x":1}', final=True)


def test_openai_cache_writes_are_retained_and_conservatively_priced():
    raw = fixture("OpenAI")
    raw["usage"]["input_tokens_details"] = {"cached_tokens": 20, "cache_write_tokens": 60}
    usage = normalise_usage("OpenAI", raw)
    assert usage["complete"] and usage["input_tokens"] == 100
    assert usage["cache_write_tokens"] == 60 and usage["cached_input_tokens"] == 20
    # Input is inclusive; the budget estimate allows 2x for writes and ignores
    # read discounts, conservatively covering the documented 1.25x write rate.
    rates = TokenRates("2", "10", "https://developers.openai.com/api/docs/guides/prompt-caching", "2026-10-20")
    assert rates.estimate(usage) == "0.00092"


@pytest.mark.parametrize("written", [-1, True, "60", 81])
def test_invalid_or_excess_openai_cache_writes_block_pricing(written):
    raw = fixture("OpenAI")
    raw["usage"]["input_tokens_details"] = {"cached_tokens": 20, "cache_write_tokens": written}
    usage = normalise_usage("OpenAI", raw)
    assert not usage["complete"]
    assert RATES["gpt-6.1-sol"].estimate(usage) is None


def test_unknown_or_inconsistent_usage_is_not_free_and_xai_shapes_do_not_double_bill():
    assert not normalise_usage("Google", {"usage": {"total_input_tokens": 1}})["complete"]
    assert not normalise_usage("OpenAI", {"usage": {"input_tokens": True, "output_tokens": 1, "total_tokens": 2}})["complete"]
    raw = fixture("xAI")
    old = {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 160,
                     "completion_tokens_details": {"reasoning_tokens": 40}}}
    assert normalise_usage("xAI", raw)["billable_output_tokens"] == normalise_usage("xAI", old)["billable_output_tokens"] == 60
    raw["usage"]["total_tokens"] = 300
    assert not normalise_usage("xAI", raw)["complete"]
    assert RATES["grok-4.7"].estimate(normalise_usage("xAI", raw)) is None


@pytest.mark.parametrize("mode,status", [("max_tokens", "truncated"), ("refusal", "refused"), ("empty", "no_code"), ("tool", "incomplete")])
def test_returned_unsuccessful_outputs_keep_their_generation_status(mode, status):
    raw = fixture("OpenAI")
    if mode == "max_tokens":
        raw.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    elif mode == "refusal":
        raw["output"] = [{"type": "message", "content": [{"type": "refusal", "refusal": "declined"}]}]
    elif mode == "empty":
        raw["output"] = []
    else:
        raw["output"].append({"type": "function_call", "name": "invented"})
    assert parse_response("OpenAI", raw)["generation_status"] == status


def test_ledger_keeps_pending_and_unknown_costs_and_refuses_changed_or_repeated_slots(tmp_path):
    ledger = SpendingLedger(tmp_path / "spend.sqlite", limit_usd="1")
    a = ledger.reserve("slot1", "OpenAI", "fingerprint", ".6")
    with pytest.raises(DispatchPaused, match="spending"):
        ledger.reserve("slot2", "Google", "x", ".5")
    with pytest.raises(DispatchPaused, match="unfinished"):
        ledger.reserve("slot1", "OpenAI", "fingerprint", ".1")
    ledger.finish(a["id"], cost_usd=None, outcome="incomplete", consume=True)
    assert ledger.snapshot()["held"] == 600000000
    reopened = SpendingLedger(tmp_path / "spend.sqlite", limit_usd="1")
    with pytest.raises(DispatchPaused, match="retained"):
        reopened.reserve("slot1", "OpenAI", "fingerprint", ".1")
    with pytest.raises(DispatchPaused, match="changed"):
        reopened.reserve("slot1", "OpenAI", "other", ".1")
    with pytest.raises(ValueError, match="silently change"):
        SpendingLedger(tmp_path / "spend.sqlite", limit_usd="2")


def test_ledger_observed_overrun_pauses_dispatch_and_keeps_actual_amount(tmp_path):
    ledger = SpendingLedger(tmp_path / "spend.sqlite", limit_usd="1")
    a = ledger.reserve("slot1", "xAI", "a", ".1")
    ledger.finish(a["id"], cost_usd=".2", outcome="completed", consume=True)
    assert ledger.snapshot()["cost"] == 200000000
    with pytest.raises(DispatchPaused, match="exceeded"):
        ledger.reserve("slot2", "Mistral", "b", ".1")


def test_ledger_reservations_are_atomic_across_separate_connections(tmp_path):
    path = tmp_path / "spend.sqlite"
    SpendingLedger(path, limit_usd="1")
    def reserve(index):
        ledger = SpendingLedger(path, limit_usd="1")
        try:
            return ledger.reserve(f"slot{index}", "OpenAI", str(index), ".6")
        except DispatchPaused:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(reserve, range(2)))
    assert sum(r is not None for r in rows) == 1
    assert SpendingLedger(path, limit_usd="1").snapshot()["committed"] == 600000000


@pytest.mark.parametrize("provider,maximum", [("OpenAI", 2), ("xAI", 1)])
async def test_provider_parallelism_limits(tmp_path, provider, maximum):
    active, peak = 0, 0
    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return httpx.Response(200, json=fixture(provider, json.loads(request.content)["model"]), request=request)
    runner = generator(tmp_path, handler)
    rows = await asyncio.gather(*(runner.generate(s, allowance_usd=".01") for s in selected(provider, 4)))
    assert peak == maximum and len(rows) == 4


async def test_transient_http_failures_retry_exact_request_and_retain_unknown_charges(tmp_path):
    calls, delays = [], []
    async def sleep(delay):
        delays.append(delay)
    def handler(request):
        calls.append(request.content)
        if len(calls) <= 2:
            return httpx.Response(529, headers={"retry-after": "4"}, json={"error": "synthetic overload"}, request=request)
        return httpx.Response(200, json=fixture("Anthropic"), request=request)
    runner = generator(tmp_path, handler, sleep=sleep)
    slot = selected("Anthropic")[0]
    result = await runner.generate(slot, allowance_usd=".01")
    assert result["generation_status"] == "completed"
    assert len(calls) == 3 and len(set(calls)) == 1 and delays == [4, 8]
    snapshot = runner.ledger.snapshot()
    assert [r["state"] for r in snapshot["attempts"]] == ["uncertain", "uncertain", "settled"]
    assert snapshot["held"] == 20000000
    with pytest.raises(DispatchPaused, match="exists"):
        await runner.generate(slot, allowance_usd=".01")


async def test_exhausted_service_failure_is_unfilled_not_a_model_failure(tmp_path):
    async def sleep(delay):
        pass
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": "unavailable"}, request=request)
    runner = generator(tmp_path, handler, sleep=sleep)
    slot = selected("Mistral")[0]
    with pytest.raises(DispatchPaused):
        await runner.generate(slot, allowance_usd=".01")
    directory = tmp_path / "artifacts" / slot["artifact_id"]
    assert len(calls) == 3 and not (directory / "metadata.json").exists()
    assert json.loads((directory / "slot_state.json").read_text())["state"] == "paused_unfilled"
    assert not any(a["outcome"] != "service_unfilled" for a in runner.ledger.snapshot()["attempts"])


@pytest.mark.parametrize("mode", ["truncated", "refused", "no_code", "syntax_error"])
async def test_bad_returned_outputs_are_saved_without_replacement(tmp_path, mode):
    calls = []
    raw = fixture("OpenAI")
    if mode == "truncated":
        raw.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    elif mode == "refused":
        raw["output"] = [{"type": "message", "content": [{"type": "refusal", "refusal": "declined"}]}]
    elif mode == "no_code":
        raw["output"] = []
    else:
        raw["output"] = [{"type": "message", "content": [{"type": "output_text", "text": "def broken(\n"}]}]
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=raw, request=request)
    runner = generator(tmp_path, handler)
    slot = selected("OpenAI")[0]
    result = await runner.generate(slot, allowance_usd=".01")
    assert len(calls) == 1 and result["generation_status"] == ("completed" if mode == "syntax_error" else mode)
    directory = tmp_path / "artifacts" / slot["artifact_id"]
    assert (directory / "attempt_01/wire_response.bin").read_bytes()
    if mode == "syntax_error":
        assert (directory / "app.py").read_text() == "def broken(\n"


class InterruptedStream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content
    async def __aiter__(self):
        yield self.content
        raise httpx.ReadError("synthetic disconnect")


async def test_partial_stream_keeps_code_and_never_retries(tmp_path):
    events = stream_events("OpenAI", fixture("OpenAI"))[:2]
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=InterruptedStream(sse_bytes(events)), request=request)
    runner = generator(tmp_path, handler)
    slot = selected("OpenAI")[0]
    result = await runner.generate(slot, allowance_usd=".01")
    assert result["generation_status"] == "incomplete" and len(calls) == 1
    assert (tmp_path / "artifacts" / slot["artifact_id"] / "app.py").read_text() == SOURCE
    assert runner.ledger.snapshot()["held"] == 10000000


async def test_acknowledged_stream_without_content_pauses_for_recovery(tmp_path):
    events = stream_events("xAI", fixture("xAI"))[:1]
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=InterruptedStream(sse_bytes(events)), request=request)
    runner = generator(tmp_path, handler)
    with pytest.raises(DispatchPaused):
        await runner.generate(selected("xAI")[0], allowance_usd=".01")
    assert len(calls) == 1 and runner.ledger.snapshot()["attempts"][0]["response_id"] == "synthetic-xai"


async def test_no_live_transport_or_credential_access_and_metadata_remains_synthetic(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "DO-NOT-READ-OR-SAVE-THIS-CANARY")
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json=fixture("OpenAI"), request=request)
    runner = generator(tmp_path, handler)
    result = await runner.generate(selected("OpenAI")[0], allowance_usd=".01")
    assert result["simulation_only"] and result["synthetic_data"]
    for file in (tmp_path / "artifacts").rglob("*"):
        if file.is_file():
            assert b"DO-NOT-READ-OR-SAVE-THIS-CANARY" not in file.read_bytes()
    with pytest.raises(ValueError, match="live calls disabled"):
        OfflineGenerator(output=tmp_path / "other", ledger=runner.ledger, transport=None, rates=RATES)
    with pytest.raises(ValueError, match="live execution"):
        SpendingLedger(tmp_path / "live.sqlite", limit_usd="10", simulation_only=False)


def test_retry_after_date_and_long_pause():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    assert retry_delay(1, "Mon, 19 Oct 2026 12:00:10 GMT", now=now) == 10
    with pytest.raises(DispatchPaused, match="120"):
        retry_delay(1, "121")


def test_partial_reasoning_prefix_does_not_hide_received_answer():
    assembler = ResponseAssembler("OpenAI")
    assembler.add(json.dumps({"type": "response.created", "response": {
        "id": "synthetic", "status": "in_progress", "output": [{"type": "reasoning"}]}}))
    assembler.add(json.dumps({"type": "response.output_text.delta", "output_index": 1, "delta": "def broken(\n"}))
    parsed = parse_response("OpenAI", assembler.response(), stream_complete=False)
    assert parsed["source"] == "def broken(\n" and parsed["generation_status"] == "incomplete"


@pytest.mark.parametrize("response", [b"not-json", b"null", b"[]"])
async def test_malformed_responses_preserve_wire_evidence_and_pause_without_retry(tmp_path, response):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=response, request=request)
    runner = generator(tmp_path, handler)
    slot = selected("Google")[0]
    with pytest.raises(DispatchPaused):
        await runner.generate(slot, allowance_usd=".01")
    directory = tmp_path / "artifacts" / slot["artifact_id"]
    assert len(calls) == 1
    assert (directory / "attempt_01/wire_response.bin").read_bytes() == response
    assert not (directory / "metadata.json").exists()
    assert runner.ledger.snapshot()["held"] == 10000000


@pytest.mark.parametrize("status", [400, 401, 403, 404, 501])
async def test_configuration_auth_and_nontransient_errors_do_not_retry(tmp_path, status):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": "synthetic"}, request=request)
    runner = generator(tmp_path, handler)
    with pytest.raises(DispatchPaused):
        await runner.generate(selected("Google")[0], allowance_usd=".01")
    assert len(calls) == 1


async def test_unknown_billing_can_stop_retry_before_budget_is_exceeded(tmp_path):
    calls = []
    async def sleep(delay):
        pass
    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "synthetic"}, request=request)
    runner = generator(tmp_path, handler, limit=".015", sleep=sleep)
    with pytest.raises(DispatchPaused, match="spending"):
        await runner.generate(selected("Mistral")[0], allowance_usd=".01")
    assert len(calls) == 1 and runner.ledger.snapshot()["held"] == 10000000


async def test_connect_failure_retries_but_read_timeout_does_not(tmp_path):
    calls = []
    async def sleep(delay):
        pass
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("synthetic pre-dispatch failure", request=request)
        raise httpx.ReadTimeout("synthetic ambiguous accepted request", request=request)
    runner = generator(tmp_path, handler, sleep=sleep)
    with pytest.raises(DispatchPaused):
        await runner.generate(selected("OpenAI")[0], allowance_usd=".01")
    assert len(calls) == 2
    assert [a["outcome"] for a in runner.ledger.snapshot()["attempts"]] == ["service_unfilled", "service_unfilled"]


async def test_model_version_and_raw_usage_preserved_even_when_missing_usage_pauses_provider(tmp_path):
    raw = fixture("OpenAI")
    raw["model"] = "synthetic-resolved-snapshot"
    raw.pop("usage")
    def handler(request):
        return httpx.Response(200, json=raw, request=request)
    runner = generator(tmp_path, handler)
    slots = selected("OpenAI", 2)
    row = await runner.generate(slots[0], allowance_usd=".01")
    assert row["model_id"] == slots[0]["model_id"]
    assert row["resolved_model_id"] == "synthetic-resolved-snapshot"
    assert row["estimated_token_cost_usd"] is None and row["provider_usage"]["raw"] is None
    with pytest.raises(DispatchPaused, match="billing"):
        await runner.generate(slots[1], allowance_usd=".01")
