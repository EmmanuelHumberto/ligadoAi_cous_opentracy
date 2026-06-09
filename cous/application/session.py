"""Persistent local chat session store."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatSession:
    session_id: str
    history: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    summarized_until: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    _store: ConversationStore | None = field(default=None, repr=False)

    def add(self, role: str, content: str) -> None:
        message = {"role": role, "content": content}
        self.history.append(message)
        self.updated_at = utc_now_iso()
        if self._store is not None:
            self._store.append_message(self.session_id, role, content, self.updated_at)

    def recent(self, limit: int) -> list[dict[str, str]]:
        start = max(self.summarized_until, len(self.history) - limit)
        return self.history[start:]

    def history_for_model(self, limit: int) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if self.summary:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Resumo persistido da conversa ate aqui. "
                        "Use como contexto comprimido:\n"
                        f"{self.summary}"
                    ),
                }
            )
        messages.extend(self.recent(limit))
        return messages

    def pending_summary_chars(self) -> int:
        return sum(len(item.get("content", "")) for item in self.history[self.summarized_until :])

    def set_summary(self, summary: str) -> None:
        self.summary = summary.strip()
        self.summarized_until = len(self.history)
        self.updated_at = utc_now_iso()
        if self._store is not None:
            self._store.append_summary(
                self.session_id,
                self.summary,
                self.summarized_until,
                self.updated_at,
            )

    def clear(self) -> None:
        self.history.clear()
        self.summary = ""
        self.summarized_until = 0
        self.updated_at = utc_now_iso()
        if self._store is not None:
            self._store.reset_session(self.session_id, self.updated_at)


class ConversationStore:
    def __init__(self, conversations_dir: Path) -> None:
        self._conversations_dir = conversations_dir

    def create_session(self, session_id: str | None = None) -> ChatSession:
        session_id = session_id or self._generate_session_id()
        session = ChatSession(session_id=session_id, _store=self)
        self._append_event(
            session_id,
            {
                "type": "meta",
                "session_id": session_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            },
        )
        return session

    def load_session(self, session_id: str, *, event_logger=None) -> ChatSession:
        """
        Carrega sessão do disco. Linhas JSONL inválidas são puladas com log.

        Args:
            session_id: ID ou prefixo da sessão.
            event_logger: EventLogger opcional para registrar linhas corrompidas.
                          Chamadas internas (ex: list_sessions) passam None.
        """
        resolved = session_id
        path = self._session_path(resolved)
        if not path.is_file():
            resolved = self.resolve_session_id(session_id) or session_id
            path = self._session_path(resolved)
        if not path.is_file():
            raise ValueError(f"Sessao de chat nao encontrada: {session_id}")
        history: list[dict[str, str]] = []
        summary = ""
        summarized_until = 0
        created_at = ""
        updated_at = ""
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                if event_logger is not None:
                    event_logger.log(
                        "jsonl_parse_error",
                        session_id=resolved,
                        line=line_number,
                        error=str(exc),
                    )
                continue
            event_type = str(item.get("type") or "")
            if event_type == "meta":
                created_at = str(item.get("created_at") or created_at or utc_now_iso())
                updated_at = str(item.get("updated_at") or updated_at or created_at)
            elif event_type == "message":
                history.append(
                    {
                        "role": str(item.get("role") or ""),
                        "content": str(item.get("content") or ""),
                    }
                )
                updated_at = str(item.get("timestamp") or updated_at or utc_now_iso())
            elif event_type == "summary":
                summary = str(item.get("summary") or "")
                summarized_until = int(item.get("summarized_until") or len(history))
                updated_at = str(item.get("timestamp") or updated_at or utc_now_iso())
            elif event_type == "reset":
                history = []
                summary = ""
                summarized_until = 0
                updated_at = str(item.get("timestamp") or updated_at or utc_now_iso())
        if not created_at:
            created_at = updated_at or utc_now_iso()
        return ChatSession(
            session_id=resolved,
            history=history,
            summary=summary,
            summarized_until=min(summarized_until, len(history)),
            created_at=created_at,
            updated_at=updated_at or created_at,
            _store=self,
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        self._conversations_dir.mkdir(parents=True, exist_ok=True)
        sessions: list[dict[str, Any]] = []
        for path in sorted(self._conversations_dir.glob("*.jsonl")):
            try:
                session = self.load_session(path.stem)
            except ValueError:
                continue
            preview = ""
            if session.history:
                preview = session.history[-1].get("content", "")[:60]
            sessions.append(
                {
                    "id": session.session_id,
                    "messages": len(session.history),
                    "summary_present": bool(session.summary),
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "preview": preview,
                }
            )
        sessions.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return sessions

    def latest_session(self) -> ChatSession | None:
        sessions = self.list_sessions()
        if not sessions:
            return None
        return self.load_session(str(sessions[0]["id"]))

    def resolve_session_id(self, value: str) -> str | None:
        target = value.strip()
        if not target:
            return None
        sessions = self.list_sessions()
        exact = [item for item in sessions if str(item["id"]) == target]
        if exact:
            return str(exact[0]["id"])
        prefix = [item for item in sessions if str(item["id"]).startswith(target)]
        if len(prefix) == 1:
            return str(prefix[0]["id"])
        return None

    def append_message(self, session_id: str, role: str, content: str, timestamp: str) -> None:
        self._append_event(
            session_id,
            {
                "type": "message",
                "session_id": session_id,
                "role": role,
                "content": content,
                "timestamp": timestamp,
            },
        )

    def append_summary(
        self,
        session_id: str,
        summary: str,
        summarized_until: int,
        timestamp: str,
    ) -> None:
        self._append_event(
            session_id,
            {
                "type": "summary",
                "session_id": session_id,
                "summary": summary,
                "summarized_until": summarized_until,
                "timestamp": timestamp,
            },
        )

    def delete_session(self, session_id: str) -> bool:
        """
        Remove permanentemente o arquivo JSONL da sessão.
        Retorna True se deletado, False se não encontrado.
        Usa match exato — para resolução de prefixo com detecção de
        ambiguidade, use resolve_unique() antes.
        """
        path = self._session_path(session_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    def resolve_unique(self, value: str) -> str:
        """
        Resolve prefixo para ID exato. Levanta ValueError se:
        - prefixo ambíguo (bate em múltiplas sessões)
        - não encontrado
        Use em operações destrutivas (delete) que exigem identificação única.
        """
        target = value.strip()
        if not target:
            raise ValueError("ID vazio.")
        sessions = self.list_sessions()
        exact = [s for s in sessions if str(s["id"]) == target]
        if exact:
            return str(exact[0]["id"])
        prefix = [s for s in sessions if str(s["id"]).startswith(target)]
        if len(prefix) == 1:
            return str(prefix[0]["id"])
        if len(prefix) > 1:
            ids = ", ".join(str(s["id"])[:20] for s in prefix[:5])
            raise ValueError(
                f"Prefixo ambiguo: {len(prefix)} sessoes encontradas ({ids}...). "
                "Use um prefixo mais especifico."
            )
        raise ValueError(f"Sessao nao encontrada: {target}")

    def reset_session(self, session_id: str, timestamp: str) -> None:
        self._append_event(
            session_id,
            {
                "type": "reset",
                "session_id": session_id,
                "timestamp": timestamp,
            },
        )

    def _append_event(self, session_id: str, event: dict[str, Any]) -> None:
        path = self._session_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    def _session_path(self, session_id: str) -> Path:
        return self._conversations_dir / f"{session_id}.jsonl"

    def _generate_session_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("chat_%Y%m%d_%H%M%S")
        return f"{stamp}_{uuid4().hex[:6]}"
