"""Pure provider adapters. No keys, environment access, network calls or SDK retries.

The exact selected API is part of each configuration. Null settings are omitted;
unrecognised settings fail closed rather than being silently dropped.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re


ENDPOINTS = {
    "OpenAI": ("Responses", "https://api.openai.com/v1/responses"),
    "Anthropic": ("Messages", "https://api.anthropic.com/v1/messages"),
    "Google": ("Interactions", "https://generativelanguage.googleapis.com/v1beta/interactions"),
    "xAI": ("Responses", "https://api.x.ai/v1/responses"),
    "Mistral": ("Chat Completions", "https://api.mistral.ai/v1/chat/completions"),
}
ALLOWED_SETTINGS = {
    "OpenAI": {"reasoning_mode", "reasoning_effort", "temperature", "top_p"},
    "Anthropic": {"thinking_type", "effort", "temperature", "top_p", "top_k"},
    "Google": {"thinking_level", "temperature", "top_p", "top_k"},
    "xAI": {"reasoning_effort", "temperature", "top_p"},
    "Mistral": {"reasoning_effort", "temperature", "top_p"},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_request(config, prompt):
    """Return a credential-free wire request, retaining the exact prompt bytes."""
    provider = config["provider"]
    if provider not in ENDPOINTS or config["api"] != ENDPOINTS[provider][0]:
        raise ValueError("unsupported provider/API combination")
    settings = config["generation_settings"]
    if set(settings) - ALLOWED_SETTINGS[provider]:
        raise ValueError("unrecognised generation setting")
    limit = config["initial_output_parameter_limit"]
    if type(limit) is not int or not 16 <= limit <= 32000:
        raise ValueError("output limit must match the reviewed draft allowance")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("empty prompt")
    headers = {"Content-Type": "application/json"}
    body = {"model": config["model_id"], "stream": True}
    if provider in {"OpenAI", "xAI"}:
        body.update(input=prompt, max_output_tokens=limit, tools=[], tool_choice="none", store=False)
        body["service_tier"] = "default"
        body["reasoning"] = {"effort": settings["reasoning_effort"]}
        if provider == "OpenAI":
            body["reasoning"]["mode"] = settings["reasoning_mode"]
    elif provider == "Anthropic":
        headers["anthropic-version"] = "2023-06-01"
        body.update(messages=[{"role": "user", "content": prompt}], max_tokens=limit,
                    thinking={"type": settings["thinking_type"]},
                    output_config={"effort": settings["effort"]}, service_tier="standard_only")
    elif provider == "Google":
        body.update(input=prompt, store=False,
                    generation_config={"max_output_tokens": limit,
                                       "thinking_level": settings["thinking_level"]})
    else:
        body.update(messages=[{"role": "user", "content": prompt}], max_tokens=limit,
                    n=1, safe_prompt=False, service_tier="standard_only")
    sampling = body["generation_config"] if provider == "Google" else body
    for name in ("temperature", "top_p", "top_k"):
        if settings.get(name) is not None:
            sampling[name] = settings[name]
    if provider == "Mistral" and settings.get("reasoning_effort") is not None:
        body["reasoning_effort"] = settings["reasoning_effort"]
    return {"provider": provider, "api": config["api"], "url": ENDPOINTS[provider][1],
            "headers": headers, "body": body, "prompt_sha256": sha256(prompt),
            "configuration_sha256": sha256(canonical(config)),
            "request_sha256": sha256(canonical(body)),
            "output_limit_semantics": config["output_limit_semantics"]}


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("missing or invalid token counter")
    return value


def normalise_usage(provider, raw):
    """Keep unknown usage unknown. Reasoning is billed once, never added twice.

    Raw counters are always retained. Monetary values computed later are token
    estimates, not invoices; tool fees and unexpected schemas prevent pricing.
    """
    u = deepcopy(raw.get("usage"))
    result = {"raw": u, "complete": False, "input_tokens": None,
              "billable_output_tokens": None, "reasoning_tokens": None,
              "cached_input_tokens": None, "cache_write_tokens": None}
    try:
        if not isinstance(u, dict):
            raise ValueError("usage not returned")
        if provider in {"OpenAI", "xAI"}:
            inp = _count(u.get("input_tokens", u.get("prompt_tokens")))
            out = _count(u.get("output_tokens", u.get("completion_tokens")))
            details = u.get("output_tokens_details") or u.get("completion_tokens_details") or {}
            reasoning = details.get("reasoning_tokens")
            if reasoning is not None:
                reasoning = _count(reasoning)
            total = _count(u.get("total_tokens"))
            if total == inp + out:
                if reasoning is not None and reasoning > out:
                    raise ValueError("reasoning exceeds inclusive output count")
            elif provider == "xAI" and reasoning is not None and total == inp + out + reasoning:
                out += reasoning  # Older xAI response shapes report visible completion separately.
            else:
                raise ValueError("inconsistent input/output/total counters")
            cached = (u.get("input_tokens_details") or u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            cache_write = 0
            if any(u.get(k, 0) for k in ("num_sources_used", "num_server_side_tools_used")):
                raise ValueError("unexpected server tool use; token-only pricing insufficient")
        elif provider == "Anthropic":
            cache_write = _count(u.get("cache_creation_input_tokens", 0))
            cached = _count(u.get("cache_read_input_tokens", 0))
            inp = _count(u.get("input_tokens")) + cache_write + cached
            out = _count(u.get("output_tokens"))
            reasoning = (u.get("output_tokens_details") or {}).get("thinking_tokens")
            if reasoning is not None and _count(reasoning) > out:
                raise ValueError("thinking exceeds inclusive output count")
            if any((u.get("server_tool_use") or {}).values()):
                raise ValueError("unexpected server tool use")
        elif provider == "Google":
            inp = _count(u.get("total_input_tokens"))
            visible = _count(u.get("total_output_tokens"))
            reasoning = _count(u.get("total_thought_tokens"))
            out = visible + reasoning
            cached, cache_write = u.get("total_cached_tokens", 0), 0
            if u.get("total_tool_use_tokens", 0) or _count(u.get("total_tokens")) != inp + out:
                raise ValueError("unexpected tools or inconsistent interaction counters")
        elif provider == "Mistral":
            inp, out = _count(u.get("prompt_tokens")), _count(u.get("completion_tokens"))
            if _count(u.get("total_tokens")) != inp + out:
                raise ValueError("inconsistent completion counters")
            reasoning, cached, cache_write = None, u.get("prompt_cache_hit_tokens", 0), 0
        else:
            raise ValueError("unknown provider")
        cached = _count(cached)
        if cached + cache_write > inp:
            raise ValueError("cache counts exceed input count")
        result.update(complete=True, input_tokens=inp, billable_output_tokens=out,
                      reasoning_tokens=reasoning, cached_input_tokens=cached,
                      cache_write_tokens=cache_write)
    except (ValueError, TypeError) as exc:
        result["issue"] = str(exc)
    return result


@dataclass(frozen=True)
class TokenRates:
    """Reviewed rates supplied explicitly; no default price or spending approval."""
    input_per_million: str
    output_per_million: str
    source: str
    checked_date: str

    def estimate(self, usage):
        if not usage["complete"]:
            return None
        rate_in, rate_out = Decimal(self.input_per_million), Decimal(self.output_per_million)
        if not rate_in.is_finite() or not rate_out.is_finite() or min(rate_in, rate_out) < 0:
            raise ValueError("invalid token rates")
        # Ignore cache discounts; allow 2x input price for explicit cache writes.
        value = ((usage["input_tokens"] + usage["cache_write_tokens"]) * rate_in +
                 usage["billable_output_tokens"] * rate_out) / Decimal(1000000)
        return str(value)


def extract_source(text):
    """Only remove one whole-response Python fence; never repair generated code."""
    match = re.fullmatch(r"\s*```(?:python)?\s*\n(.*?)\n```\s*", text, re.I | re.S)
    source = match.group(1) if match else text
    return source.strip() + "\n" if source.strip() else ""


def parse_response(provider, raw, *, stream_complete=True):
    text, refusal, tool_use = "", False, False
    if provider in {"OpenAI", "xAI"}:
        parts = []
        for item in raw.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        parts.append(part.get("text", ""))
                    refusal |= part.get("type") == "refusal"
            elif item.get("type") not in {"reasoning", None}:
                tool_use = True
        text = "".join(parts)
        complete = raw.get("status") == "completed"
        truncated = (raw.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
        reason = raw.get("incomplete_details") or raw.get("error") or raw.get("status")
    elif provider == "Anthropic":
        text = "".join(p.get("text", "") for p in raw.get("content", []) if p.get("type") == "text")
        refusal = raw.get("stop_reason") == "refusal" or (raw.get("stop_details") or {}).get("type") == "refusal"
        tool_use = any(p.get("type") in {"tool_use", "server_tool_use"} for p in raw.get("content", []))
        complete, truncated = raw.get("stop_reason") == "end_turn", raw.get("stop_reason") == "max_tokens"
        reason = raw.get("stop_reason")
    elif provider == "Google":
        parts = []
        for step in raw.get("steps", []):
            if step.get("type") == "model_output":
                parts.extend(p.get("text", "") for p in step.get("content", []) if p.get("type") == "text")
            elif step.get("type") not in {"thought", None}:
                tool_use = True
        text = "".join(parts)
        complete, truncated = raw.get("status") == "completed", False
        reason = raw.get("error") or raw.get("status")
    elif provider == "Mistral":
        choices = raw.get("choices", [])
        if len(choices) > 1:
            raise ValueError("more than one generated choice")
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        text = content if isinstance(content, str) else "".join(p.get("text", "") for p in content if p.get("type") == "text")
        refusal = bool(message.get("refusal"))
        tool_use = bool(message.get("tool_calls"))
        complete, truncated = choice.get("finish_reason") == "stop", choice.get("finish_reason") in {"length", "model_length"}
        reason = choice.get("finish_reason")
    else:
        raise ValueError("unknown provider")
    status = ("refused" if refusal else "truncated" if truncated else
              "incomplete" if not complete or not stream_complete or tool_use else
              "completed" if text.strip() else "no_code")
    return {"generation_status": status, "text": text, "source": extract_source(text),
            "provider_response_id": raw.get("id"), "resolved_model_id": raw.get("model"),
            "finish_reason": reason, "unexpected_tool_use": tool_use,
            "usage": normalise_usage(provider, raw)}
