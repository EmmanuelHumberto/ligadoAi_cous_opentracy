"""Sidebar — painel lateral com info.

Layout:
  ┌─ INFO ───┐  — DataTable + RichLog
  └──────────┘
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, RichLog


class Sidebar(Container):
    """Painel lateral direito: info (DataTable ou RichLog)."""

    DEFAULT_CSS = """
    Sidebar {
        width: 35%;
        background: #1E1F22;
        border: solid #3A3D41;
        border-title-color: #82AAFF;
        border-title-background: #1E1F22;
        border-title-style: bold;
        border-title-align: center;
        padding: 0;
    }
    #info-table {
        height: 1fr;
        scrollbar-size: 1 1;
    }
    #info-log {
        height: 1fr;
        scrollbar-size: 1 1;
        color: #B0B0B0;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        self.border_title = " ℹ INFO "
        yield DataTable(id="info-table")
        yield RichLog(id="info-log", highlight=False, markup=True, wrap=True, max_lines=30)
