"""Testes unitários para AppState e ComponentStatus."""

import pytest

from cous.cli.tui.state import AppState, ComponentStatus


class TestComponentStatus:
    def test_default_state_is_unknown(self):
        cs = ComponentStatus("runtime")
        assert cs.state == "unknown"
        assert cs.name == "runtime"
        assert cs.detail == "-"

    def test_ok_dot(self):
        cs = ComponentStatus("backend", "ok")
        assert "[#639922]" in cs.dot

    def test_warn_dot(self):
        cs = ComponentStatus("runtime", "warn")
        assert "[#EF9F27]" in cs.dot

    def test_down_dot(self):
        cs = ComponentStatus("knowledge", "down")
        assert "[#E24B4A]" in cs.dot

    def test_unknown_dot(self):
        cs = ComponentStatus("measurements", "unknown")
        assert "[#555]" in cs.dot


class TestAppState:
    def test_default_agent_id_empty(self):
        state = AppState()
        assert state.agent_id == ""

    def test_custom_agent_id(self):
        state = AppState(agent_id="cous-test")
        assert state.agent_id == "cous-test"

    def test_default_components_are_unknown(self):
        state = AppState()
        assert state.backend.state == "unknown"
        assert state.runtime.state == "unknown"
        assert state.knowledge.state == "unknown"
        assert state.measurements.state == "unknown"

    def test_default_trace_fields(self):
        state = AppState()
        assert state.last_trace_id == ""
        assert state.last_stages == []
        assert state.model_name == ""
        assert state.token_count == 0
        assert not state.is_thinking

    def test_mutable_fields(self):
        state = AppState()
        state.last_trace_id = "trace-abc"
        state.model_name = "deepseek-chat"
        state.token_count = 1234
        state.is_thinking = True
        assert state.last_trace_id == "trace-abc"
        assert state.model_name == "deepseek-chat"
        assert state.token_count == 1234
        assert state.is_thinking

    def test_session_id(self):
        state = AppState(session_id="sess123")
        assert state.session_id == "sess123"

    def test_tui_mode_default(self):
        state = AppState()
        assert state.tui_mode is True
