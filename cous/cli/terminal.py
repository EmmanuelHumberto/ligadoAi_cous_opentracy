"""Interactive terminal loop."""

from __future__ import annotations

from cous.application.session import ConversationStore
from cous.cli import renderer
from cous.cli.commands import CommandContext, build_chat_summary, build_router
from cous.cli.tui.output_router import NullOutputRouter
from cous.clients.base import ClientError
from cous.clients.knowledge import KnowledgeClient
from cous.clients.measurements import MeasurementsClient
from cous.clients.opentracy import OpenTracyClient
from cous.config import Config
from cous.logger import EventLogger, TraceEmitter


def run_terminal(
    config: Config,
    opentracy: OpenTracyClient,
    knowledge: KnowledgeClient,
    measurements: MeasurementsClient,
    conversations: ConversationStore,
    logger: EventLogger,
    *,
    feedback_store: object = None,
    system_prompt_cache: object = None,
    trace_emitter: TraceEmitter | None = None,
) -> None:
    """Detecta se o terminal suporta TUI e escolhe o modo.

    Modo TUI (Textual): ativado quando o terminal é interativo (TTY),
    a flag COUS_NO_TUI não está setada, e config.tui.enabled == True.
    Modo legado: fallback para pipes, CI, ou --no-tui explícito.
    """
    if _should_use_tui(config):
        _run_tui(
            config, opentracy, knowledge, measurements, conversations, logger,
            feedback_store=feedback_store,
            system_prompt_cache=system_prompt_cache,
            trace_emitter=trace_emitter,
        )
    else:
        _run_legacy(
            config, opentracy, knowledge, measurements, conversations, logger,
            feedback_store=feedback_store,
            system_prompt_cache=system_prompt_cache,
            trace_emitter=trace_emitter,
        )


def _should_use_tui(config: Config) -> bool:
    """Decide se o modo TUI deve ser ativado."""
    import os
    import sys

    if os.environ.get("COUS_NO_TUI"):
        return False
    if not sys.stdout.isatty():
        return False
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return getattr(config, "tui", None) and config.tui.enabled


def _run_tui(
    config: Config,
    opentracy: OpenTracyClient,
    knowledge: KnowledgeClient,
    measurements: MeasurementsClient,
    conversations: ConversationStore,
    logger: EventLogger,
    *,
    feedback_store: object = None,
    system_prompt_cache: object = None,
    trace_emitter: TraceEmitter | None = None,
) -> None:
    """Inicia o modo TUI com Textual."""
    from cous.cli.tui.app import CousApp

    app = CousApp(
        config=config,
        opentracy=opentracy,
        knowledge=knowledge,
        measurements=measurements,
        conversations=conversations,
        event_logger=logger,
        feedback_store=feedback_store,
        system_prompt_cache=system_prompt_cache,
        trace_emitter=trace_emitter,
    )
    app.run()


def _run_legacy(
    config: Config,
    opentracy: OpenTracyClient,
    knowledge: KnowledgeClient,
    measurements: MeasurementsClient,
    conversations: ConversationStore,
    logger: EventLogger,
    *,
    feedback_store: object = None,
    system_prompt_cache: object = None,
    trace_emitter: TraceEmitter | None = None,
) -> None:
    """Loop legado — idêntico ao comportamento atual."""
    session = conversations.latest_session() or conversations.create_session()
    router = build_router()
    ctx = CommandContext(
        config=config,
        opentracy=opentracy,
        knowledge=knowledge,
        measurements=measurements,
        conversations=conversations,
        session=session,
        logger=logger,
        feedback_store=feedback_store,
        system_prompt_cache=system_prompt_cache,
        trace_emitter=trace_emitter,
        output_router=NullOutputRouter(),
    )
    renderer.welcome(config.opentracy.agent_id)
    renderer.info(f"Sessao de chat atual: {session.session_id}")
    _log(ctx, "terminal_ready", session_id=session.session_id)

    while True:
        text = renderer.prompt().strip()
        if not text:
            continue
        _log(ctx, "input_received", session_id=ctx.session.session_id, is_command=text.startswith("/"))
        command_result = router.dispatch(text, ctx)
        if command_result is False:
            _log(ctx, "terminal_exit", session_id=ctx.session.session_id)
            break
        if command_result is True:
            continue
        _send_chat(text, ctx)


