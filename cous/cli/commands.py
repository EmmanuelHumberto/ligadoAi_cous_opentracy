"""Command router for the Cous terminal."""

from __future__ import annotations

import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cous.application.session import ChatSession, ConversationStore
from cous.cli import renderer
from cous.cli.tui.events import TableData
from cous.cli.tui.output_router import NullOutputRouter
from cous.clients.base import ClientError
from cous.clients.knowledge import KnowledgeClient
from cous.clients.measurements import MeasurementsClient
from cous.clients.opentracy import OpenTracyClient
from cous.config import Config
from cous.logger import EventLogger
from cous.measurements.constants import DEFAULT_VERTICALS
from cous.measurements.diagnosis import diagnosis_summary_rows
from cous.measurements.serial_capture import (
    capture_tma_snapshots,
    normalize_snapshot_type,
    normalize_verticals,
)

CommandHandler = Callable[["CommandContext", str], bool]
SUPPORTED_INDEX_EXTENSIONS = {".md", ".txt", ".docx"}


def _route_msg(ctx: CommandContext, method: str, text: str) -> None:
    """Roteia mensagem de texto para output_router (TUI) ou renderer (legado)."""
    if ctx.output_router:
        getattr(ctx.output_router, method)(text)
    else:
        getattr(renderer, method)(text)


@dataclass
class CommandContext:
    config: Config
    opentracy: OpenTracyClient
    knowledge: KnowledgeClient
    measurements: MeasurementsClient
    conversations: ConversationStore
    session: ChatSession
    logger: EventLogger
    feedback_store: FeedbackStore | None = None
    system_prompt_cache: SystemPromptCache | None = None
    trace_emitter: TraceEmitter | None = None
    last_trace_id: str = ""  # trace_id da última resposta
    output_router: "OutputRouter | NullOutputRouter | None" = None  # populado no TUI em on_mount()
    send_to_chat: "Callable[[str], None] | None" = None  # callback para enviar prompt ao fluxo de chat normal
    post_assistant: "Callable[[str], None] | None" = None  # callback para exibir mensagem do assistente diretamente (sem LLM)


class CommandRouter:
    def __init__(self) -> None:
        self._commands: dict[str, tuple[CommandHandler, str]] = {}

    def register(
        self,
        name: str,
        handler: CommandHandler,
        description: str,
        *,
        aliases: list[str] | None = None,
    ) -> None:
        self._commands[name] = (handler, description)
        for alias in aliases or []:
            self._commands[alias] = (handler, f"Atalho de /{name}")

    def dispatch(self, text: str, ctx: CommandContext) -> bool | None:
        if not text.startswith("/"):
            return None
        parts = text[1:].strip().split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        entry = self._commands.get(command)
        if entry is None:
            if hasattr(ctx, "logger"):
                ctx.logger.log("command_unknown", session_id=ctx.session.session_id, command=command)
            _route_msg(ctx, "error", f"Comando desconhecido: /{command}")
            _route_msg(ctx, "info", "Digite /ajuda para ver os comandos disponiveis.")
            return True
        handler, _ = entry
        if hasattr(ctx, "logger"):
            ctx.logger.log("command_dispatch", session_id=ctx.session.session_id, command=command, args=args)
        return handler(ctx, args)

    def descriptions(self) -> list[tuple[str, str]]:
        return [(f"/{name}", desc) for name, (_, desc) in sorted(self._commands.items())]


def build_router() -> CommandRouter:
    router = CommandRouter()
    router.register("ajuda", _help, "Mostra comandos", aliases=["h"])
    router.register("sair", _exit, "Encerra o programa", aliases=["q", "exit"])
    router.register("limpar", _clear, "Limpa a tela", aliases=["cls"])
    router.register("status", _status, "Mostra status do OpenTracy", aliases=["st"])
    router.register("tools", _tools, "Lista MCP tools do agente")
    router.register("validar", _validate, "Valida arquivo ou pasta sem indexar")
    router.register("indexar", _index, "Indexa arquivo ou pasta via OpenTracy")
    router.register("indexados", _documents, "Lista documentos indexados")
    router.register("buscar", _search, "Busca na base de conhecimento")
    router.register("remover", _delete, "Remove documento do indice")
    router.register("medicoes", _measurements, "Lista sessoes de medicao", aliases=["m"])
    router.register("medicao", _measurement, "Mostra detalhes de uma medicao", aliases=["md"])
    router.register(
        "diagnostico",
        _measurement_diagnostic,
        "Enfileira diagnostico no OpenTracy",
        aliases=["dg"],
    )
    router.register("comparar", _measurement_compare, "Compara duas medicoes e gera laudo comparativo", aliases=["cmp"])
    router.register("laudo", _measurement_report, "Gera laudo de uma medicao", aliases=["ld"])
    router.register("capturar", _capture, "Cria sessao de medicao/coleta", aliases=["cp"])
    router.register("sincronizar", _sync_measurements, "Sincroniza medicoes com o runtime", aliases=["sync"])
    router.register("deletar_medicao", _delete_measurement, "Remove sessoes de medicao (local + remoto)", aliases=["dm"])
    router.register("novo", _new_session, "Cria nova sessao de chat", aliases=["n"])
    router.register("memoria", _memory, "Mostra memoria local")
    router.register("resumo", _summary_chat, "Resume a sessao de chat atual")
    router.register("carregar", _load_chat_session, "Carrega sessao de chat por id", aliases=["cg"])
    router.register("listar", _list_chat_sessions, "Lista sessoes de chat", aliases=["ls"])
    router.register("deletar_chat", _delete_chat_session, "Remove permanentemente uma sessao de chat do disco")
    router.register("exportar", _export_chat_session, "Exporta uma sessao de chat como arquivo Markdown")
    router.register("confirmar", _confirm_feedback, "Confirma que a ultima resposta esta correta")
    router.register("corrigir", _correct_feedback, "Registra correcao para a ultima resposta")
    router.register("solucao", _solution_feedback, "Registra solucao aplicada apos diagnostico")
    return router


def _help(ctx: CommandContext, args: str) -> bool:
    _GROUPS = [
        ("Gerais",    "#C8C8C8", ["/ajuda", "/sair", "/limpar", "/status", "/tools"]),
        ("Chat",      "#82AAFF", ["/novo", "/listar", "/carregar", "/memoria",
                                   "/resumo", "/deletar_chat", "/exportar"]),
        ("Feedback",  "#FFB86C", ["/confirmar", "/corrigir", "/solucao"]),
        ("Knowledge", "#639922", ["/validar", "/indexar", "/indexados", "/buscar", "/remover"]),
        ("Medições",  "#56B6C2", ["/capturar", "/medicoes", "/medicao",
                                   "/sincronizar", "/deletar_medicao", "/diagnostico",
                                   "/comparar", "/laudo"]),
    ]
    router = build_router()
    cmd_desc = dict(router.descriptions())

    rows = []
    for label, color, cmds in _GROUPS:
        for cmd in sorted(cmds):
            desc = cmd_desc.get(cmd, "")
            if desc.startswith("Atalho de"):
                continue
            rows.append([f"[bold {color}]{cmd}[/]", f"[dim]{desc}[/]"])

    if ctx.output_router:
        ctx.output_router._post(TableData(["Comando", "Descrição"], rows))
    return True


def _exit(ctx: CommandContext, args: str) -> bool:
    return False


def _clear(ctx: CommandContext, args: str) -> bool:
    if ctx.output_router:
        ctx.output_router.clear()
    else:
        renderer.console.clear()
    return True


