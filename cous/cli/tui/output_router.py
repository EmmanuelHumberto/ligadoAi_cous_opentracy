"""Roteador de saída para painéis TUI.

Redireciona TODAS as chamadas de renderer para o info-panel (RichLog único).
Thread-safe: usa call_from_thread para o loop Textual.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.message import Message

from cous.cli.tui.events import InfoLine, TableData


class OutputRouter:
    """Redireciona saídas para o info-panel da Sidebar.

    info-panel é um RichLog único que alterna entre pipeline, dados e logs.
    """

    def __init__(self, app: object) -> None:
        self._app = app
        self._pending: list[Message] = []

    # ── Core ────────────────────────────────────────────────────────────

    def _post(self, msg: Message) -> None:
        running = getattr(self._app, "_running", False)
        if running:
            self._app.post_message(msg)
        else:
            self._pending.append(msg)

    def flush_pending(self) -> None:
        for msg in self._pending:
            self._app.post_message(msg)
        self._pending.clear()

    # ── Saída única ─────────────────────────────────────────────────────

    def _info(self, text: str) -> None:
        """Adiciona linha ao info-panel (sem clear)."""
        self._post(InfoLine(text))

    # ── Mensagens de texto ──────────────────────────────────────────────

    def error(self, text: str) -> None:
        self._info(f"[red]▸[/] {text}")

    def info(self, text: str) -> None:
        self._info(text)

    def success(self, text: str) -> None:
        self._info(f"[green]▸[/] {text}")

    def warning(self, text: str) -> None:
        self._info(f"[yellow]▸[/] {text}")

    def assistant(self, text: str) -> None:
        self._info(text)

    def welcome(self, agent_id: str) -> None:
        self._info(f"Cous TUI — agente: {agent_id}")

    # ── Tabelas ─────────────────────────────────────────────────────────

    def status_table(self, rows: list[tuple[str, str, str]]) -> None:
        lines = ["Status"]
        for name, state, detail in rows:
            lines.append(f"  {name}: {state}")
        self._info("\n".join(lines))

    def search_results(self, results: list[dict], query: str = "") -> None:
        columns = ["Score", "ID", "Fonte", "Trecho"]
        rows: list[list[str]] = []
        for r in results[:20]:
            score = f"{r.get('score', 0):.2f}"
            doc_id = str(r.get("document_id", ""))[:14]
            metadata = r.get("metadata") or {}
            # Fonte pelo document_type do metadata
            doc_type = str(metadata.get("document_type") or "")
            if doc_type == "measurement":
                fonte = "Medição"
            elif "laudo" in doc_type.lower():
                fonte = "Laudo"
            elif "equipamento" in doc_type.lower():
                fonte = "Equip."
            else:
                fonte = doc_type.title() if doc_type else "Doc"
            # Extrai contexto ao redor do termo buscado
            full_text = str(r.get("text") or "")
            snippet = full_text[:70]
            if query:
                idx = full_text.lower().find(query.lower())
                if idx >= 0:
                    start = max(0, idx - 20)
                    end = min(len(full_text), idx + len(query) + 50)
                    snippet = "..." + full_text[start:end] + "..."
            rows.append([score, doc_id, fonte, snippet])
        self._post(TableData(columns, rows))

    def documents_table(self, docs: list[dict]) -> None:
        rows = []
        for d in docs:
            doc_id = str(d.get("id", ""))[:14]
            dt = str(d.get("document_type") or "-")
            mfr = str(d.get("manufacturer") or "-")[:15]
            title = str(d.get("title") or "")[:40]
            rows.append([doc_id, dt, mfr, title])
        self._post(TableData(["ID", "Tipo", "Fabricante", "Título"], rows))

    def measurements_table(self, sessions: list[dict]) -> None:
        lines = [f"Medições ({len(sessions)})"]
        for s in sessions[:20]:
            sid = str(s.get("id", ""))
            status = s.get("status", "?")
            lines.append(f"  {sid} {status}")
        self._info("\n".join(lines))

    def chat_sessions_table(self, sessions: list[dict]) -> None:
        lines = [f"Sessões de chat ({len(sessions)})"]
        for s in sessions[:20]:
            sid = str(s.get("id", ""))
            msgs = s.get("messages", "?")
            lines.append(f"  {sid} msgs={msgs}")
        self._info("\n".join(lines))

    def measurement_detail(self, session: dict) -> None:
        from cous.measurements.analysis import summarize_session
        s = summarize_session(session)
        hdr = session.get("header") or {}
        sid = str(s.get("id", ""))
        rows = [
            ("ID", sid),
            ("Fabricante", str(s.get("fabricante") or "-")),
            ("Modelo", str(s.get("modelo") or "-")),
            ("Nº Série", str(s.get("numero_serie") or "-")),
            ("Tipo Coleta", str(s.get("tipo_coleta") or "-")),
            ("Status", str(s.get("status") or "?")),
            ("Snapshots", str(s.get("total_snapshots") or "0")),
        ]
        if hdr.get("tipo_maquina"):
            rows.append(("Tipo Máquina", str(hdr["tipo_maquina"])))
        if hdr.get("tipo_motor"):
            rows.append(("Tipo Motor", str(hdr["tipo_motor"])))
        if hdr.get("sistema_transmissao"):
            rows.append(("Transmissão", str(hdr["sistema_transmissao"])))
        curso = hdr.get("curso_nominal_mm")
        if curso is not None:
            rows.append(("Curso Nominal", f"{curso} mm"))
        if hdr.get("tecnico"):
            rows.append(("Técnico", str(hdr["tecnico"])))
        if s.get("observacoes"):
            rows.append(("Observações", str(s["observacoes"])[:80]))
        # Métricas agregadas
        hall = s.get("hall") or {}
        if hall.get("frequency_hz_avg") is not None:
            rows.append(("Hall Freq.", f"{hall['frequency_hz_avg']:.2f} Hz"))
        if hall.get("rpm_avg") is not None:
            rows.append(("Hall RPM", f"{hall['rpm_avg']:.0f}"))
        power = s.get("power") or {}
        if power.get("bus_voltage_mv_avg") is not None:
            rows.append(("Tensão", f"{power['bus_voltage_mv_avg']:.0f} mV"))
        if power.get("current_ma_avg") is not None:
            rows.append(("Corrente", f"{power['current_ma_avg']:.0f} mA"))
        vib = s.get("vibration") or {}
        if vib.get("rms_norm_mg_avg") is not None:
            rows.append(("Vibração RMS", f"{vib['rms_norm_mg_avg']:.2f} mg"))
        if vib.get("peak_norm_mg_max") is not None:
            rows.append(("Vibração Pico", f"{vib['peak_norm_mg_max']:.0f} mg"))
        if vib.get("p2p_norm_mg_max") is not None:
            rows.append(("Vib. Pico-a-Pico", f"{vib['p2p_norm_mg_max']:.0f} mg"))
        if vib.get("crest_factor_permille_avg") is not None:
            rows.append(("Fator de Crista", f"{vib['crest_factor_permille_avg']:.0f} ‰"))
        if vib.get("rpm_inferred_avg") is not None:
            rows.append(("RPM (vib)", f"{vib['rpm_inferred_avg']:.0f}"))
        # Vibração por eixo (opcional)
        for axis in ("x", "y", "z"):
            rms_key = f"rms_{axis}_mg_avg"
            peak_key = f"peak_{axis}_mg_max"
            if vib.get(rms_key) is not None:
                rows.append((f"Vib. RMS {axis.upper()}", f"{vib[rms_key]:.2f} mg"))
            if vib.get(peak_key) is not None:
                rows.append((f"Vib. Pico {axis.upper()}", f"{vib[peak_key]:.0f} mg"))
        # Orientação
        if vib.get("roll_cdeg_avg") is not None:
            rows.append(("Roll", f"{vib['roll_cdeg_avg']:.1f}°"))
        if vib.get("pitch_cdeg_avg") is not None:
            rows.append(("Pitch", f"{vib['pitch_cdeg_avg']:.1f}°"))
        self._post(TableData(["Campo", "Valor"], [[c, v] for c, v in rows]))

    # ── Controle ────────────────────────────────────────────────────────

    def clear(self) -> None:
        self._post(InfoLine("", clear=True))

    # ── Feedback ────────────────────────────────────────────────────────

    def feedback_registered(self, fb_type: str, trace_id: str) -> None:
        self._info(f"Feedback: {fb_type} trace={trace_id[:8]}")

    def job_progress(self, job_id: str, status: str, stage: str) -> None:
        self._info(f"Job {job_id[:8]}: {status} ({stage})")

    def _post_prompt(self, question: str, default: str, event: object, result: list) -> None:
        """Posta PromptRequest e espera resposta (chamado via _tui_prompt)."""
        from cous.cli.tui.events import PromptRequest
        self._post(PromptRequest(question, default, event, result))


class NullOutputRouter:
    """Output router que descarta todas as saídas (modo legado/headless).

    Substitui o fallback condicional if ctx.output_router em _route_msg(),
    eliminando a necessidade de verificar None em cada call-site.
    """

    def error(self, text: str) -> None: pass
    def info(self, text: str) -> None: pass
    def success(self, text: str) -> None: pass
    def warning(self, text: str) -> None: pass
    def assistant(self, text: str) -> None: pass
    def welcome(self, agent_id: str) -> None: pass
    def status_table(self, rows): pass
    def search_results(self, results, query: str = "") -> None: pass
    def documents_table(self, docs): pass
    def measurements_table(self, sessions): pass
    def chat_sessions_table(self, sessions): pass
    def measurement_detail(self, session): pass
    def clear(self) -> None: pass
    def feedback_registered(self, fb_type: str, trace_id: str) -> None: pass
    def job_progress(self, job_id: str, status: str, stage: str) -> None: pass