def _send_chat(text: str, ctx: CommandContext) -> None:
    ctx.session.add("user", text)
    _log(ctx, "chat_user", session_id=ctx.session.session_id, text=text)
    request_text = text
    # System prompt via HistoryMessage (workaround — RunRequest não tem campo system)
    history = ctx.session.history_for_model(ctx.config.memory.max_history)
    if ctx.system_prompt_cache is not None:
        system_prompt = ctx.system_prompt_cache.get()
        history.insert(0, {"role": "system", "content": system_prompt})
    try:
        result = ctx.opentracy.chat(
            request_text,
            history=history,
            session_id=ctx.session.session_id,
        )
    except ClientError as exc:
        _log(ctx, "chat_error", session_id=ctx.session.session_id, error=str(exc))
        renderer.error(str(exc))
        return
    response = str(result.get("response") or "")
    ctx.session.add("assistant", response)
    _log(
        ctx,
        "chat_assistant",
        session_id=ctx.session.session_id,
        trace_id=result.get("trace_id"),
        text=response,
    )
    renderer.assistant(response)
    trace_id = str(result.get("trace_id") or "")
    if trace_id:
        ctx.last_trace_id = trace_id
        renderer.info(f"trace_id={trace_id}")
    # Emitir trace compatível com OpenTracy
    if ctx.trace_emitter is not None:
        ctx.trace_emitter.emit_chat(
            trace_id=trace_id,
            session_id=ctx.session.session_id,
            channel="terminal",
            request=text,
            response=response,
            duration_ms=int(result.get("duration_ms") or 0),
            agent_version=str(result.get("agent_version") or ""),
            stages=result.get("stages"),
        )
    _maybe_refresh_summary(ctx)


def _maybe_refresh_summary(ctx: CommandContext) -> None:
    limit = ctx.config.memory.max_chars_before_summary
    if ctx.session.pending_summary_chars() <= limit:
        return
    try:
        summary = build_chat_summary(ctx)
        ctx.session.set_summary(summary)
        _log(ctx, "summary_updated", session_id=ctx.session.session_id, automatic=True)
        renderer.info("Resumo automatico atualizado para a sessao atual.")
    except ClientError as exc:
        _log(
            ctx,
            "summary_error",
            session_id=ctx.session.session_id,
            error=str(exc),
            fallback="local_truncation",
        )
        _apply_local_summary_fallback(ctx)
        renderer.warning(
            f"Resumo automatico remoto falhou ({exc}). "
            "Resumo local aplicado — use /resumo para tentar novamente."
        )


def _apply_local_summary_fallback(ctx: CommandContext) -> None:
    """
    Fallback de resumo local: preserva as primeiras ~80 palavras de cada
    mensagem antiga em vez de descartar tudo. Mantém as últimas
    max_history mensagens intactas.
    """
    keep = ctx.config.memory.max_history
    total = len(ctx.session.history)
    compressed_count = max(0, total - keep)
    if compressed_count == 0:
        return

    # Limites para evitar que o próprio resumo seja grande demais
    MAX_MESSAGES_IN_FALLBACK = 20
    MAX_CHARS_IN_FALLBACK = 4000

    # Extrai as mensagens que serão comprimidas (todas exceto as últimas `keep`)
    compressed = ctx.session.history[:compressed_count]
    truncated_lines = []
    total_chars = 0

    for msg in compressed[-MAX_MESSAGES_IN_FALLBACK:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        words = content.split()
        truncated = " ".join(words[:80])
        if len(words) > 80:
            truncated += " [...]"
        line = f"[{role}] {truncated}"
        if total_chars + len(line) > MAX_CHARS_IN_FALLBACK and truncated_lines:
            truncated_lines.append("[...]")
            break
        truncated_lines.append(line)
        total_chars += len(line)

    summary = (
        f"[Resumo local — {compressed_count} mensagens anteriores comprimidas. "
        "Execute /resumo para um resumo completo gerado pelo agente.]\n\n"
        + "\n".join(truncated_lines)
    )
    ctx.session.set_summary(summary)


def _log(ctx: object, event: str, **payload: object) -> None:
    logger = getattr(ctx, "logger", None)
    if logger is not None:
        logger.log(event, **payload)
