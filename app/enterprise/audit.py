"""
Audit and reproducibility module.

Every major output — analysis, alert, monitoring decision — emits an
immutable audit record that answers:

    "Why did this output happen, what evidence was used,
     and what decisions led here?"

Records are stored in-process (and optionally persisted to SQLite) and
can be queried by request_id or time range.

Abstractions
------------
AnalysisAuditRecord     : full analysis request → output trace
AlertAuditRecord        : alert generation trace
MonitoringDecisionRecord: monitoring event trace

AuditStore              : thread-safe record store with SQLite persistence
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUDIT_DB_FILENAME = "audit.db"


# ── Audit record types ────────────────────────────────────────────────────

@dataclass
class AnalysisAuditRecord:
    """Reproducibility record for a full analysis request.

    Attributes
    ----------
    audit_id            : unique ID for this record
    request_id          : analysis request ID
    timestamp           : ISO timestamp when analysis was completed
    company             : company being analyzed
    user_question       : the question submitted
    routing_decision    : routing metadata (agents selected, confidence)
    evidence_sources    : which providers were queried
    evidence_snapshot   : key fields from the grounding context
    agents_used         : list of agents that ran
    signal_profile_state: learning signal profiles active at the time
    configuration       : relevant config snapshot (model, version)
    has_errors          : whether any stage failed
    trace_id            : linked observability trace ID
    """
    audit_id:             str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id:           str = ""
    timestamp:            str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    company:              str = ""
    user_question:        str = ""
    routing_decision:     Dict[str, Any] = field(default_factory=dict)
    evidence_sources:     List[str] = field(default_factory=list)
    evidence_snapshot:    Dict[str, Any] = field(default_factory=dict)
    agents_used:          List[str] = field(default_factory=list)
    signal_profile_state: Dict[str, Any] = field(default_factory=dict)
    configuration:        Dict[str, Any] = field(default_factory=dict)
    has_errors:           bool = False
    trace_id:             str = ""
    notes:                str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class AlertAuditRecord:
    """Reproducibility record for alert generation.

    Attributes
    ----------
    audit_id        : unique ID for this record
    request_id      : parent analysis request ID
    timestamp       : ISO timestamp
    component       : which thesis component changed
    case_archetype  : historical case archetype assigned
    case_role       : current case role (escalation/continuation/etc)
    severity        : final severity assigned
    severity_reason : why this severity was chosen
    typical_consequence: expected consequence from archetype
    history_meaning_used: summary of HistoricalMeaning consulted
    supporting_evidence : evidence counts and metrics attached
    trace_id        : linked observability trace
    """
    audit_id:              str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id:            str = ""
    timestamp:             str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    component:             str = ""
    case_archetype:        str = ""
    case_role:             str = ""
    severity:              str = ""
    severity_reason:       str = ""
    typical_consequence:   str = ""
    history_meaning_used:  Dict[str, Any] = field(default_factory=dict)
    supporting_evidence:   Dict[str, Any] = field(default_factory=dict)
    trace_id:              str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class MonitoringDecisionRecord:
    """Reproducibility record for a monitoring event decision.

    Attributes
    ----------
    audit_id            : unique ID
    request_id          : parent request or event ID
    timestamp           : ISO timestamp
    event_type          : type of event processed
    signal_description  : raw signal text
    behavior_profile    : SignalBehaviorProfile.profile_type used
    pattern_role        : pattern role (reinforcing/echoing/etc)
    recommended_action  : action decided
    judgment_summary    : ContextualJudgment summary text
    history_meaning_used: HistoricalMeaning summary consulted
    temporal_context    : is_cluster, is_first_seen, is_recurrent flags
    trace_id            : linked observability trace
    """
    audit_id:             str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id:           str = ""
    timestamp:            str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    event_type:           str = ""
    signal_description:   str = ""
    behavior_profile:     str = ""
    pattern_role:         str = ""
    recommended_action:   str = ""
    judgment_summary:     str = ""
    history_meaning_used: Dict[str, Any] = field(default_factory=dict)
    temporal_context:     Dict[str, Any] = field(default_factory=dict)
    trace_id:             str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── AuditStore ────────────────────────────────────────────────────────────

class AuditStore:
    """Thread-safe in-process + optional SQLite audit record store.

    The in-memory store holds the most recent ``max_memory`` records per
    type for fast access.  All records are also persisted to SQLite when
    ``db_path`` is set.
    """

    def __init__(self, db_path: Optional[str] = None, max_memory: int = 500) -> None:
        self._db_path   = db_path
        self._max_memory = max_memory
        self._lock      = threading.Lock()
        self._analyses: List[AnalysisAuditRecord]        = []
        self._alerts:   List[AlertAuditRecord]            = []
        self._monitoring: List[MonitoringDecisionRecord]  = []
        if db_path:
            self._init_db()

    # ── persistence ──────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)  # type: ignore[arg-type]
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_audit (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    timestamp TEXT,
                    company TEXT,
                    payload TEXT NOT NULL
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_audit (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    timestamp TEXT,
                    component TEXT,
                    payload TEXT NOT NULL
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monitoring_audit (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    timestamp TEXT,
                    event_type TEXT,
                    payload TEXT NOT NULL
                )""")
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(f"AuditStore: DB init failed: {exc}")

    def _persist(self, table: str, row: tuple) -> None:
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path)  # type: ignore[arg-type]
            placeholders = ",".join(["?" for _ in row])
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})", row)
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(f"AuditStore: persist failed: {exc}")

    # ── record emission ───────────────────────────────────────────────────

    def record_analysis(self, record: AnalysisAuditRecord) -> None:
        with self._lock:
            self._analyses.append(record)
            if len(self._analyses) > self._max_memory:
                self._analyses = self._analyses[-self._max_memory:]
        self._persist("analysis_audit", (
            record.audit_id, record.request_id, record.timestamp,
            record.company, record.to_json(),
        ))
        logger.debug(f"Audit: analysis recorded request_id={record.request_id}")

    def record_alert(self, record: AlertAuditRecord) -> None:
        with self._lock:
            self._alerts.append(record)
            if len(self._alerts) > self._max_memory:
                self._alerts = self._alerts[-self._max_memory:]
        self._persist("alert_audit", (
            record.audit_id, record.request_id, record.timestamp,
            record.component, record.to_json(),
        ))

    def record_monitoring(self, record: MonitoringDecisionRecord) -> None:
        with self._lock:
            self._monitoring.append(record)
            if len(self._monitoring) > self._max_memory:
                self._monitoring = self._monitoring[-self._max_memory:]
        self._persist("monitoring_audit", (
            record.audit_id, record.request_id, record.timestamp,
            record.event_type, record.to_json(),
        ))

    # ── query ─────────────────────────────────────────────────────────────

    def get_analysis(self, request_id: str) -> Optional[AnalysisAuditRecord]:
        with self._lock:
            for r in reversed(self._analyses):
                if r.request_id == request_id:
                    return r
        return None

    def get_alerts_for_request(self, request_id: str) -> List[AlertAuditRecord]:
        with self._lock:
            return [r for r in self._alerts if r.request_id == request_id]

    def get_monitoring_for_request(self, request_id: str) -> List[MonitoringDecisionRecord]:
        with self._lock:
            return [r for r in self._monitoring if r.request_id == request_id]

    def recent_analyses(self, n: int = 20) -> List[AnalysisAuditRecord]:
        with self._lock:
            return list(reversed(self._analyses[-n:]))

    def recent_alerts(self, n: int = 50) -> List[AlertAuditRecord]:
        with self._lock:
            return list(reversed(self._alerts[-n:]))

    def recent_monitoring(self, n: int = 50) -> List[MonitoringDecisionRecord]:
        with self._lock:
            return list(reversed(self._monitoring[-n:]))

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "analysis_records":   len(self._analyses),
                "alert_records":      len(self._alerts),
                "monitoring_records": len(self._monitoring),
            }


# ── Default global store ──────────────────────────────────────────────────
#
# By default the global audit_store is IN-MEMORY ONLY (db_path=None).
# SQLite persistence is opt-in: set the ANTHROPIC_AUDIT_DB environment
# variable or pass db_path explicitly to a new AuditStore instance.
#
# This prevents module import from creating files on disk, which is essential
# for clean test runs, ephemeral environments, and deterministic behavior.

import os as _os

_default_db_path: Optional[str] = _os.environ.get("ANTHROPIC_AUDIT_DB") or None
audit_store = AuditStore(db_path=_default_db_path)

