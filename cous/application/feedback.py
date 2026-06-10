"""Structured human feedback store for operational learning.

Feedback records are append-only JSONL, tolerant to corruption,
and exportable as goldens for OpenTracy evals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MAX_FEEDBACK_RECORDS = 10_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FeedbackRecord:
    id: str
    feedback_type: str  # "confirmed" | "correction" | "solution_applied"
    session_id: str
    trace_id: str  # trace_id da resposta que gerou o feedback
    measurement_id: str | None = None
    content: str = ""
    original_response: str = ""
    user_request: str = ""  # pergunta original do operador
    timestamp: str = field(default_factory=_utc_now_iso)


class FeedbackStore:
    """Append-only JSONL store for structured human feedback."""

    def __init__(self, path: Path) -> None:
        self._path = path

    # -- write ----------------------------------------------------------------

    def record(
        self,
        *,
        feedback_type: str,
        session_id: str,
        trace_id: str = "",
        content: str = "",
        original_response: str = "",
        user_request: str = "",
        measurement_id: str | None = None,
    ) -> FeedbackRecord:
        rec = FeedbackRecord(
            id=f"fb_{uuid4().hex[:12]}",
            feedback_type=feedback_type,
            session_id=session_id,
            trace_id=trace_id,
            measurement_id=measurement_id,
            content=content,
            original_response=original_response,
            user_request=user_request,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "id": rec.id,
                            "feedback_type": rec.feedback_type,
                            "session_id": rec.session_id,
                            "trace_id": rec.trace_id,
                            "measurement_id": rec.measurement_id,
                            "content": rec.content,
                            "original_response": rec.original_response,
                            "user_request": rec.user_request,
                            "timestamp": rec.timestamp,
                        },
                        ensure_ascii=True,
                        default=str,
                    )
                    + "\n"
                )
        except OSError:
            pass  # feedback nunca derruba o terminal
        return rec

    # -- read ----------------------------------------------------------------

    def list_records(self, *, feedback_type: str | None = None) -> list[FeedbackRecord]:
        if not self._path.is_file():
            return []
        records: list[FeedbackRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            ft = str(item.get("feedback_type") or "")
            if feedback_type and ft != feedback_type:
                continue
            records.append(
                FeedbackRecord(
                    id=str(item.get("id") or ""),
                    feedback_type=ft,
                    session_id=str(item.get("session_id") or ""),
                    trace_id=str(item.get("trace_id") or ""),
                    measurement_id=item.get("measurement_id"),
                    content=str(item.get("content") or ""),
                    original_response=str(item.get("original_response") or ""),
                    user_request=str(item.get("user_request") or ""),
                    timestamp=str(item.get("timestamp") or ""),
                )
            )
            if len(records) >= MAX_FEEDBACK_RECORDS:
                break
        return records

    def export_as_goldens(self, output_path: Path) -> int:
        """Exporta registros confirmed como NDJSON compatível com datasets/goldens.

        question = pergunta original do operador (user_request)
        expected = resposta do agente que foi confirmada (original_response)
        """
        confirmed = self.list_records(feedback_type="confirmed")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with output_path.open("w", encoding="utf-8") as handle:
            for rec in confirmed:
                handle.write(
                    json.dumps(
                        {
                            "question": rec.user_request or rec.original_response,
                            "expected": rec.original_response,
                            "source": "terminal_feedback",
                            "feedback_id": rec.id,
                            "session_id": rec.session_id,
                            "trace_id": rec.trace_id,
                        },
                        ensure_ascii=True,
                    )
                    + "\n"
                )
                count += 1
        return count
