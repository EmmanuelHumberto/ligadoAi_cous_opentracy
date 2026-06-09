"""Interactive terminal loop."""

from __future__ import annotations

from cous.application.session import ChatSession
from cous.cli import renderer
from cous.cli.commands import CommandContext, build_router
from cous.clients.base import ClientError
from cous.clients.knowledge import KnowledgeClient
from cous.clients.measurements import MeasurementsClient
from cous.clients.opentracy import OpenTracyClient
from cous.config import Config


def run_terminal(
    config: Config,
    opentracy: OpenTracyClient,
    knowledge: KnowledgeClient,
    measurements: MeasurementsClient,
) -> None:
    session = ChatSession()
    router = build_router()
    ctx = CommandContext(
        config=config,
        opentracy=opentracy,
        knowledge=knowledge,
        measurements=measurements,
        session=session,
    )
    renderer.welcome(config.opentracy.agent_id)

    while True:
        text = renderer.prompt().strip()
        if not text:
            continue
        command_result = router.dispatch(text, ctx)
        if command_result is False:
            break
        if command_result is True:
            continue
        _send_chat(text, ctx)


def _send_chat(text: str, ctx: CommandContext) -> None:
    ctx.session.add("user", text)
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
            history=ctx.session.recent(ctx.config.memory.max_history),
        )
    except ClientError as exc:
        renderer.error(str(exc))
        return
    response = str(result.get("response") or "")
    ctx.session.add("assistant", response)
    renderer.assistant(response)
    trace_id = result.get("trace_id")
    if trace_id:
        renderer.info(f"trace_id={trace_id}")
