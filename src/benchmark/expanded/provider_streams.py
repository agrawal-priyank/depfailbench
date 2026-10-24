"""Incremental SSE decoding and provider-specific response assembly.

The caller preserves the complete wire bytes before decoding. Reasoning/thought
blocks are retained in raw records, never concatenated into the generated file.
"""

from copy import deepcopy
import codecs
import json


class SSEDecoder:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer, self.data = "", []

    def feed(self, chunk, *, final=False):
        self.buffer += self.decoder.decode(chunk, final=final)
        events = []
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.removesuffix("\r")
            if line == "":
                if self.data:
                    events.append("\n".join(self.data))
                    self.data = []
            elif line.startswith("data:"):
                self.data.append(line[5:].removeprefix(" "))
        if final and (self.buffer or self.data):
            # A disconnected stream may end without the SSE blank-line terminator.
            raise ValueError("unterminated SSE frame")
        return events


class ResponseAssembler:
    def __init__(self, provider):
        self.provider = provider
        self.raw = {}
        self.terminal = False
        self.content_received = False
        self.accepted = False
        self.blocks = {}
        self.deltas = {}

    def add(self, event):
        if event == "[DONE]":
            if self.provider == "Mistral":
                self.terminal = bool(self.raw.get("choices", [{}])[0].get("finish_reason"))
            return
        e = json.loads(event)
        kind = e.get("type") or e.get("event_type")
        if self.provider in {"OpenAI", "xAI"}:
            if isinstance(e.get("response"), dict):
                self.raw.update(deepcopy(e["response"]))
                self.accepted = bool(self.raw.get("id"))
                self.content_received |= bool(self.raw.get("output"))
            if kind == "response.output_item.added":
                self.content_received = True
            if kind == "response.output_text.delta":
                self.deltas.setdefault(e.get("output_index", 0), []).append(e.get("delta", ""))
            if kind and ("delta" in kind or "refusal" in kind):
                self.content_received = True
            if kind in {"response.completed", "response.incomplete", "response.failed"}:
                self.terminal = True
            if kind == "error":
                self.raw["error"] = e
                self.raw["status"] = "incomplete"
        elif self.provider == "Anthropic":
            if kind == "message_start":
                self.raw = deepcopy(e["message"])
                self.accepted = bool(self.raw.get("id"))
            elif kind == "content_block_start":
                self.blocks[e["index"]] = deepcopy(e["content_block"])
                self.content_received = True
            elif kind == "content_block_delta":
                self.content_received = True
                block = self.blocks.setdefault(e["index"], {"type": "text", "text": ""})
                delta = e["delta"]
                if delta.get("type") == "text_delta":
                    block["text"] = block.get("text", "") + delta["text"]
            elif kind == "message_delta":
                self.raw.update(e.get("delta", {}))
                self.raw.setdefault("usage", {}).update(e.get("usage", {}))
            elif kind == "message_stop":
                self.terminal = True
            elif kind == "error":
                self.raw["error"] = e["error"]
        elif self.provider == "Google":
            if isinstance(e.get("interaction"), dict):
                self.raw.update(deepcopy(e["interaction"]))
                self.accepted = bool(self.raw.get("id"))
            if kind == "step.start":
                self.blocks[e["index"]] = deepcopy(e["step"])
                self.content_received = True
            elif kind == "step.delta":
                self.content_received = True
                block = self.blocks.setdefault(e["index"], {"type": "model_output"})
                delta = e.get("delta", {})
                if block.get("type") == "model_output" and delta.get("type") == "text":
                    self.deltas.setdefault(e["index"], []).append(delta.get("text", ""))
            elif kind == "interaction.status_update":
                self.raw["status"] = e.get("status")
            if e.get("usage"):
                self.raw["usage"] = deepcopy(e["usage"])
            if (e.get("metadata") or {}).get("total_usage"):
                self.raw["usage"] = deepcopy(e["metadata"]["total_usage"])
            if kind == "interaction.completed" or kind == "interaction.status_update" and e.get("status") in {"completed", "incomplete", "failed", "cancelled"}:
                self.terminal = True
            if kind == "error":
                self.raw["error"] = e["error"]
        elif self.provider == "Mistral":
            for key in ("id", "model", "usage"):
                if e.get(key) is not None:
                    self.raw[key] = deepcopy(e[key])
            self.accepted = bool(self.raw.get("id"))
            choices = e.get("choices", [])
            if len(choices) > 1 or choices and choices[0].get("index", 0) != 0:
                raise ValueError("unexpected extra streamed choice")
            if choices:
                choice = choices[0]
                delta = choice.get("delta", {})
                message = self.blocks.setdefault(0, {"role": "assistant", "content": ""})
                if delta.get("content"):
                    self.content_received = True
                    if not isinstance(delta["content"], str):
                        raise ValueError("unsupported streamed completion content")
                    message["content"] += delta["content"]
                if delta.get("tool_calls"):
                    self.content_received = True
                    message.setdefault("tool_calls", []).extend(delta["tool_calls"])
                if delta.get("refusal"):
                    self.content_received = True
                    message["refusal"] = delta["refusal"]
                self.raw["choices"] = [{"index": 0, "message": message,
                                        "finish_reason": choice.get("finish_reason") or
                                        (self.raw.get("choices") or [{}])[0].get("finish_reason")}]
        else:
            raise ValueError("unsupported stream provider")

    def response(self):
        raw = deepcopy(self.raw)
        if self.provider in {"OpenAI", "xAI"} and self.deltas:
            # A partial stream can already contain a reasoning item while its
            # answer exists only in deltas. Do not lose that received answer.
            has_text = any(p.get("type") == "output_text" and p.get("text")
                           for item in raw.get("output", []) for p in item.get("content", []))
            if not has_text:
                raw.setdefault("output", []).extend(
                    {"type": "message", "content": [{"type": "output_text", "text": "".join(parts)}]}
                    for _, parts in sorted(self.deltas.items()))
        elif self.provider == "Anthropic" and self.blocks:
            raw["content"] = [b for _, b in sorted(self.blocks.items())]
        elif self.provider == "Google" and not raw.get("steps") and self.blocks:
            steps = []
            for index, block in sorted(self.blocks.items()):
                if index in self.deltas:
                    block["content"] = [{"type": "text", "text": "".join(self.deltas[index])}]
                steps.append(block)
            raw["steps"] = steps
        return raw
