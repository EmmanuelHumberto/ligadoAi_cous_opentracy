"""Painel de chat com bolhas e barra de input."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Static


class ChatBubble(Static):
    """Bolha de mensagem no chat.

    Classes CSS: .bubble-operator (direita, azul), .bubble-agent (esquerda, borda),
    .bubble-system (cinza, itálico).
    """

    def __init__(self, text: str, *, role: str = "operator", trace_id: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._role = role
        self._trace_id = trace_id

    def on_mount(self) -> None:
        classes = {"operator": "bubble-operator", "agent": "bubble-agent", "system": "bubble-system"}
        self.add_class(classes.get(self._role, "bubble-system"))

        content = self._text
        if self._trace_id:
            content += f"\n[dim]trace: {self._trace_id}[/]"
        self.update(content)


class ChatScroll(VerticalScroll):
    """Scroll vertical de bolhas de chat."""

    DEFAULT_CSS = """
    ChatScroll {
        padding: 1 2;
    }
    """

    def add_bubble(self, text: str, *, role: str = "operator", trace_id: str = "") -> None:
        """Adiciona uma bolha de chat e faz scroll automático."""
        bubble = ChatBubble(text, role=role, trace_id=trace_id)
        self.mount(bubble)
        self.scroll_end(animate=False)


class InputBar(Static):
    """Barra de input com campo de texto e botão enviar."""

    DEFAULT_CSS = """
    InputBar {
        height: 3;
        padding: 0 2;
    }
    InputBar Input {
        border: solid #2E2F33;
        background: #1A1B1E;
        color: #C8C8C8;
    }
    InputBar Input:focus {
        border: solid #639922;
    }
    """

    def compose(self) -> ComposeResult:
        yield Input(placeholder="▸ Digite uma mensagem ou /comando...", id="chat-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Encaminha o texto para o App como UserInput."""
        if event.value.strip():
            self.post_message(self._user_input(event.value.strip()))
        event.input.clear()

    @staticmethod
    def _user_input(text: str) -> "UserInput":
        from cous.cli.tui.events import UserInput
        return UserInput(text)


class ChatPanel(Static):
    """Painel principal de chat — composto por ChatScroll + InputBar."""

    DEFAULT_CSS = """
    ChatPanel {
        width: 1fr;
        border-right: solid #2E2F33;
    }
    .bubble-operator {
        background: #1A3A5C;
        color: #90C8F0;
        padding: 0 1;
    }
    .bubble-agent {
        background: #242528;
        border: solid #2E2F33;
        padding: 0 1;
        color: #C8C8C8;
    }
    .bubble-system {
        color: #888888;
        text-style: italic;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield ChatScroll(id="chat-scroll")
        yield InputBar(id="input-bar")
