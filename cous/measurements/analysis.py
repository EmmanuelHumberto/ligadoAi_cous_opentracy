"""Local search and summarization for measurement sessions."""

from __future__ import annotations

from statistics import mean
from typing import Any

from cous.measurements.serial_capture import normalize_snapshot_type


def filter_sessions(sessions: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    ranked = search_sessions(sessions, query)
    return [item["session"] for item in ranked]


def search_sessions(
    sessions: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    terms = _normalize_terms(query)
    if not terms:
        return [{"session": session, "score": 1} for session in sessions[:limit]]
    ranked: list[dict[str, Any]] = []
    for session in sessions:
        haystack = _session_haystack(session)
        score = sum(3 if term in haystack else 0 for term in terms)
        if terms and session.get("id"):
            session_id = str(session["id"]).lower()
            score += sum(5 for term in terms if term in session_id)
        if score > 0:
            ranked.append({"session": session, "score": score})
    ranked.sort(
        key=lambda item: (
            int(item["score"]),
            str(item["session"].get("updated_at") or item["session"].get("created_at") or ""),
        ),
        reverse=True,
    )
    return ranked[:limit]


def summarize_session(session: dict[str, Any]) -> dict[str, Any]:
    header = session.get("header") or {}
    snapshots = session.get("snapshots") or []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        snapshot_type = normalize_snapshot_type(snapshot.get("type"))
        by_type.setdefault(snapshot_type, []).append(snapshot)
    return {
        "id": session.get("id"),
        "fabricante": header.get("fabricante"),
        "modelo": header.get("modelo"),
        "numero_serie": header.get("numero_serie"),
        "tipo_coleta": header.get("tipo_coleta"),
        "status": session.get("status"),
        "sync_status": session.get("sync_status"),
        "updated_at": session.get("updated_at"),
        "total_snapshots": session.get("total_snapshots", len(snapshots)),
        "hall": _summarize_hall(by_type.get("hall", [])),
        "power": _summarize_power(by_type.get("power", [])),
        "vibration": _summarize_vibration(by_type.get("vibration", [])),
        "course": _summarize_course(by_type.get("course", [])),
        "snapshots_by_type": session.get("snapshots_by_type") or {},
        "observacoes": header.get("observacoes") or "",
        "tecnico": header.get("tecnico") or "",
    }


def build_chat_context(query: str, sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return ""
    matches = search_sessions(sessions, query, limit=3)
    if not matches and not _looks_like_measurement_query(query):
        return ""
    if not matches:
        matches = [{"session": session, "score": 1} for session in sessions[:3]]
    blocks = []
    for item in matches:
        summary = summarize_session(item["session"])
        lines = [
            f"id={summary['id']}",
            f"maquina={(summary.get('fabricante') or '-')} {(summary.get('modelo') or '-')}",
            f"serie={summary.get('numero_serie') or '-'}",
            f"tipo_coleta={summary.get('tipo_coleta') or '-'}",
            f"status={summary.get('status') or '-'} sync={summary.get('sync_status') or '-'}",
            f"snapshots={summary.get('total_snapshots') or 0}",
        ]
        hall = summary["hall"]
        if hall:
            lines.append(
                "hall="
                f"freq_media={_fmt(hall.get('frequency_hz_avg'))}Hz "
                f"rpm_media={_fmt(hall.get('rpm_avg'))} "
                f"duty_media={_fmt(hall.get('duty_avg'))}"
            )
        power = summary["power"]
        if power:
            lines.append(
                "power="
                f"tensao_media={_fmt(power.get('bus_voltage_mv_avg'))}mV "
                f"corrente_media={_fmt(power.get('current_ma_avg'))}mA "
                f"potencia_media={_fmt(power.get('power_mw_avg'))}mW"
            )
        vibration = summary["vibration"]
        if vibration:
            lines.append(
                "vibration="
                f"rms_media={_fmt(vibration.get('rms_norm_mg_avg'))}mg "
                f"pico_max={_fmt(vibration.get('peak_norm_mg_max'))}mg"
            )
        if summary.get("observacoes"):
            lines.append(f"observacoes={summary['observacoes']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_markdown_report(session: dict[str, Any]) -> str:
    summary = summarize_session(session)
    lines = [
        f"# Laudo Local {summary.get('id')}",
        "",
        "## Cabecalho",
        f"- Fabricante: {summary.get('fabricante') or '-'}",
        f"- Modelo: {summary.get('modelo') or '-'}",
        f"- Serie: {summary.get('numero_serie') or '-'}",
        f"- Tipo de coleta: {summary.get('tipo_coleta') or '-'}",
        f"- Status: {summary.get('status') or '-'}",
        f"- Sincronizacao: {summary.get('sync_status') or '-'}",
        f"- Total de snapshots: {summary.get('total_snapshots') or 0}",
        "",
        "## Resumo tecnico",
    ]
    hall = summary["hall"]
    if hall:
        lines.extend(
            [
                f"- Hall: {hall['count']} snapshots",
                f"- Frequencia media: {_fmt(hall.get('frequency_hz_avg'))} Hz",
                f"- RPM media inferida: {_fmt(hall.get('rpm_avg'))}",
                f"- Duty medio: {_fmt(hall.get('duty_avg'))} permille",
            ]
        )
    power = summary["power"]
    if power:
        lines.extend(
            [
                f"- Power: {power['count']} snapshots",
                f"- Tensao media: {_fmt(power.get('bus_voltage_mv_avg'))} mV",
                f"- Corrente media: {_fmt(power.get('current_ma_avg'))} mA",
                f"- Potencia media: {_fmt(power.get('power_mw_avg'))} mW",
            ]
        )
    vibration = summary["vibration"]
    if vibration:
        lines.extend(
            [
                f"- Vibracao: {vibration['count']} snapshots",
                f"- RMS medio: {_fmt(vibration.get('rms_norm_mg_avg'))} mg",
                f"- Pico maximo: {_fmt(vibration.get('peak_norm_mg_max'))} mg",
                f"- Frequencia dominante media: {_fmt(vibration.get('dominant_frequency_hz_avg'))} Hz",
            ]
        )
    lines.extend(
        [
            "",
            "## Observacoes",
            f"- Tecnico: {summary.get('tecnico') or '-'}",
            f"- Observacoes: {summary.get('observacoes') or '-'}",
        ]
    )
    return "\n".join(lines)


def build_recent_summary(sessions: list[dict[str, Any]], *, limit: int = 3) -> str:
    if not sessions:
        return "Nenhuma medicao salva."
    lines = ["Medicoes recentes:"]
    for session in sessions[:limit]:
        summary = summarize_session(session)
        line = (
            f"- {summary.get('id')} "
            f"{summary.get('fabricante') or '-'} {summary.get('modelo') or '-'} "
            f"status={summary.get('status') or '-'} "
            f"sync={summary.get('sync_status') or '-'} "
            f"snapshots={summary.get('total_snapshots') or 0}"
        )
        hall = summary.get("hall") or {}
        if hall.get("frequency_hz_avg") is not None:
            line += f" freq_media={_fmt(hall['frequency_hz_avg'])}Hz"
        lines.append(line)
    return "\n".join(lines)


def _session_haystack(session: dict[str, Any]) -> str:
    header = session.get("header") or {}
    fields = [
        session.get("id"),
        session.get("status"),
        session.get("sync_status"),
        header.get("fabricante"),
        header.get("modelo"),
        header.get("numero_serie"),
        header.get("tipo_coleta"),
        header.get("tecnico"),
        header.get("observacoes"),
        header.get("peca_substituida"),
    ]
    return " ".join(str(value or "").lower() for value in fields)


def _normalize_terms(query: str) -> list[str]:
    return [item.strip().lower() for item in query.split() if item.strip()]


def _looks_like_measurement_query(query: str) -> bool:
    normalized = f" {query.strip().lower()} "
    keywords = {
        " medicao ",
        " medicoes ",
        " coleta ",
        " coletas ",
        " laudo ",
        " diagnostico ",
        " maquina ",
        " maquinas ",
        " snapshot ",
        " snapshots ",
        " hall ",
        " vibracao ",
        " vibration ",
        " power ",
        " course ",
        " rpm ",
        " serial ",
        " bancada ",
        " reparo ",
    }
    return any(keyword in normalized for keyword in keywords)


def _summarize_hall(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {}
    return {
        "count": len(snapshots),
        "frequency_hz_avg": _avg(snapshots, "frequency_hz"),
        "rpm_avg": _avg(snapshots, "rpm_inferred"),
        "duty_avg": _avg(snapshots, "duty_permille"),
    }


def _summarize_power(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {}
    return {
        "count": len(snapshots),
        "bus_voltage_mv_avg": _avg(snapshots, "bus_voltage_mv"),
        "current_ma_avg": _avg(snapshots, "current_ma"),
        "power_mw_avg": _avg(snapshots, "power_mw"),
    }


def _summarize_vibration(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {}
    result: dict[str, Any] = {
        "count": len(snapshots),
        "rms_norm_mg_avg": _avg(snapshots, "rms_norm_mg"),
        "peak_norm_mg_max": _peak(snapshots, "peak_norm_mg"),
        "p2p_norm_mg_max": _peak(snapshots, "p2p_norm_mg"),
        "dominant_frequency_hz_avg": _avg(snapshots, "dominant_frequency_hz"),
        "rpm_inferred_avg": _avg(snapshots, "rpm_inferred"),
        "crest_factor_permille_avg": _avg(snapshots, "crest_factor_permille"),
        "quality_permille_avg": _avg(snapshots, "quality_permille"),
        "sample_count": _int_avg(snapshots, "sample_count"),
        "window_span_us_avg": _avg(snapshots, "window_span_us"),
    }
    # Orientação (opcional)
    if any(s.get("data", {}).get("roll_cdeg") is not None for s in snapshots):
        result["roll_cdeg_avg"] = _avg(snapshots, "roll_cdeg")
        result["pitch_cdeg_avg"] = _avg(snapshots, "pitch_cdeg")
    # Acelerômetro por eixo (opcional)
    for axis in ("x", "y", "z"):
        rms_key = f"rms_{axis}_mg"
        if any(s.get("data", {}).get(rms_key) is not None for s in snapshots):
            result[f"rms_{axis}_mg_avg"] = _avg(snapshots, rms_key)
    return result


def _summarize_course(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        return {}
    values = _numbers(snapshots, "course_mm")
    if not values:
        return {"count": 0, "course_mm_avg": None, "course_mm_min": None, "course_mm_max": None}
    return {"count": len(values), "course_mm_avg": mean(values),
            "course_mm_min": min(values), "course_mm_max": max(values)}


def _avg(snapshots: list[dict[str, Any]], key: str) -> float | None:
    values = _numbers(snapshots, key)
    if not values:
        return None
    return mean(values)


def _peak(snapshots: list[dict[str, Any]], key: str) -> float | None:
    values = _numbers(snapshots, key)
    return max(values) if values else None


def _int_avg(snapshots: list[dict[str, Any]], key: str) -> int | None:
    values = _numbers(snapshots, key)
    if not values:
        return None
    return int(mean(values))


def _numbers(snapshots: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for snapshot in snapshots:
        value = snapshot.get(key)
        if value is None or value == "":
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def index_measurement_session(session: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Gera documento markdown com sumário da medição e metadata para o OpenTracy.

    Retorna (markdown, metadata) onde metadata segue o schema KnowledgeMetadata:
      manufacturer, model, category, document_type, title, extra

    O extra contém todos os campos do header com tipos puros (NUMBER, TEXT, LIST).
    """
    header = session.get("header", {})
    markdown = build_markdown_report(session)

    def _num(value: object) -> float | None:
        """Converte para float, retorna None se inválido."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    extra = {
        "session_id": str(session.get("id", "")),
        "serial": str(header.get("numero_serie", "")),
        "source": "measurement",
        # Metadados da máquina
        "tipo_maquina": str(header.get("tipo_maquina", "")),
        "tipo_motor": str(header.get("tipo_motor", "")),
        "sistema_transmissao": str(header.get("sistema_transmissao", "")),
        # Curso (numérico)
        "curso_nominal_mm": _num(header.get("curso_nominal_mm")),
        "curso_min_mm": _num(header.get("curso_min_mm")),
        "curso_max_mm": _num(header.get("curso_max_mm")),
        # Operador
        "tecnico": str(header.get("tecnico", "")),
        "observacoes": str(header.get("observacoes", "")),
        "verticais": list(header.get("verticais") or []),
        "total_snapshots": session.get("total_snapshots", 0),
    }
    # Remove campos com None
    extra = {k: v for k, v in extra.items() if v is not None}

    metadata = {
        "manufacturer": str(header.get("fabricante", "")),
        "model": str(header.get("modelo", "")),
        "category": str(header.get("tipo_coleta", "")),
        "document_type": "measurement",
        "title": f"Medição {str(session.get('id', ''))[:20]}",
        "extra": extra,
    }
    return markdown, metadata