def _status(ctx: CommandContext, args: str) -> bool:
    health = ctx.opentracy.health()
    knowledge_state = "indisponivel"
    knowledge_detail = "-"
    measurements_state = "indisponivel"
    measurements_detail = "-"
    diagnosis_state = "indisponivel"
    diagnosis_detail = "-"
    try:
        knowledge = ctx.knowledge.status()
        knowledge_state = "ok"
        knowledge_detail = (
            f"status={knowledge.get('status')} "
            f"docs={knowledge.get('document_count', 0)} "
            f"chunks={knowledge.get('chunk_count', 0)}"
        )
    except ClientError as exc:
        knowledge_detail = str(exc)
        if exc.status_code in {401, 403}:
            knowledge_state = "auth_falhou"
    try:
        measurements = ctx.measurements.status()
        measurements_state = "ok" if measurements.get("enabled") else "desabilitado"
        measurements_detail = (
            f"backend={measurements.get('backend')} "
            f"db={'sim' if measurements.get('database_configured') else 'nao'} "
            f"auth={'sim' if measurements.get('auth_configured') else 'nao'}"
        )
    except ClientError as exc:
        measurements_detail = str(exc)
        if exc.status_code in {401, 403}:
            measurements_state = "auth_falhou"
    try:
        diagnosis = ctx.measurements.diagnosis_runtime_status()
        status = str(diagnosis.get("status") or "unknown")
        diagnosis_state = "ok" if status in {"available", "mock"} else status
        diagnosis_detail = (
            f"db={'sim' if diagnosis.get('database_configured') else 'nao'} "
            f"worker={'sim' if diagnosis.get('worker_enabled') else 'nao'} "
            f"running={'sim' if diagnosis.get('worker_running') else 'nao'}"
        )
    except (ClientError, AttributeError) as exc:
        diagnosis_detail = str(exc)
        if isinstance(exc, ClientError) and exc.status_code in {401, 403}:
            diagnosis_state = "auth_falhou"
    rows = [
        ("OpenTracy backend", "ok" if health["backend"] else "offline", "-"),
        ("OpenTracy runtime", "ok" if health["runtime"] else "offline", "-"),
        ("Knowledge API", knowledge_state, knowledge_detail),
        ("Measurements API", measurements_state, measurements_detail),
        ("Diagnosis API", diagnosis_state, diagnosis_detail),
    ]
    if ctx.output_router:
        ctx.output_router.status_table(rows)
    else:
        renderer.status_table(rows)
    return True


def _tools(ctx: CommandContext, args: str) -> bool:
    try:
        tools = ctx.opentracy.list_tools()
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
        return True
    if not tools:
        _route_msg(ctx, "info", "Nenhuma tool encontrada.")
        return True
    for tool in tools:
        _route_msg(ctx, "info", str(tool.get("name") or tool.get("tool_name") or tool))
    return True


