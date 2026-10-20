"""Explicit, hash-bound paid-execution permission. Reading it makes no API call.

No permission file is created automatically. Validation permission cannot enable
main generation; main additionally needs the complete frozen study declaration.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from decimal import InvalidOperation

from .planning import assets_root, check
from .providers import TokenRates
from .spending import DispatchPaused, units


def execution_snapshot(root=None):
    root = assets_root(root)
    files = [root / n for n in ("study.json", "scaffold.py", "task_contracts.json", "analysis.py", "requirements-analysis.txt")]
    files += sorted((root / "prompts").glob("*.md")) + sorted((root / "tasks").glob("*.md"))
    files += [root.parent / "requirements.lock"]
    result = {str(p.relative_to(root.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result.update({"implementation/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(Path(__file__).resolve().parent.glob("*.py"))})
    return result


class ExecutionPermit:
    """A reviewed local record, not a replacement for the author's authorization."""
    def __init__(self, path, *, root=None):
        self.path, self.root = Path(path), assets_root(root)
        self.document = json.loads(self.path.read_text())
        self.document_sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.validate()

    def validate(self):
        d = self.document
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.document_sha256:
            raise DispatchPaused("execution permission changed; review and reopen it explicitly")
        if d.get("schema_version") != 1:
            raise DispatchPaused("unsupported execution authorization schema")
        if d.get('execution_mode') == 'mock_validation':
            if d.get('mock_validation_authorized') is not True or d.get('paid_execution_authorized') is not False:
                raise DispatchPaused('mock permission must explicitly prohibit paid execution')
        elif d.get('execution_mode') != 'live' or d.get('paid_execution_authorized') is not True:
            raise DispatchPaused("explicit paid execution authorization is absent")
        if d.get("cohort") not in {"validation", "main"}:
            raise DispatchPaused("authorization must select exactly one cohort")
        for field in ("authorized_by", "authorization_record"):
            if not isinstance(d.get(field), str) or not d[field].strip():
                raise DispatchPaused("author and authorization record must be supplied")
        try:
            expires = datetime.fromisoformat(d["expires_at_utc"])
        except (KeyError, ValueError, TypeError):
            raise DispatchPaused("explicit timezone-aware authorization expiry required") from None
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise DispatchPaused("execution authorization expired or lacks a timezone")
        if units(d.get("maximum_cost_usd", 0)) <= 0:
            raise DispatchPaused("a reviewed positive numeric spending limit is required")
        check(self.root)
        if d.get("snapshot") != execution_snapshot(self.root):
            raise DispatchPaused("implementation, prompts, configuration or environment lock differs from authorization")
        study = json.loads((self.root / "study.json").read_text())
        if d["cohort"] == "main" and not (study.get("frozen") is True and study.get("paid_execution_authorized") is True):
            raise DispatchPaused("main generation requires the final frozen and authorized protocol")
        return d

    def validate_budget(self, limit_usd):
        self.validate()
        if units(limit_usd) != units(self.document["maximum_cost_usd"]):
            raise DispatchPaused("ledger spending limit differs from the authorized limit")

    def validate_slot(self, slot, rates):
        self.validate()
        if slot["cohort"] != self.document["cohort"]:
            raise DispatchPaused("slot cohort is outside this execution authorization")
        recorded = self.document.get("token_rates")
        actual = {name: asdict(rate) for name, rate in rates.items() if isinstance(rate, TokenRates)}
        if recorded != actual or len(actual) != len(rates):
            raise DispatchPaused("explicit reviewed token rates differ from the authorization")
        expected = {c['model_id'] for c in json.loads((self.root/'study.json').read_text())['configurations']}
        if set(actual) != expected:
            raise DispatchPaused('reviewed token rates must cover the complete selected panel')
        try:
            for rate in rates.values():
                if not rate.source.strip() or not rate.checked_date.strip():
                    raise ValueError('pricing source and checked date required')
                rate.estimate({'complete':True,'input_tokens':0,'cache_write_tokens':0,'billable_output_tokens':0})
        except (ValueError, TypeError, AttributeError, InvalidOperation):
            raise DispatchPaused('invalid reviewed token prices; dispatch blocked') from None

    @property
    def fingerprint(self):
        return self.document_sha256
