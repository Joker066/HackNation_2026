"""Audit log of every check: question (PII-masked), time, sources, result, cost, latency."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas import CheckResponse, Status, Verdict

from .db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    request_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    session_id TEXT,
    input_masked TEXT NOT NULL,
    status TEXT NOT NULL,
    verdicts TEXT NOT NULL,
    sources TEXT NOT NULL,
    abstained INTEGER NOT NULL,
    security_events TEXT NOT NULL,
    error_detail TEXT,
    latency_ms INTEGER NOT NULL,
    llm_model TEXT,
    llm_input_tokens INTEGER NOT NULL DEFAULT 0,
    llm_output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    retrieval_errors INTEGER NOT NULL DEFAULT 0,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checks_session ON checks(session_id);
CREATE INDEX IF NOT EXISTS checks_created ON checks(created_at);
"""


class AuditLog:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        with connect(db_path) as conn:
            conn.executescript(SCHEMA)

    def save(
        self,
        response: CheckResponse,
        *,
        channel: str,
        session_id: str | None,
        input_masked: str,
        latency_ms: int,
        llm_model: str | None,
        llm_input_tokens: int,
        llm_output_tokens: int,
        cost_usd: float,
        retrieval_errors: int = 0,
    ) -> None:
        verdicts = [c.verdict.value for c in response.claims]
        sources = sorted({e.url for c in response.claims for e in c.evidence})
        abstained = any(v == Verdict.insufficient.value for v in verdicts)
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    response.request_id,
                    response.created_at.isoformat(),
                    channel,
                    session_id,
                    input_masked,
                    response.status.value,
                    json.dumps(verdicts, ensure_ascii=False),
                    json.dumps(sources),
                    int(abstained),
                    json.dumps(response.security_events, ensure_ascii=False),
                    response.status_detail if response.status != Status.ok else None,
                    latency_ms,
                    llm_model,
                    llm_input_tokens,
                    llm_output_tokens,
                    cost_usd,
                    retrieval_errors,
                    response.model_dump_json(),
                ),
            )

    def get(self, request_id: str) -> CheckResponse | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT response_json FROM checks WHERE request_id = ?", (request_id,)).fetchone()
        return CheckResponse.model_validate_json(row["response_json"]) if row else None

    def recent(self, limit: int = 50) -> list[dict]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM checks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{k: row[k] for k in row.keys() if k != "response_json"} for row in rows]

    def delete_session(self, session_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("DELETE FROM checks WHERE session_id = ?", (session_id,)).rowcount

    def purge_older_than(self, days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with connect(self.db_path) as conn:
            return conn.execute("DELETE FROM checks WHERE created_at < ?", (cutoff,)).rowcount

    def metrics(self) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS checks,
                          SUM(status = 'ok') AS ok,
                          SUM(status = 'error') AS errors,
                          SUM(abstained) AS abstentions,
                          SUM(security_events != '[]') AS security_events,
                          SUM(retrieval_errors) AS retrieval_errors,
                          SUM(cost_usd) AS total_cost_usd,
                          AVG(cost_usd) AS avg_cost_usd
                   FROM checks"""
            ).fetchone()
            latencies = [r[0] for r in conn.execute("SELECT latency_ms FROM checks ORDER BY latency_ms")]
        result = dict(row)
        result["median_latency_ms"] = latencies[len(latencies) // 2] if latencies else None
        return result