def _index(ctx: CommandContext, args: str) -> bool:
    if not args.strip():
        _route_msg(ctx, "error", "Uso: /indexar <arquivo|pasta>")
        return True
    target = Path(args.strip()).expanduser().resolve()
    if not target.exists():
        _route_msg(ctx, "error", f"Arquivo ou pasta nao encontrado: {target}")
        return True
    targets = _collect_index_targets(target)
    if not targets:
        _route_msg(ctx, "warning",
            "Nenhum arquivo suportado encontrado. Tipos atuais: "
            + ", ".join(sorted(SUPPORTED_INDEX_EXTENSIONS))
        )
        return True
    if target.is_dir():
        _route_msg(ctx, "info", f"Lote: {len(targets)} arquivos para indexar.")
    try:
        for path in targets:
            validation = ctx.knowledge.validate(path)
            if not validation.get("approved"):
                _route_msg(ctx, "warning",
                    f"Ignorado: {path.name} "
                    f"{_format_validation_errors(validation)}"
                )
                continue
            # Extrai metadados estruturados do conteúdo do arquivo
            metadata = None
            try:
                from cous.knowledge.metadata import extract_metadata
                text = path.read_text(encoding="utf-8", errors="replace")
                metadata = extract_metadata(text, str(path))
            except Exception:
                pass  # fallback: sem metadados
            created = ctx.knowledge.index(path, metadata=metadata)
            job_id = str(created.get("job_id"))
            _route_msg(ctx, "info", f"Job criado: {job_id} arquivo={path.name}")
            _poll_job(ctx, job_id)
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _collect_index_targets(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() in SUPPORTED_INDEX_EXTENSIONS else []
    if not target.is_dir():
        return []
    return [
        path
        for path in sorted(target.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_INDEX_EXTENSIONS
    ]


def _validate(ctx: CommandContext, args: str) -> bool:
    target_value = args.strip() or _prompt("Arquivo ou pasta para validar", ctx=ctx)
    if not target_value.strip():
        _route_msg(ctx, "error", "Uso: /validar <arquivo|pasta>")
        return True
    target = Path(target_value).expanduser().resolve()
    if not target.exists():
        _route_msg(ctx, "error", f"Arquivo ou pasta nao encontrado: {target}")
        return True
    targets = _collect_index_targets(target)
    if not targets:
        renderer.warning(
            "Nenhum arquivo suportado encontrado. Tipos atuais: "
            + ", ".join(sorted(SUPPORTED_INDEX_EXTENSIONS))
        )
        return True
    approved = 0
    rejected = 0
    try:
        for path in targets:
            result = ctx.knowledge.validate(path)
            if result.get("approved"):
                approved += 1
                renderer.success(
                    f"OK {path.name} chars={result.get('char_count', 0)} "
                    f"tipo={result.get('content_type') or '-'}"
                )
            else:
                rejected += 1
                _route_msg(ctx, "warning", f"REPROVADO {path.name} {_format_validation_errors(result)}")
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
        return True
    _route_msg(ctx, "info", f"Validacao concluida: {approved} aprovados, {rejected} reprovados.")
    return True


def _format_validation_errors(validation: dict[str, Any]) -> str:
    errors = validation.get("errors")
    if not isinstance(errors, list) or not errors:
        return "(sem detalhes)"
    codes = [
        str(error.get("code"))
        for error in errors
        if isinstance(error, dict) and error.get("code")
    ]
    return f"({', '.join(codes)})" if codes else "(sem detalhes)"


def _poll_job(ctx: CommandContext, job_id: str) -> None:
    """Polling com backoff exponencial. Máx ~6 chamadas para jobs rápidos."""
    terminal_statuses = {"indexed", "failed", "cancelled", "skipped"}
    timeout_seconds = ctx.config.knowledge.poll_timeout_seconds
    backoff_seconds = 1.0
    max_backoff = 16.0
    elapsed = 0.0

    while elapsed < timeout_seconds:
        job = ctx.knowledge.get_job(job_id)
        status = str(job.get("status", "unknown"))
        stage = job.get("stage") or "-"
        _route_msg(ctx, "info", f"job={job_id[:8]} status={status} stage={stage}")

        # Job progress via output_router no TUI
        if ctx.output_router:
            ctx.output_router.job_progress(job_id, status, stage)

        if status in terminal_statuses:
            if status == "failed":
                error = job.get("error")
                if error:
                    _route_msg(ctx, "error", _format_job_error(error))
            return

        time.sleep(backoff_seconds)
        elapsed += backoff_seconds
        backoff_seconds = min(backoff_seconds * 2, max_backoff)

    _route_msg(ctx, "warning",
        f"Polling encerrado apos {timeout_seconds}s; o job pode continuar no OpenTracy."
    )


def _format_job_error(error: object) -> str:
    if not isinstance(error, dict):
        return str(error)
    code = str(error.get("code") or "erro")
    message = str(error.get("message") or "")
    errors = error.get("errors")
    if isinstance(errors, list) and errors:
        codes = [
            str(item.get("code"))
            for item in errors
            if isinstance(item, dict) and item.get("code")
        ]
        if codes:
            return f"{code}: {message} ({', '.join(codes)})"
    return f"{code}: {message}".strip()


def _documents(ctx: CommandContext, args: str) -> bool:
    try:
        docs = ctx.knowledge.list_documents()
        if ctx.output_router:
            ctx.output_router.documents_table(docs)
        else:
            renderer.documents_table(docs)
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _search(ctx: CommandContext, args: str) -> bool:
    query = args.strip() or _prompt("Consulta para buscar", ctx=ctx)
    if not query.strip():
        _route_msg(ctx, "error", "Uso: /buscar <consulta>")
        return True
    try:
        results = ctx.knowledge.search(query.strip())
        if ctx.output_router:
            ctx.output_router.search_results(results, query=query.strip())
        else:
            renderer.search_results(results)
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _delete(ctx: CommandContext, args: str) -> bool:
    document_id = args.strip() or _prompt("Document ID para remover", ctx=ctx)
    if not document_id:
        _route_msg(ctx, "error", "Uso: /remover <document_id>")
        return True
    try:
        # Se parece um prefixo (não um UUID completo), busca nos documentos
        if len(document_id) < 32 and not _looks_like_full_uuid(document_id):
            resolved = _resolve_document_id(ctx, document_id)
            if resolved is None:
                _route_msg(ctx, "error", f"Nenhum documento encontrado com prefixo: {document_id}")
                return True
            if len(resolved) > 1:
                _route_msg(ctx, "info", f"Multiplos documentos encontrados. Use o ID completo:")
                for doc_id in resolved:
                    _route_msg(ctx, "info", f"  {doc_id}")
                return True
            document_id = resolved[0]
        ctx.knowledge.delete_document(document_id)
        _route_msg(ctx, "success", f"Documento removido: {document_id}")
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _resolve_document_id(ctx: CommandContext, prefix: str) -> list[str] | None:
    """Busca documentos cujo ID começa com o prefixo."""
    try:
        docs = ctx.knowledge.list_documents()
        matches = [d.get("id", "") for d in docs if str(d.get("id", "")).startswith(prefix)]
        return matches if matches else None
    except ClientError:
        return None


def _looks_like_full_uuid(value: str) -> bool:
    import re
    return bool(re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', value))


def _delete_measurement(ctx: CommandContext, args: str) -> bool:
    """Remove sessoes de medicao do armazenamento local e remoto.

    Aceita multiplos IDs separados por virgula ou espaco:
      /deletar_medicao id1, id2, id3
      /deletar_medicao id1 id2 id3
    """
    raw = args.strip()
    if not raw:
        _route_msg(ctx, "error", "Uso: /deletar_medicao <id1> [id2 ...]")
        return True
    # Split por vírgula, depois por espaço em cada elemento
    ids: list[str] = []
    for part in raw.split(","):
        for sub in part.strip().split():
            if sub:
                ids.append(sub)
    if not ids:
        _route_msg(ctx, "error", "Uso: /deletar_medicao <id1> [id2 ...]")
        return True

    deleted_local = 0
    deleted_remote = 0
    not_found = 0

    for session_id in ids:
        try:
            ctx.measurements.get_session(session_id)
        except ValueError:
            _route_msg(ctx, "warning", f"Nao encontrada: {session_id}")
            not_found += 1
            continue
        ctx.measurements.delete_session(session_id)
        deleted_local += 1
        try:
            ctx.measurements.delete_remote_session(session_id)
            deleted_remote += 1
        except Exception:
            pass  # runtime offline — remocao local ja foi feita

    if deleted_local > 0:
        remote_info = f" ({deleted_remote} remoto)" if deleted_remote > 0 else ""
        _route_msg(ctx, "success", f"{deleted_local} sessoes removidas{remote_info}")
    if not_found > 0:
        _route_msg(ctx, "warning", f"{not_found} sessoes nao encontradas")
    return True


def _measurements(ctx: CommandContext, args: str) -> bool:
    try:
        sessions = ctx.measurements.list_sessions(args.strip() or None)
        if not sessions:
            _route_msg(ctx, "info", "Nenhuma sessao encontrada para o filtro informado.")
            return True
        if ctx.output_router:
            ctx.output_router.measurements_table(sessions)
        else:
            renderer.measurements_table(sessions)
    except (ClientError, ValueError) as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _measurement(ctx: CommandContext, args: str) -> bool:
    session_id = args.strip() or _prompt_measurement_session_id(ctx, "medicao")
    if not session_id:
        _route_msg(ctx, "error", "Uso: /medicao <id>")
        return True
    try:
        session = ctx.measurements.get_session(session_id)
        if session is None:
            _route_msg(ctx, "error", f"Medicao nao encontrada: {session_id}")
            return True
        if ctx.output_router:
            ctx.output_router.measurement_detail(session)
        else:
            renderer.measurement_detail(session)
    except (ClientError, ValueError, AttributeError) as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _measurement_report(ctx: CommandContext, args: str) -> bool:
    session_id = args.strip() or _prompt_measurement_session_id(ctx, "laudo")
    if not session_id:
        _route_msg(ctx, "error", "Uso: /laudo <id>")
        return True
    try:
        result = ctx.measurements.report(session_id)
        markdown = str(result.get("markdown") or "")
        if ctx.post_assistant:
            ctx.post_assistant(markdown)
        elif ctx.output_router:
            ctx.output_router.assistant(markdown)
        else:
            renderer.assistant(markdown)
    except (ClientError, ValueError) as exc:
        _route_msg(ctx, "error", str(exc))
    return True


def _measurement_diagnostic(ctx: CommandContext, args: str) -> bool:
    """Enfileira diagnóstico remoto COUS v3 no OpenTracy."""
    parts = args.strip().split(maxsplit=1)
    if parts and parts[0].lower() in {"status", "resultado", "result"}:
        return _measurement_diagnostic_status(
            ctx,
            parts[1] if len(parts) > 1 else "",
        )

    session_id = args.strip() or _prompt_measurement_session_id(ctx, "diagnostico")
    if not session_id:
        _route_msg(ctx, "error", "Uso: /diagnostico <id>")
        return True

    try:
        result = ctx.measurements.diagnose_v3(session_id)
    except (ClientError, ValueError, AttributeError) as exc:
        _route_msg(ctx, "error", str(exc))
        return True

    diagnostic = result.get("diagnostic") or {}
    status = str(diagnostic.get("status") or "unknown")
    correlation_id = str(diagnostic.get("correlation_id") or "")
    source = str(result.get("source") or "")

    if status == "local_fallback":
        error = str(diagnostic.get("error") or "diagnostico v3 indisponivel")
        _route_msg(ctx, "warning", f"Diagnostico v3 nao enfileirado: {error}")
        if correlation_id:
            _route_msg(ctx, "info", f"correlation_id local={correlation_id}")
        return True

    _route_msg(ctx, "success", f"Diagnostico v3 enfileirado: status={status}")
    if correlation_id:
        _route_msg(ctx, "info", f"correlation_id={correlation_id}")
    _route_msg(
        ctx,
        "info",
        "Fonte: "
        + (source or "v3-remoto")
        + ". O resultado final sera disponibilizado pelo worker/callback do OpenTracy.",
    )
    _route_msg(ctx, "info", f"Consulte com: /diagnostico resultado {session_id}")
    return True


def _measurement_diagnostic_status(ctx: CommandContext, args: str) -> bool:
    session_id = args.strip() or _prompt_measurement_session_id(ctx, "diagnostico")
    if not session_id:
        _route_msg(ctx, "error", "Uso: /diagnostico status <id>")
        return True

    try:
        session = ctx.measurements.get_session(session_id)
    except (ClientError, ValueError, AttributeError) as exc:
        _route_msg(ctx, "error", str(exc))
        return True

    if session is None:
        _route_msg(ctx, "error", f"Medicao nao encontrada: {session_id}")
        return True

    if hasattr(ctx.measurements, "refresh_diagnosis_status"):
        try:
            refreshed = ctx.measurements.refresh_diagnosis_status(session_id)
            session = refreshed.get("session") or session
        except (ClientError, ValueError, AttributeError):
            pass

    rows = diagnosis_summary_rows(session)
    if not rows:
        _route_msg(ctx, "warning", f"Nenhum diagnostico registrado para {session_id}.")
        return True

    lines = [f"Diagnostico da medicao {session_id}"]
    lines.extend(f"{key}: {value}" for key, value in rows)
    text = "\n".join(lines)
    if ctx.post_assistant:
        ctx.post_assistant(text)
    elif ctx.output_router:
        ctx.output_router.assistant(text)
    else:
        renderer.assistant(text)
    return True


def _measurement_compare(ctx: CommandContext, args: str) -> bool:
    """Compara duas sessões de medição e gera laudo comparativo (motor local).

    Uso: /comparar <id1> <id2>
         /comparar              (compara as duas últimas)
         /comparar <id1>        (compara <id1> com a última)

    Extrai valores médios de cada sessão, compara campo a campo,
    aplica cadeias causais nas diferenças e exibe laudo formatado.
    """
    args_stripped = args.strip()
    ids = args_stripped.split()

    sessions_list = ctx.measurements.list_sessions()
    if len(sessions_list) < 2:
        _route_msg(ctx, "error", "Sao necessarias pelo menos 2 sessoes de medicao para comparar.")
        return True

    all_ids = [str(s.get("id") or "") for s in sessions_list]

    # Determinar quais sessões comparar
    if len(ids) == 0:
        session_id_a = all_ids[-2] if len(all_ids) >= 2 else ""
        session_id_b = all_ids[-1]
    elif len(ids) == 1:
        session_id_a = ids[0]
        session_id_b = all_ids[-1]
    else:
        session_id_a, session_id_b = ids[0], ids[1]

    if session_id_a == session_id_b:
        _route_msg(ctx, "error", "Os IDs das sessoes devem ser diferentes.")
        return True

    try:
        session_a = ctx.measurements.get_session(session_id_a)
        session_b = ctx.measurements.get_session(session_id_b)
    except Exception as e:
        _route_msg(ctx, "error", f"Erro ao carregar sessoes: {e}")
        return True

    if not session_a or not session_b:
        _route_msg(ctx, "error", "Uma ou ambas as sessoes nao foram encontradas.")
        return True

    avg_a = _extract_session_averages(session_a)
    avg_b = _extract_session_averages(session_b)

    header_a = session_a.get("header") or {}
    header_b = session_b.get("header") or {}

    laudo = _render_comparison_report(
        session_id_a, header_a, avg_a,
        session_id_b, header_b, avg_b,
    )

    if ctx.post_assistant:
        try:
            ctx.post_assistant(laudo)
        except Exception:
            pass
    elif ctx.send_to_chat:
        try:
            ctx.send_to_chat(laudo)
        except Exception:
            pass
    else:
        _route_msg(ctx, "assistant", laudo)

    return True


def _extract_session_averages(session: dict) -> dict[str, dict]:
    """Extrai valores médios por tipo de snapshot de uma sessão."""
    snapshots = session.get("snapshots") or []
    accum: dict[str, dict[str, float]] = {}
    counts: dict[str, dict[str, int]] = {}

    for snap in snapshots:
        snap_type = snap.get("type", "desconhecido")
        if snap_type not in accum:
            accum[snap_type] = {}
            counts[snap_type] = {}

        for key, val in snap.items():
            if key in ("type", "status", "version", "valid", "snapshot_kind",
                        "armature_resistance_measured"):
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                accum[snap_type][key] = accum[snap_type].get(key, 0.0) + float(val)
                counts[snap_type][key] = counts[snap_type].get(key, 0) + 1

    averages: dict[str, dict[str, float]] = {}
    for snap_type, fields in accum.items():
        averages[snap_type] = {}
        for field, total in fields.items():
            cnt = counts[snap_type].get(field, 1)
            averages[snap_type][field] = total / cnt if cnt > 0 else 0.0

    return averages


def _render_comparison_report(
    id_a: str, header_a: dict, avg_a: dict,
    id_b: str, header_b: dict, avg_b: dict,
) -> str:
    """Renderiza comparativo numérico entre duas sessões. Apenas dados, sem interpretação."""
    fab_a = header_a.get("fabricante", "?")
    mod_a = header_a.get("modelo", "?")
    fab_b = header_b.get("fabricante", "?")
    mod_b = header_b.get("modelo", "?")

    lines = [
        "╔══ COMPARAÇÃO NUMÉRICA ═══════════╗",
        f"║ A: {fab_a} {mod_a}",
        f"║ B: {fab_b} {mod_b}",
        "╠══════════════════════════════════╣",
    ]

    # Todos os campos numéricos, agrupados por tipo de snapshot
    # Usar os campos que existem nos dados, não uma lista fixa
    all_campos: dict[str, set] = {}
    for snap_type in set(list(avg_a.keys()) + list(avg_b.keys())):
        campos_a = set(avg_a.get(snap_type, {}).keys())
        campos_b = set(avg_b.get(snap_type, {}).keys())
        all_campos[snap_type] = campos_a | campos_b

    total_diffs = 0

    for snap_type in sorted(all_campos.keys()):
        campos = sorted(all_campos[snap_type])
        vals_a = avg_a.get(snap_type, {})
        vals_b = avg_b.get(snap_type, {})

        lines.append(f"╟── {snap_type} ({len(campos)} campos) ──╢")

        for campo in campos:
            va = vals_a.get(campo)
            vb = vals_b.get(campo)

            if va is None and vb is None:
                continue

            # Formatar valores
            va_str = f"{va:.1f}" if isinstance(va, float) else (str(va) if va is not None else "?")
            vb_str = f"{vb:.1f}" if isinstance(vb, float) else (str(vb) if vb is not None else "?")

            if va is not None and vb is not None and isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                delta = vb - va
                if va != 0:
                    pct = (delta / abs(va)) * 100
                    sinal = "+" if delta > 0 else ""
                    lines.append(f"║ {campo[:20]:20s} {va_str:>8s} → {vb_str:>8s}  Δ={sinal}{delta:.1f} ({pct:+.1f}%)")
                else:
                    lines.append(f"║ {campo[:20]:20s} {va_str:>8s} → {vb_str:>8s}  Δ={delta:.1f}")
                total_diffs += 1
            elif va is not None:
                lines.append(f"║ {campo[:20]:20s} {va_str:>8s}   (ausente em B)")
            elif vb is not None:
                lines.append(f"║ {campo[:20]:20s} {'?':>8s} → {vb_str:>8s} (ausente em A)")

    lines.append("╠══════════════════════════════════╣")
    lines.append(f"║ Total de campos comparados: {total_diffs}")
    lines.append("║ Use /diagnostico <id> para análise")
    lines.append("║ Use /laudo <id> para laudo completo")
    lines.append("╚══════════════════════════════════╝")
    return "\n".join(lines)


def _build_diagnosis_prompt(session: dict) -> str:
    """Monta o prompt de diagnóstico a partir de uma sessão de medição."""
    header = session.get("header") or {}
    snapshots = session.get("snapshots") or []
    
    fabricante = header.get("fabricante", "?")
    modelo = header.get("modelo", "?")
    tipo_coleta = header.get("tipo_coleta", "?")
    observacoes = header.get("observacoes", "")
    
    # Resumo estatístico por tipo de snapshot
    from collections import Counter
    type_counts = Counter()
    exemplos = {}
    for snap in snapshots:
        t = snap.get("type", "desconhecido")
        type_counts[t] += 1
        if t not in exemplos:
            exemplos[t] = {k: v for k, v in snap.items() if k not in ("type", "status", "version", "valid")}
    
    # Montar prompt
    parts = [
        "=== SOLICITAÇÃO DE DIAGNÓSTICO TÉCNICO ===",
        f"Máquina: {fabricante} {modelo}",
        f"Tipo de coleta: {tipo_coleta}",
    ]
    
    if observacoes:
        parts.append(f"Observações do operador: {observacoes}")
    
    parts.append(f"\nTotal de snapshots coletados: {len(snapshots)}")
    parts.append("Distribuição por tipo:")
    for t, c in type_counts.most_common():
        parts.append(f"  - {t}: {c} snapshots")
    
    # Amostras: no máximo 2 snapshots por tipo para não estourar timeout
    parts.append("\nAmostras de cada tipo de medição (até 2 por tipo):")
    for t, campos in sorted(exemplos.items()):
        parts.append(f"\n  [{t}] — amostra de {type_counts[t]} snapshots")
        for k, v in sorted(campos.items()):
            if isinstance(v, float):
                parts.append(f"    {k}: {v:.3f}")
            else:
                parts.append(f"    {k}: {v}")
    
    # Relações da assinatura eletromecânica (Firmware v2)
    for snap in snapshots:
        if snap.get("type") == "electromechanical_signature" and "relations" in snap:
            rels = snap["relations"]
            parts.append("\nRelações observado vs referência (assinatura eletromecânica):")
            for rel_name, rel_data in sorted(rels.items()):
                if isinstance(rel_data, dict) and rel_data.get("valid"):
                    obs = rel_data.get("obs", "?")
                    ref = rel_data.get("ref", "?")
                    err = rel_data.get("err", "?")
                    conf = rel_data.get("conf", "?")
                    parts.append(f"  {rel_name}: obs={obs} ref={ref} erro={err}‰ conf={conf}/1000")
            break  # só uma assinatura por sessão
    
    parts.append("\n---")
    parts.append("Com base nos dados acima e nos documentos técnicos indexados")
    parts.append("(datasheets, ordens de serviço, manuais), gere um diagnóstico")
    parts.append("técnico estruturado com:")
    parts.append("1. Análise dos valores medidos e das relações observado vs referência")
    parts.append("2. Possíveis causas (baseadas em OS similares se disponíveis)")
    parts.append("3. Recomendações de manutenção")
    parts.append("4. Nível de confiança do diagnóstico")
    
    return "\n".join(parts)


def _count_snapshots(session: dict) -> int:
    return len(session.get("snapshots") or [])


def _capture(ctx: CommandContext, args: str) -> bool:
    try:
        header = (
            _parse_measurement_header_args(args)
            if args.strip()
            else _prompt_measurement_header(ctx=ctx)
        )
        session = ctx.measurements.create_session(_measurement_header_payload(header))
        session_id = str(session.get("id") or "")
    except ValueError as exc:
        _route_msg(ctx, "error", str(exc))
        _route_msg(ctx, "info",
            "Uso: /capturar fabricante=FK modelo=Flux numero_serie=SN123 "
            "tipo_coleta=desempenho sistema_transmissao=direct porta_serial=/dev/ttyACM0 "
            "verticais=hall,power,course,vibration"
        )
        return True
    except ClientError as exc:
        _route_msg(ctx, "error", str(exc))
        return True
    _route_msg(ctx, "success", f"Sessao de medicao criada: {session_id}")
    if ctx.output_router:
        ctx.output_router.measurement_detail(session)
    else:
        renderer.measurement_detail(session)
    if _is_truthy(header.get("sem_serial")):
        ctx.measurements.save_session(session_id)
        _route_msg(ctx, "info", "Sessao criada sem captura serial.")
        return True
    while True:
        capture_error = ""
        snapshots: list[dict[str, Any]] = []
        try:
            snapshots = _capture_serial_snapshots(header, ctx=ctx)
            if not snapshots:
                _route_msg(ctx, "warning", "Nenhum TMA_DATA selecionado foi capturado.")
        except (ClientError, OSError, ValueError) as exc:
            capture_error = str(exc)
            _route_msg(ctx, "error", f"Falha na captura serial: {exc}")
        action = _prompt_post_capture_action(ctx=ctx, 
            has_snapshots=bool(snapshots),
            has_error=bool(capture_error),
        )
        if action == "refazer":
            _route_msg(ctx, "info", "Refazendo testes com o mesmo cabecalho.")
            continue
        if action == "descartar":
            ctx.measurements.delete_session(session_id)
            _route_msg(ctx, "warning", "Sessao descartada.")
            return True
        if action == "sair":
            ctx.measurements.abandon_session(session_id)
            _route_msg(ctx, "info", "Sessao mantida localmente para continuar depois.")
            return True
        if not snapshots:
            ctx.measurements.save_session(session_id)
            _route_msg(ctx, "warning", "Sessao salva sem snapshots validos.")
            return True
        result = ctx.measurements.add_snapshots(session_id, snapshots)
        _route_msg(ctx, "success",
            f"Snapshots salvos: aceitos={result.get('accepted', 0)} "
            f"rejeitados={result.get('rejected', 0)}"
        )
        rejected_items = result.get("rejected_items") or []
        if rejected_items:
            _route_msg(ctx, "warning", f"Snapshots rejeitados na validacao: {len(rejected_items)}")
        saved = ctx.measurements.save_session(session_id)
        _try_sync_saved_session(ctx, session_id)
        if ctx.output_router:
            ctx.output_router.measurement_detail(saved)
        else:
            renderer.measurement_detail(saved)
        return True
    return True


def _parse_measurement_header_args(args: str) -> dict[str, Any]:
    allowed = {
        "fabricante",
        "modelo",
        "numero_serie",
        "tipo_maquina",
        "tipo_motor",
        "sistema_transmissao",
        "curso_nominal_mm",
        "curso_min_mm",
        "curso_max_mm",
        "tipo_coleta",
        "peca_substituida",
        "observacoes",
        "tecnico",
        "porta_serial",
        "baudrate",
        "duracao_seg",
        "verticais",
        "sem_serial",
    }
    aliases = {
        "serie": "numero_serie",
        "serial": "numero_serie",
        "transmissao": "sistema_transmissao",
        "coleta": "tipo_coleta",
        "porta": "porta_serial",
        "duracao": "duracao_seg",
        "curso": "curso_nominal_mm",
        "dry_run": "sem_serial",
        "no_serial": "sem_serial",
    }
    header: dict[str, Any] = {
        "tipo_coleta": "desempenho",
        "baudrate": 115200,
        "duracao_seg": 30.0,
        "verticais": list(DEFAULT_VERTICALS),
        "sem_serial": False,
    }
    if not args.strip():
        return header
    for token in shlex.split(args):
        if "=" not in token:
            raise ValueError(f"Parametro invalido: {token}. Use chave=valor.")
        raw_key, raw_value = token.split("=", 1)
        key = aliases.get(raw_key.strip().lower(), raw_key.strip().lower())
        if key not in allowed:
            raise ValueError(f"Parametro desconhecido: {raw_key}")
        value = raw_value.strip()
        if key in {"curso_nominal_mm", "curso_min_mm", "curso_max_mm", "duracao_seg"}:
            header[key] = float(value) if value else None
        elif key == "baudrate":
            header[key] = int(value)
        elif key == "verticais":
            header[key] = sorted(normalize_verticals(value.split(",")))
        elif key == "sem_serial":
            header[key] = _is_truthy(value)
        else:
            header[key] = value
    return header


def _measurement_header_payload(header: dict[str, Any]) -> dict[str, Any]:
    payload = dict(header)
    payload.pop("sem_serial", None)
    return payload


def _prompt_measurement_header(ctx: CommandContext | None = None) -> dict[str, Any]:
    header: dict[str, Any] | None = None
    while True:
        _route_msg(ctx, "info", "Preencha o cabecalho. Pressione Enter para aceitar o padrao.")
        _route_msg(ctx, "info", "Dados da maquina")
        machine = _prompt_machine_header(header, ctx=ctx)
        _route_msg(ctx, "info", "Dados da coleta")
        collection = _prompt_collection_header(header, ctx=ctx)
        _route_msg(ctx, "info", "Conexao serial")
        serial = _prompt_serial_header(header, ctx=ctx)
        _route_msg(ctx, "info", "Selecao de TMA_DATA")
        current_verticals = header.get("verticais") if header else None
        current_sem_serial = bool(header.get("sem_serial")) if header else False
        header = {}
        header.update(machine)
        header.update(collection)
        header.update(serial)
        header["verticais"] = _prompt_verticals(current_verticals, ctx=ctx)
        header["sem_serial"] = _prompt_bool("Criar sessao sem capturar agora?", current_sem_serial, ctx=ctx)
        _route_msg(ctx, "info",
            "Resumo: "
            f"{header.get('fabricante') or '-'} {header.get('modelo') or '-'} "
            f"serie={header.get('numero_serie') or '-'} "
            f"coleta={header.get('tipo_coleta')} "
            f"verticais={','.join(header['verticais'])}"
        )
        action = _prompt_header_action(ctx=ctx)
        if action == "salvar":
            return header
        if action == "descartar":
            raise ValueError("Captura cancelada pelo usuario.")


def _prompt_machine_header(previous: dict[str, Any] | None = None, *, ctx = None) -> dict[str, Any]:
    previous = previous or {}
    return {
        "fabricante": _prompt("Fabricante", str(previous.get("fabricante") or "DKLAB"), ctx=ctx),
        "modelo": _prompt("Modelo", str(previous.get("modelo") or ""), ctx=ctx),
        "numero_serie": _prompt("Numero de serie", str(previous.get("numero_serie") or ""), ctx=ctx),
        "tipo_maquina": _prompt(
            "Tipo de maquina",
            str(previous.get("tipo_maquina") or "tattoo_machine"),
            ctx=ctx,
        ),
        "tipo_motor": _prompt("Tipo de motor", str(previous.get("tipo_motor") or "coreless"), ctx=ctx),
        "sistema_transmissao": _prompt(
            "Sistema de transmissao",
            str(previous.get("sistema_transmissao") or "direct"),
            ctx=ctx,
        ),
        "curso_nominal_mm": _prompt_float("Curso nominal mm", _coerce_float(previous.get("curso_nominal_mm")), ctx=ctx),
        "curso_min_mm": _prompt_float("Curso minimo mm", _coerce_float(previous.get("curso_min_mm")), ctx=ctx),
        "curso_max_mm": _prompt_float("Curso maximo mm", _coerce_float(previous.get("curso_max_mm")), ctx=ctx),
    }


def _prompt_collection_header(previous: dict[str, Any] | None = None, *, ctx = None) -> dict[str, Any]:
    previous = previous or {}
    header = {
        "tipo_coleta": _prompt(
            "Tipo de coleta",
            str(previous.get("tipo_coleta") or "desempenho"),
            [
                "desempenho",
                "reparo",
                "pos-reparo",
                "homologacao",
                "bancada",
                "calibracao",
                "laudo_calibracao",
            ],
            ctx=ctx,
        ),
        "peca_substituida": str(previous.get("peca_substituida") or ""),
        "observacoes": _prompt("Observacoes", str(previous.get("observacoes") or ""), ctx=ctx),
        "tecnico": _prompt("Tecnico responsavel", str(previous.get("tecnico") or ""), ctx=ctx),
    }
    if header["tipo_coleta"] in {"reparo", "pos-reparo"}:
        header["peca_substituida"] = _prompt(
            "Peca substituida",
            str(previous.get("peca_substituida") or ""),
            ctx=ctx,
        )
    return header


def _prompt_serial_header(previous: dict[str, Any] | None = None, *, ctx = None) -> dict[str, Any]:
    previous = previous or {}
    return {
        "porta_serial": _prompt("Porta serial", str(previous.get("porta_serial") or "/dev/ttyACM0"), ctx=ctx),
        "baudrate": _prompt_int("Baudrate", _coerce_int(previous.get("baudrate"), 115200), ctx=ctx),
        "duracao_seg": _prompt_float(
            "Duracao segundos",
            _coerce_float(previous.get("duracao_seg"), 30.0),
            ctx=ctx,
        )
        or 30.0,
    }


VERTICAL_COLORS: dict[str, str] = {
    "hall": "cyan",
    "power": "blue",
    "course": "orange1",
    "vibration": "magenta",
}


def _capture_serial_snapshots(header: dict[str, Any], *, ctx = None) -> list[dict[str, Any]]:
    selected = normalize_verticals(header.get("verticais") or DEFAULT_VERTICALS)
    counts: dict[str, int] = {vertical: 0 for vertical in sorted(selected)}

    def on_snapshot(snapshot: dict[str, Any]) -> None:
        snapshot_type = normalize_snapshot_type(snapshot.get("type"))
        counts[snapshot_type] = counts.get(snapshot_type, 0) + 1
        parts = []
        for key in sorted(counts):
            color = VERTICAL_COLORS.get(key, "white")
            parts.append(f"[{color}]{key}={counts[key]}[/]")
        _route_msg(ctx, "info", " ".join(parts))

    _route_msg(ctx, "info",
        "Capturando TMA_DATA: "
        f"porta={header.get('porta_serial')} baudrate={header.get('baudrate')} "
        f"duracao={header.get('duracao_seg')}s verticais={','.join(sorted(selected))}"
    )
    return capture_tma_snapshots(
        port=str(header.get("porta_serial") or "/dev/ttyACM0"),
        baudrate=int(header.get("baudrate") or 115200),
        duration_seconds=float(header.get("duracao_seg") or 30.0),
        allowed_types=selected,
        on_snapshot=on_snapshot,
    )


def _prompt(message: str, default: str = "", options: list[str] | None = None, *,
            ctx: CommandContext | None = None, keep_history: bool = False) -> str:
    """Prompt interativo. No TUI, usa threading.Event para não travar a UI.

    keep_history=False: limpa readline history antes do prompt (campos textuais).
    keep_history=True:  mantém histórico (útil para s/n).
    """
    if ctx is not None and ctx.output_router:
        return _tui_prompt(ctx, message, default, options)
    # Modo legado: limpa histórico e mostra campo atual
    if not keep_history:
        try:
            import readline
            readline.clear_history()
        except (ImportError, OSError):
            pass
    suffix = f" [{default}]" if default else ""
    if options:
        suffix += " (" + "/".join(options) + ")"
    renderer.info(f">> {message}")
    renderer.console.print(f"{message}{suffix}: ", end="", markup=False)
    value = input().strip()
    value = value or default
    if options and value not in options:
        renderer.console.print(f"Opcao invalida: {', '.join(options)}")
        return _prompt(message, default, options)
    return value


def _tui_prompt(ctx: CommandContext, message: str, default: str, options: list[str] | None) -> str:
    """Prompt no TUI: posta PromptRequest e espera resposta via threading.Event."""
    import threading
    event = threading.Event()
    result = [default]  # mutable container

    ctx.output_router._post_prompt(message, default, event, result)

    # Timeout de 120s para não travar indefinidamente
    if not event.wait(timeout=120):
        return default
    return result[0]


def _prompt_float(message: str, default: float | None = None, *, ctx = None) -> float | None:
    value = _prompt(message, "" if default is None else str(default), ctx=ctx)
    return float(value) if value else None


def _prompt_int(message: str, default: int, *, ctx = None) -> int:
    return int(_prompt(message, str(default), ctx=ctx))


def _prompt_bool(message: str, default: bool, *, ctx = None) -> bool:
    value = _prompt(message, "sim" if default else "nao", ctx=ctx, keep_history=True).lower()
    if value in {"sim", "s", "yes", "y", "true", "1"}:
        return True
    if value in {"nao", "n", "no", "false", "0"}:
        return False
    _route_msg(ctx, "warning", "Responda com sim/nao ou s/n.")
    return _prompt_bool(message, default, ctx=ctx)


def _prompt_verticals(current: list[str] | None = None, ctx: CommandContext | None = None) -> list[str]:
    selected: list[str] = []
    available = ctx.measurements.get_verticals() if ctx is not None else DEFAULT_VERTICALS
    for vertical in available:
        default = True if current is None else vertical in current
        if _prompt_bool(f"Coletar {vertical}_snapshot?", default, ctx=ctx):
            selected.append(vertical)
    if not selected:
        raise ValueError("Selecione pelo menos uma vertical TMA_DATA.")
    return sorted(normalize_verticals(selected))


def _prompt_header_action(ctx = None) -> str:
    return _prompt(
        "Cabecalho pronto. Escolha a acao",
        "salvar",
        ["salvar", "editar", "descartar"],
        ctx=ctx,
    )


def _prompt_post_capture_action(*, has_snapshots: bool, has_error: bool, ctx = None) -> str:
    default = "refazer" if has_error or not has_snapshots else "salvar"
    return _prompt(
        "Pos-captura: salvar, descartar, sair ou refazer",
        default,
        ["salvar", "descartar", "sair", "refazer"],
        ctx=ctx,
    )


def _coerce_float(value: object, fallback: float | None = None) -> float | None:
    if value in {None, ""}:
        return fallback
    return float(value)


def _coerce_int(value: object, fallback: int) -> int:
    if value in {None, ""}:
        return fallback
    return int(value)


def _is_truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "sim", "s", "yes", "y", "on"}


def _new_session(ctx: CommandContext, args: str) -> bool:
    ctx.session = ctx.conversations.create_session()
    ctx.logger.log("chat_session_created", session_id=ctx.session.session_id)
    _route_msg(ctx, "success", f"Nova sessao de chat criada: {ctx.session.session_id}")
    return True


def _memory(ctx: CommandContext, args: str) -> bool:
    _route_msg(ctx, "info",
        "Sessao atual: "
        f"{ctx.session.session_id} mensagens={len(ctx.session.history)} "
        f"resumo={'sim' if bool(ctx.session.summary) else 'nao'}"
    )
    return True


def _summary_chat(ctx: CommandContext, args: str) -> bool:
    if not ctx.session.history:
        _route_msg(ctx, "info", "Sessao de chat atual ainda nao tem mensagens.")
        return True
    try:
        summary = build_chat_summary(ctx)
    except ClientError as exc:
        _route_msg(ctx, "error", f"Falha ao resumir sessao: {exc}")
        return True
    ctx.session.set_summary(summary)
    ctx.logger.log("summary_updated", session_id=ctx.session.session_id, automatic=False)
    _route_msg(ctx, "success", f"Resumo atualizado para a sessao {ctx.session.session_id}.")
    if ctx.output_router:
        ctx.output_router.assistant(summary)
    else:
        renderer.assistant(summary)
    return True


def _load_chat_session(ctx: CommandContext, args: str) -> bool:
    target = args.strip() or _prompt(
        "Sessao de chat para carregar (id, prefixo ou vazio para mais recente)",
        ctx=ctx,
    )
    try:
        if not target:
            latest = ctx.conversations.latest_session()
            if latest is None:
                _route_msg(ctx, "info", "Nenhuma sessao de chat persistida.")
                return True
            ctx.session = latest
        else:
            ctx.session = ctx.conversations.load_session(target, event_logger=ctx.logger)
    except ValueError as exc:
        _route_msg(ctx, "error", str(exc))
        return True
    _route_msg(ctx, "success", f"Sessao carregada: {ctx.session.session_id}")
    ctx.logger.log("chat_session_loaded", session_id=ctx.session.session_id)
    _route_msg(ctx, "info",
        f"Mensagens={len(ctx.session.history)} resumo={'sim' if bool(ctx.session.summary) else 'nao'}"
    )
    return True


def _list_chat_sessions(ctx: CommandContext, args: str) -> bool:
    sessions = ctx.conversations.list_sessions()
    if not sessions:
        _route_msg(ctx, "info", "Nenhuma sessao de chat persistida.")
        return True
    if ctx.output_router:
        ctx.output_router.chat_sessions_table(sessions)
    else:
        renderer.chat_sessions_table(sessions)
    return True


def _delete_chat_session(ctx: CommandContext, args: str) -> bool:
    session_id = args.strip()
    if not session_id:
        _route_msg(ctx, "error", "Uso: /deletar_chat <id>")
        _route_msg(ctx, "info", "Use /listar para ver os IDs disponiveis.")
        return True

    # resolve_unique reporta ambiguidade (diferente de resolve_session_id)
    try:
        resolved = ctx.conversations.resolve_unique(session_id)
    except ValueError as exc:
        _route_msg(ctx, "error", str(exc))
        return True

    # Proteção: não permite deletar a sessão ativa
    if resolved == ctx.session.session_id:
        _route_msg(ctx, "error",
            "Nao e possivel deletar a sessao ativa. "
            "Crie uma nova sessao com /novo antes de deletar esta."
        )
        return True

    # Confirmação interativa
    confirm = _prompt(f"Deletar sessao {resolved}? Esta acao e irreversivel. [s/N] ", ctx=ctx).strip().lower()
    if confirm not in {"s", "sim"}:
        _route_msg(ctx, "info", "Operacao cancelada.")
        return True

    deleted = ctx.conversations.delete_session(resolved)
    if deleted:
        ctx.logger.log("session_deleted", session_id=resolved)
        _route_msg(ctx, "success", f"Sessao {resolved} deletada.")
    else:
        _route_msg(ctx, "error", f"Falha ao deletar sessao {resolved}.")
    return True


def _export_chat_session(ctx: CommandContext, args: str) -> bool:
    parts = args.strip().split(maxsplit=1)
    session_id = parts[0] if parts else ""

    if not session_id:
        session = ctx.session
    else:
        try:
            session = ctx.conversations.load_session(session_id, event_logger=ctx.logger)
        except ValueError as exc:
            _route_msg(ctx, "error", str(exc))
            return True

    output_dir = Path(".cous-data/exports")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{session.session_id}.md"
    lines: list[str] = [
        f"# Sessão de Chat — {session.session_id}\n",
        f"**Criada em:** {session.created_at}  ",
        f"**Atualizada em:** {session.updated_at}  ",
        f"**Mensagens:** {len(session.history)}\n",
    ]
    if session.summary:
        lines += ["\n## Resumo\n", session.summary, ""]

    lines.append("\n## Histórico\n")
    for message in session.history:
        role = message.get("role", "desconhecido")
        content = message.get("content", "")
        label = "**Operador**" if role == "user" else "**Agente**"
        lines += [f"\n{label}:\n", content, ""]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    ctx.logger.log("session_exported", session_id=session.session_id, path=str(output_path.resolve()))
    _route_msg(ctx, "success", f"Sessao exportada: {output_path.resolve()}")
    return True


def _confirm_feedback(ctx: CommandContext, args: str) -> bool:
    """Confirma que uma resposta do agente estava correta.
    
    Uso:
      /confirmar                        confirma a última resposta
      /confirmar <trace_id> [coment]    confirma uma resposta específica pelo trace_id
    """
    if ctx.feedback_store is None:
        _route_msg(ctx, "error", "Feedback nao configurado.")
        return True

    args = args.strip()
    trace_id = ctx.last_trace_id
    comment = ""

    if args:
        # Se o primeiro token parece um UUID/trace_id, usa ele
        parts = args.split(maxsplit=1)
        first = parts[0]
        if _looks_like_trace_id(first):
            trace_id = first
            comment = parts[1] if len(parts) > 1 else ""
        else:
            comment = args

    if not comment:
        comment = ctx.session.last_assistant_message()

    if not trace_id:
        _route_msg(ctx, "error", "Nenhuma resposta disponivel para confirmar.")
        return True

    ctx.feedback_store.record(
        feedback_type="confirmed",
        session_id=ctx.session.session_id,
        trace_id=trace_id,
        content=comment,
        original_response=ctx.session.last_assistant_message(),
        user_request=ctx.session.last_user_message(),
    )
    ctx.logger.log("feedback_confirmed", session_id=ctx.session.session_id, trace_id=trace_id)
    if ctx.output_router:
        ctx.output_router.success(f"Feedback registrado: resposta confirmada (trace_id={trace_id}).")
        ctx.output_router.feedback_registered("confirmed", trace_id)
    else:
        _route_msg(ctx, "success", f"Feedback registrado: resposta confirmada (trace_id={trace_id}).")
    # Fase E: promover trace a golden no runtime
    try:
        ctx.opentracy.promote_to_golden(trace_id)
    except Exception as exc:
        _route_msg(ctx, "warning", f"Promocao a golden falhou: {exc}")
    
    # COUS v3.1: promover hipótese confirmada a KnowledgeUnit
    try:
        # Buscar correlation_id associado à última resposta (se for diagnóstico)
        session_data = ctx.measurements.latest_session()
        if session_data:
            corr_id = session_data.get("diagnosis_correlation_id")
            if corr_id:
                # Tentar promover — o correlation_id não é o ku_id diretamente,
                # mas indica que há um diagnóstico pendente de confirmação
                _route_msg(ctx, "info", f"Diagnostico {corr_id[:8]}... marcado como confirmado.")
                # Incrementar contador de casos confirmados para KUs relacionadas
                ctx.logger.log("knowledge_confirmed", correlation_id=corr_id, trace_id=trace_id)
    except Exception:
        pass  # falha não-bloqueante — feedback já foi registrado
    
    return True


def _looks_like_trace_id(value: str) -> bool:
    """Heurística: UUID ou hash hexadecimal com 8+ caracteres."""
    import re
    # UUID: 07030490-25d5-4e7b-a690-4da4d9583080
    if re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', value):
        return True
    # Hash curto: mock_04ab6ea08e7c ou 04ab6ea08e7c
    if re.match(r'^(mock_)?[0-9a-fA-F]{12,}$', value):
        return True
    return False


def _correct_feedback(ctx: CommandContext, args: str) -> bool:
    """Registra uma correção para a última resposta do agente."""
    if ctx.feedback_store is None:
        _route_msg(ctx, "error", "Feedback nao configurado.")
        return True
    correction = args.strip()
    if not correction:
        _route_msg(ctx, "error", "Uso: /corrigir <texto da correcao>")
        return True
    ctx.feedback_store.record(
        feedback_type="correction",
        session_id=ctx.session.session_id,
        trace_id=ctx.last_trace_id,
        content=correction,
        original_response=ctx.session.last_assistant_message(),
        user_request=ctx.session.last_user_message(),
    )
    ctx.logger.log("feedback_correction", session_id=ctx.session.session_id, trace_id=ctx.last_trace_id)
    if ctx.output_router:
        ctx.output_router.success("Feedback registrado: correcao aplicada.")
    else:
        _route_msg(ctx, "success", "Feedback registrado: correcao aplicada.")
    return True


def _solution_feedback(ctx: CommandContext, args: str) -> bool:
    """Registra uma solução aplicada após diagnóstico."""
    if ctx.feedback_store is None:
        _route_msg(ctx, "error", "Feedback nao configurado.")
        return True
    solution = args.strip()
    if not solution:
        _route_msg(ctx, "error", "Uso: /solucao <descricao da solucao>")
        return True
    ctx.feedback_store.record(
        feedback_type="solution_applied",
        session_id=ctx.session.session_id,
        trace_id=ctx.last_trace_id,
        content=solution,
        original_response=ctx.session.last_assistant_message(),
        user_request=ctx.session.last_user_message(),
    )
    ctx.logger.log("feedback_solution", session_id=ctx.session.session_id, trace_id=ctx.last_trace_id)
    if ctx.output_router:
        ctx.output_router.success("Feedback registrado: solucao aplicada.")
    else:
        _route_msg(ctx, "success", "Feedback registrado: solucao aplicada.")
    return True


def _sync_measurements(ctx: CommandContext, args: str) -> bool:
    target = args.strip()
    if target:
        try:
            synced = ctx.measurements.sync_session(target)
        except (ClientError, ValueError) as exc:
            _route_msg(ctx, "error", f"Falha ao sincronizar: {exc}")
            return True
        renderer.success(
            "Medicao sincronizada: "
            f"{synced.get('id')} remote_id={synced.get('remote_id') or '-'}"
        )
        return True

    # Sync em lote com barra de progresso Rich
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        BarColumn,
        TaskProgressColumn,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("Sincronizando sessões...", total=None)

        def update_bar(current: int, total: int, description: str) -> None:
            progress.update(task, total=total, completed=current, description=description)

        try:
            result = ctx.measurements.sync_pending_sessions(on_progress=update_bar)
        except Exception as exc:
            _route_msg(ctx, "error", f"Falha ao sincronizar: {exc}")
            return True

    _route_msg(ctx, "success", f"Sincronizadas: {result['synced_count']}")
    if result["failed"]:
        _route_msg(ctx, "warning", f"Falhas ({result['failed_count']}):")
        for failure in result["failed"]:
            _route_msg(ctx, "error", f"  {failure['session_id']}: {failure['error']}")
    return True


def _default_session_id(ctx: CommandContext, action: str) -> str:
    session = ctx.measurements.latest_session()
    if session is None:
        return ""
    session_id = str(session.get("id") or "")
    _route_msg(ctx, "info", f"Usando a sessao mais recente para /{action}: {session_id}")
    return session_id


def _prompt_measurement_session_id(ctx: CommandContext, action: str) -> str:
    session = ctx.measurements.latest_session()
    default = str(session.get("id") or "") if session else ""
    if default:
        return default
    return _prompt("ID da medicao", "", ctx=ctx)


def _try_sync_saved_session(ctx: CommandContext, session_id: str) -> None:
    try:
        synced = ctx.measurements.sync_session(session_id)
    except Exception as exc:
        _route_msg(ctx, "warning", f"Sessao salva localmente, mas sync remoto falhou: {exc}")
        return
    _route_msg(ctx, "success",
        "Sessao sincronizada com o backend de medicoes: "
        f"remote_id={synced.get('remote_id') or '-'}"
    )
    # Indexar sumário da medição no knowledge base (Fase B)
    tmp_path: str | None = None
    try:
        from cous.measurements.analysis import index_measurement_session
        from pathlib import Path
        import tempfile
        session = ctx.measurements.get_session(session_id)
        markdown, metadata = index_measurement_session(session)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(markdown)
            tmp_path = tmp.name
        result = ctx.knowledge.index(Path(tmp_path), metadata=metadata)
        # O runtime lê o arquivo durante o job (source_uri).
        job_id = str(result.get("job_id") or "")
        if job_id:
            _poll_job(ctx, job_id)
    except Exception as exc:
        _route_msg(ctx, "warning", f"Indexacao automatica da medicao falhou: {exc}")
    finally:
        # Após o job terminar, o runtime já leu o arquivo — pode deletar
        if tmp_path is not None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def build_chat_summary(ctx: CommandContext) -> str:
    result = ctx.opentracy.chat(
        (
            "Resuma a conversa a seguir em portugues, de forma tecnica e curta. "
            "Preserve decisoes, ids, comandos usados, erros observados e proximos passos."
        ),
        history=ctx.session.history,
        channel="terminal_summary",
    )
    return str(result.get("response") or "").strip()
