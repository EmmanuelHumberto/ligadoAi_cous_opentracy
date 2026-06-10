"""Terminal rendering helpers."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(mouse=False)


def welcome(agent_id: str) -> None:
    console.print(Panel.fit(f"Cous -> OpenTracy\nAgente: {agent_id}", border_style="cyan"))


def prompt() -> str:
    try:
        console.print()
        console.print("[bold cyan]▸[/]", end=" ")
        return input()
    except (EOFError, KeyboardInterrupt):
        return "/sair"


def info(message: str) -> None:
    console.print("[cyan]Info[/] ", end="")
    console.print(message, markup=False)


def success(message: str) -> None:
    console.print("[green]Sucesso[/] ", end="")
    console.print(message, markup=False)


def warning(message: str) -> None:
    console.print("[yellow]Aviso[/] ", end="")
    console.print(message, markup=False)


def error(message: str) -> None:
    console.print("[red]Erro[/] ", end="")
    console.print(message, markup=False)


def status_table(rows: list[tuple[str, str, str]]) -> None:
    table = Table(title="Status", show_header=True)
    table.add_column("Componente", style="bold cyan")
    table.add_column("Estado")
    table.add_column("Detalhe")
    for component, state, detail in rows:
        table.add_row(component, state, detail)
    console.print(table)


def assistant(message: str) -> None:
    console.print()
    console.print(Panel(message or "", border_style="green", title="OpenTracy"))


def documents_table(documents: list[dict]) -> None:
    table = Table(title="Documentos Indexados", show_header=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Titulo")
    table.add_column("Fabricante")
    table.add_column("Modelo")
    table.add_column("Status")
    for doc in documents:
        table.add_row(
            str(doc.get("id", ""))[:8],
            str(doc.get("title") or "-"),
            str(doc.get("manufacturer") or "-"),
            str(doc.get("model") or "-"),
            str(doc.get("status") or "-"),
        )
    console.print(table)


def search_results(results: list[dict]) -> None:
    table = Table(title="Busca", show_header=True)
    table.add_column("Score", justify="right")
    table.add_column("Fonte")
    table.add_column("Trecho")
    for result in results:
        table.add_row(
            f"{float(result.get('score', 0)):.2f}",
            str(result.get("source_uri") or "-"),
            str(result.get("text") or "")[:120],
        )
    console.print(table)


def measurements_table(sessions: list[dict]) -> None:
    table = Table(title="Sessoes de Medicao", show_header=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Fabricante")
    table.add_column("Modelo")
    table.add_column("Status")
    table.add_column("Sync")
    table.add_column("Snapshots", justify="right")
    table.add_column("Atualizada")
    for session in sessions:
        header = session.get("header") or {}
        table.add_row(
            str(session.get("id", ""))[:20],
            str(header.get("fabricante") or "-"),
            str(header.get("modelo") or "-"),
            str(session.get("status") or "-"),
            str(session.get("sync_status") or "-"),
            str(session.get("total_snapshots", 0)),
            str(session.get("updated_at") or "-")[:19],
        )
    console.print(table)


def chat_sessions_table(sessions: list[dict]) -> None:
    table = Table(title="Sessoes de Chat", show_header=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Msgs", justify="right")
    table.add_column("Resumo")
    table.add_column("Atualizada")
    table.add_column("Preview")
    for session in sessions:
        table.add_row(
            str(session.get("id") or "")[:24],
            str(session.get("messages") or 0),
            "sim" if session.get("summary_present") else "nao",
            str(session.get("updated_at") or "-")[:19],
            str(session.get("preview") or "-"),
        )
    console.print(table)


def measurement_detail(session: dict) -> None:
    header = session.get("header") or {}
    rows = [
        ("ID", str(session.get("id") or "-")),
        ("Status", str(session.get("status") or "-")),
        ("Fabricante", str(header.get("fabricante") or "-")),
        ("Modelo", str(header.get("modelo") or "-")),
        ("Serie", str(header.get("numero_serie") or "-")),
        ("Tipo maquina", str(header.get("tipo_maquina") or "-")),
        ("Tipo motor", str(header.get("tipo_motor") or "-")),
        ("Transmissao", str(header.get("sistema_transmissao") or "-")),
        ("Curso nominal", _format_optional_mm(header.get("curso_nominal_mm"))),
        ("Curso minimo", _format_optional_mm(header.get("curso_min_mm"))),
        ("Curso maximo", _format_optional_mm(header.get("curso_max_mm"))),
        ("Tipo coleta", str(header.get("tipo_coleta") or "-")),
        ("Peca substituida", str(header.get("peca_substituida") or "-")),
        ("Tecnico", str(header.get("tecnico") or "-")),
        ("Porta", str(header.get("porta_serial") or "-")),
        ("Baudrate", str(header.get("baudrate") or "-")),
        ("Duracao", str(header.get("duracao_seg") or "-")),
        ("Verticais", ", ".join(header.get("verticais") or []) or "-"),
        ("Observacoes", str(header.get("observacoes") or "-")),
        ("Snapshots", str(session.get("total_snapshots", 0))),
        ("Validos", str(session.get("valid_snapshots", 0))),
        ("Invalidos", str(session.get("invalid_snapshots", 0))),
        ("Sync", str(session.get("sync_status") or "-")),
        ("Remote ID", str(session.get("remote_id") or "-")),
        ("Erro sync", str(session.get("last_sync_error") or "-")),
        ("Atualizada", str(session.get("updated_at") or "-")),
    ]
    table = Table(title="Medicao", show_header=False)
    table.add_column("Campo", style="bold cyan")
    table.add_column("Valor")
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)


def _format_optional_mm(value: object) -> str:
    if value is None or value == "":
        return "-"
    return f"{value} mm"
