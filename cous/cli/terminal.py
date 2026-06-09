"""Interactive terminal loop."""

from __future__ import annotations

from cous.application.session import ConversationStore
from cous.cli import renderer
from cous.cli.commands import CommandContext, build_chat_summary, build_router
from cous.clients.base import ClientError
from cous.clients.knowledge import KnowledgeClient
from cous.clients.measurements import MeasurementsClient
from cous.clients.opentracy import OpenTracyClient
from cous.config import Config
from cous.logger import EventLogger


def run_terminal(
    config: Config,
    opentracy: OpenTracyClient,
    knowledge: KnowledgeClient,
    measurements: MeasurementsClient,
    conversations: ConversationStore,
    logger: EventLogger,
) -> None:
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
    measurement_context = ctx.measurements.chat_context(text)
    if measurement_context:
        request_text = (
            "Contexto local de medicoes salvas no terminal:\n"
            f"{measurement_context}\n\n"
            "Use esse contexto apenas se for relevante para responder ao pedido.\n"
            f"Pedido do operador: {text}"
        )
        renderer.info("Contexto local de medicoes anexado ao chat.")
    try:
        result = ctx.opentracy.chat(
            request_text,
            history=ctx.session.history_for_model(ctx.config.memory.max_history),
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
    trace_id = result.get("trace_id")
    if trace_id:
        renderer.info(f"trace_id={trace_id}")
    _maybe_refresh_summary(ctx)


def _maybe_refresh_summary(ctx: CommandContext) -> None:
    limit = ctx.config.memory.max_chars_before_summary
    if ctx.session.pending_summary_chars() <= limit:
        return
    try:
        summary = build_chat_summary(ctx)
    except ClientError as exc:
        _log(ctx, "summary_error", session_id=ctx.session.session_id, error=str(exc))
        renderer.warning(f"Resumo automatico falhou: {exc}")
        return
    ctx.session.set_summary(summary)
    _log(ctx, "summary_updated", session_id=ctx.session.session_id, automatic=True)
    renderer.info("Resumo automatico atualizado para a sessao atual.")


def _log(ctx: object, event: str, **payload: object) -> None:
    logger = getattr(ctx, "logger", None)
    if logger is not None:
        logger.log(event, **payload)
