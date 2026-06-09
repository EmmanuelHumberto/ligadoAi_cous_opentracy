"""Small local chat session store."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChatSession:
    history: list[dict[str, str]] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def recent(self, limit: int) -> list[dict[str, str]]:
        return self.history[-limit:]

    def clear(self) -> None:
        self.history.clear()
