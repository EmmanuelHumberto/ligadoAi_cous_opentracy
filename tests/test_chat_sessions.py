from pathlib import Path
from types import SimpleNamespace

from cous.application.session import ConversationStore
from cous.cli.commands import build_chat_summary, build_router
from cous.cli.terminal import _maybe_refresh_summary


def test_conversation_store_persists_and_loads_sessions(tmp_path):
    store = ConversationStore(tmp_path / "conversations")
    session = store.create_session("chat_test")

    session.add("user", "ola")
    session.add("assistant", "resposta")
    session.set_summary("resumo tecnico")

    loaded = store.load_session("chat_test")
    sessions = store.list_sessions()

    assert loaded.session_id == "chat_test"
    assert len(loaded.history) == 2
    assert loaded.summary == "resumo tecnico"
    assert sessions[0]["id"] == "chat_test"
    assert sessions[0]["summary_present"] is True


def test_conversation_store_resolves_prefix_and_latest(tmp_path):
    store = ConversationStore(tmp_path / "conversations")
    first = store.create_session("chat_aaa111")
    second = store.create_session("chat_bbb222")
    first.add("user", "primeira")
    second.add("user", "segunda")

    assert store.resolve_session_id("chat_bbb") == "chat_bbb222"
    assert store.latest_session().session_id == "chat_bbb222"


def test_build_chat_summary_uses_agent_response():
    class FakeOpenTracy:
        def chat(self, request, *, history=None, channel="terminal"):
            assert "Resuma a conversa" in request
            assert channel == "terminal_summary"
            assert history == [{"role": "user", "content": "erro na coleta"}]
            return {"response": "Resumo objetivo"}

    ctx = SimpleNamespace(
        opentracy=FakeOpenTracy(),
        session=SimpleNamespace(history=[{"role": "user", "content": "erro na coleta"}]),
    )

    assert build_chat_summary(ctx) == "Resumo objetivo"


def test_auto_summary_updates_session_when_threshold_is_reached(tmp_path):
    class FakeOpenTracy:
        def chat(self, request, *, history=None, channel="terminal"):
            return {"response": "Resumo automatico"}

    store = ConversationStore(tmp_path / "conversations")
    session = store.create_session("chat_summary")
    session.add("user", "x" * 50)
    session.add("assistant", "y" * 50)

    ctx = SimpleNamespace(
        config=SimpleNamespace(memory=SimpleNamespace(max_chars_before_summary=20)),
        opentracy=FakeOpenTracy(),
        session=session,
    )

    _maybe_refresh_summary(ctx)

    loaded = store.load_session("chat_summary")
    assert loaded.summary == "Resumo automatico"
    assert loaded.summarized_until == 2


def test_load_session_tolerates_corrupted_line(tmp_path):
    """Sessão com uma linha corrompida deve carregar o restante das mensagens."""
    store = ConversationStore(tmp_path)
    session = store.create_session()
    session.add("user", "mensagem válida")

    # Injeta linha corrompida diretamente no arquivo
    path = tmp_path / f"{session.session_id}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write("LINHA_INVALIDA_NAO_JSON\n")

    session.add("user", "mensagem após corrupção")

    loaded = store.load_session(session.session_id)
    # Deve ter 2 mensagens (não 0 ou erro)
    assert len(loaded.history) == 2


def test_load_session_skips_all_corrupted_lines(tmp_path):
    """Arquivo completamente corrompido retorna sessão vazia sem lançar exceção."""
    store = ConversationStore(tmp_path)
    session_id = "chat_20260101_000000_abc123"
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text(
        '{"type":"meta","session_id":"chat_20260101_000000_abc123",'
        '"created_at":"2026-01-01T00:00:00+00:00","updated_at":"2026-01-01T00:00:00+00:00"}\n'
        "INVALIDO\nOUTRO_INVALIDO\n"
    )
    loaded = store.load_session(session_id)
    assert loaded.history == []


def test_delete_session_removes_file(tmp_path):
    store = ConversationStore(tmp_path)
    session = store.create_session()
    session_id = session.session_id

    assert (tmp_path / f"{session_id}.jsonl").is_file()
    assert store.delete_session(session_id) is True
    assert not (tmp_path / f"{session_id}.jsonl").is_file()


def test_delete_session_returns_false_if_not_found(tmp_path):
    store = ConversationStore(tmp_path)

    assert store.delete_session("nao_existe") is False


def test_delete_session_via_resolve_unique_then_delete(tmp_path):
    store = ConversationStore(tmp_path)
    session = store.create_session()
    prefix = session.session_id[:12]

    resolved = store.resolve_unique(prefix)
    deleted = store.delete_session(resolved)

    assert deleted is True
    assert not (tmp_path / f"{session.session_id}.jsonl").is_file()


def test_export_command_writes_markdown_for_current_session(tmp_path, monkeypatch, make_context):
    monkeypatch.chdir(tmp_path)
    router = build_router()
    ctx = make_context()
    ctx.session.add("user", "ola")
    ctx.session.add("assistant", "resposta")
    ctx.session.set_summary("resumo tecnico")

    result = router.dispatch("/exportar", ctx=ctx)

    output = Path(".cous-data/exports") / f"{ctx.session.session_id}.md"
    content = output.read_text(encoding="utf-8")
    assert result is True
    assert output.is_file()
    assert "# Sessão de Chat" in content
    assert "## Resumo" in content
    assert "## Histórico" in content
    assert "ola" in content


def test_delete_chat_command_removes_non_active_session(tmp_path, monkeypatch, make_context):
    router = build_router()
    ctx = make_context()
    other = ctx.conversations.create_session()
    monkeypatch.setattr("builtins.input", lambda: "s")

    result = router.dispatch(f"/deletar_chat {other.session_id}", ctx=ctx)

    assert result is True
    assert ctx.conversations.resolve_session_id(other.session_id) is None
