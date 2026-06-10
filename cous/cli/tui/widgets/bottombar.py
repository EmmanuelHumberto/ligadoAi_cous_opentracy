"""Barra inferior com informações da sessão."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static


class BottomBar(Static):
    """Barra inferior fixa com session_id, modelo e tokens.

    Exibe: sess: a3f2b1c9  │  model: deepseek-chat  │  tokens: 1.2k
    Atualizada via update_info() após cada resposta do agente.
    """

    DEFAULT_CSS = """
    BottomBar {
        height: 1;
        background: #242528;
        border-top: solid #2E2F33;
        padding: 0 1;
        color: #666666;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._session_id = "-"
        self._model = "-"
        self._tokens = 0

    def compose(self) -> ComposeResult:
        pass  # Static render é suficiente

    def on_mount(self) -> None:
        self._refresh()

    def update_info(self, *, session_id: str = "", model: str = "", tokens: int = 0) -> None:
        """Atualiza as informações exibidas."""
        if session_id:
            self._session_id = session_id[:12]
        if model:
            self._model = model
        if tokens:
            self._tokens = tokens
        self._refresh()

    def _refresh(self) -> None:
        self.update(
            f" sess: {self._session_id}  │  "
            f"model: {self._model}  │  "
            f"tokens: {self._tokens}"
        )
