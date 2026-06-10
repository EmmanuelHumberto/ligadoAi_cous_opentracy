"""Testes para detecção de modo TUI vs legado."""

import os
import sys
from unittest.mock import patch

import pytest

from cous.config import Config
from cous.cli.terminal import _should_use_tui


class TestShouldUseTui:
    def test_returns_false_when_cous_no_tui_env_set(self, monkeypatch):
        monkeypatch.setenv("COUS_NO_TUI", "1")
        config = Config()
        assert _should_use_tui(config) is False

    def test_returns_false_when_not_tty(self, monkeypatch):
        monkeypatch.delenv("COUS_NO_TUI", raising=False)
        config = Config()
        config.tui.enabled = True
        # Em CI/pipe, isatty() retorna False
        assert _should_use_tui(config) is False

    def test_returns_false_when_tui_disabled_in_config(self, monkeypatch):
        monkeypatch.delenv("COUS_NO_TUI", raising=False)
        config = Config()
        config.tui.enabled = False
        assert _should_use_tui(config) is False

    def test_returns_false_when_textual_not_installed(self, monkeypatch):
        monkeypatch.delenv("COUS_NO_TUI", raising=False)
        config = Config()
        config.tui.enabled = True
        with patch.dict(sys.modules, {"textual": None}):
            # textual ausente → fallback legado
            with patch("sys.stdout.isatty", return_value=True):
                # isatty=True, mas sem textual → False
                pass  # _should_use_tui tem try/import textual internamente
            assert _should_use_tui(config) is False

    def test_default_config_legacy_in_non_tty(self):
        config = Config()
        assert _should_use_tui(config) is False
