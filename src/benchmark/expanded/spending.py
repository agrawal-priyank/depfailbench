"""Durable local dispatch ledger, including pending and uncertain charges.

Reservations are reviewed allowances, NOT provider-enforced cost bounds. In
particular, Grok's visible-output cap does not bound its reasoning bill.
"""

from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import json
import sqlite3
from datetime import datetime, timezone


class DispatchPaused(RuntimeError):
    pass


def units(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError("money must be finite and nonnegative")
    return int((value * 1000000000).to_integral_value(rounding=ROUND_CEILING))


class SpendingLedger:
    def __init__(self, path, *, limit_usd, simulation_only=True):
        if simulation_only is not True:
            raise ValueError("live execution is not enabled by this draft")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        limit = units(limit_usd)
        if limit <= 0:
            raise ValueError("explicit positive simulation budget required")
        with self.transaction() as db:
            schema = '''
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS slots (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    provider TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, slot_id TEXT NOT NULL,
                    number INTEGER NOT NULL, provider TEXT NOT NULL, state TEXT NOT NULL,
                    reserved INTEGER NOT NULL, charged INTEGER, outcome TEXT, response_id TEXT,
                    UNIQUE(slot_id, number));
                CREATE TABLE IF NOT EXISTS pauses (provider TEXT PRIMARY KEY, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (sequence INTEGER PRIMARY KEY, utc TEXT NOT NULL,
                    event TEXT NOT NULL, details TEXT NOT NULL);
            '''
            for statement in schema.split(';'):
                if statement.strip():
                    db.execute(statement)
            old = db.execute("SELECT value FROM settings WHERE name='limit'").fetchone()
            if old and int(old[0]) != limit:
                raise ValueError("cannot silently change an existing ledger spending limit")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('limit', ?)", (str(limit),))
            db.execute("INSERT OR IGNORE INTO settings VALUES ('simulation_only', 'true')")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def audit(db, event, details):
        db.execute("INSERT INTO audit (utc,event,details) VALUES (?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), event, json.dumps(details, sort_keys=True)))

    @staticmethod
    def totals(db):
        row = db.execute('''SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) AS committed,
            COALESCE(SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END),0) AS held,
            COALESCE(SUM(COALESCE(charged,0)),0) AS cost FROM attempts''').fetchone()
        return dict(row)

    def reserve(self, slot_id, provider, fingerprint, allowance_usd):
        allowance = units(allowance_usd)
        if allowance <= 0:
            raise ValueError("positive per-attempt allowance required")
        with self.transaction() as db:
            pause = db.execute("SELECT reason FROM pauses WHERE provider IN (?, '*')", (provider,)).fetchone()
            if pause:
                raise DispatchPaused(pause[0])
            slot = db.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
            if slot and (slot["fingerprint"] != fingerprint or slot["provider"] != provider):
                raise DispatchPaused("slot settings or prompt changed since its first attempt")
            if slot and slot["consumed"]:
                raise DispatchPaused("slot already contains a retained model output")
            attempts = db.execute("SELECT * FROM attempts WHERE slot_id=? ORDER BY number", (slot_id,)).fetchall()
            if any(a["state"] == "inflight" for a in attempts):
                raise DispatchPaused("unfinished attempt requires reconciliation before resuming")
            if len(attempts) >= 3:
                raise DispatchPaused("slot reached the three-attempt limit")
            active = db.execute("SELECT COUNT(*) FROM attempts WHERE provider=? AND state='inflight'", (provider,)).fetchone()[0]
            if active >= (1 if provider == "xAI" else 2):
                raise DispatchPaused("provider concurrency limit reached")
            limit = int(db.execute("SELECT value FROM settings WHERE name='limit'").fetchone()[0])
            if self.totals(db)["committed"] + allowance > limit:
                raise DispatchPaused("spending limit cannot cover pending/uncertain charges plus next allowance")
            number = len(attempts) + 1
            identity = f"{slot_id}:{number}"
            db.execute("INSERT OR IGNORE INTO slots(id,fingerprint,provider) VALUES (?,?,?)", (slot_id, fingerprint, provider))
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)",
                       (identity, slot_id, number, provider, "inflight", allowance, None, None, None,))
            self.audit(db, "reserve", {"attempt_id": identity, "allowance_units": allowance})
            return {"id": identity, "number": number, "reserved_units": allowance}

    def finish(self, identity, *, cost_usd, outcome, response_id=None, consume=False):
        charged = units(cost_usd) if cost_usd is not None else None
        with self.transaction() as db:
            attempt = db.execute("SELECT * FROM attempts WHERE id=?", (identity,)).fetchone()
            if not attempt or attempt["state"] != "inflight":
                raise DispatchPaused("attempt already settled or unknown")
            db.execute("UPDATE attempts SET state=?,charged=?,outcome=?,response_id=? WHERE id=?",
                       ("settled" if charged is not None else "uncertain", charged, outcome, response_id, identity))
            if consume:
                db.execute("UPDATE slots SET consumed=1 WHERE id=?", (attempt["slot_id"],))
            limit = int(db.execute("SELECT value FROM settings WHERE name='limit'").fetchone()[0])
            if charged is not None and charged > attempt["reserved"] or self.totals(db)["committed"] > limit:
                db.execute("INSERT OR REPLACE INTO pauses VALUES ('*', 'observed cost exceeded allowance or overall limit; review required')")
            self.audit(db, "finish", {"attempt_id": identity, "cost_units": charged,
                                      "outcome": outcome, "consumed": consume})

    def pause(self, provider, reason):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO pauses VALUES (?,?)", (provider, reason))
            self.audit(db, "pause", {"provider": provider, "reason": reason})

    def snapshot(self):
        with self.transaction() as db:
            return {"simulation_only": True, "currency": "USD", "units_per_usd": 1000000000,
                    "limit_units": int(db.execute("SELECT value FROM settings WHERE name='limit'").fetchone()[0]),
                    **self.totals(db),
                    "attempts": [dict(r) for r in db.execute("SELECT * FROM attempts ORDER BY rowid")],
                    "pauses": [dict(r) for r in db.execute("SELECT * FROM pauses")]}
