from cous.cli.commands import (
    CommandRouter,
    _collect_index_targets,
    _format_validation_errors,
    _parse_measurement_header_args,
    _prompt,
    _prompt_verticals,
    build_router,
)


def test_unknown_command_returns_continue(make_context):
    router = CommandRouter()
    ctx = make_context()

    result = router.dispatch("/naoexiste", ctx=ctx)

    assert result is True


def test_collect_index_targets_accepts_supported_file(tmp_path):
    source = tmp_path / "doc.md"
    source.write_text("conteudo", encoding="utf-8")

    assert _collect_index_targets(source) == [source]


def test_collect_index_targets_expands_directory(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "c.pdf").write_text("c", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "d.docx").write_bytes(b"PK\x03\x04")

    targets = _collect_index_targets(tmp_path)

    assert [path.name for path in targets] == ["a.md", "b.txt", "d.docx"]


def test_format_validation_errors_uses_error_codes():
    message = _format_validation_errors(
        {"errors": [{"code": "low_alpha_ratio"}, {"code": "too_few_words"}]}
    )

    assert message == "(low_alpha_ratio, too_few_words)"


def test_parse_measurement_header_args_preserves_technical_fields():
    header = _parse_measurement_header_args(
        'fabricante="FK Irons" modelo=Flux serie=SN123 '
        'transmissao=direct tipo_motor=brushless curso=3.5 '
        'coleta=calibracao porta=/dev/ttyACM0 verticais=hall,power sem_serial=sim'
    )

    assert header["fabricante"] == "FK Irons"
    assert header["modelo"] == "Flux"
    assert header["numero_serie"] == "SN123"
    assert header["sistema_transmissao"] == "direct"
    assert header["tipo_motor"] == "brushless"
    assert header["curso_nominal_mm"] == 3.5
    assert header["tipo_coleta"] == "calibracao"
    assert header["porta_serial"] == "/dev/ttyACM0"
    assert header["verticais"] == ["hall", "power"]
    assert header["sem_serial"] is True


def test_prompt_verticals_accepts_yes_no_shortcuts(monkeypatch):
    answers = iter(["s", "n", "sim", "nao", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))

    assert _prompt_verticals() == ["course", "hall"]


def test_prompt_does_not_parse_default_as_rich_markup(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "")

    assert _prompt("Porta serial", "/dev/ttyACM0") == "/dev/ttyACM0"


def test_command_alias_dispatches_to_registered_handler(make_context):
    router = build_router()
    ctx = make_context()

    assert router.dispatch("/h", ctx=ctx) is True


def test_status_includes_diagnosis_api(make_context, monkeypatch):
    router = build_router()
    ctx = make_context()
    rows_seen = []
    ctx.output_router = type(
        "Output",
        (),
        {"status_table": lambda self, rows: rows_seen.append(rows)},
    )()

    assert router.dispatch("/status", ctx=ctx) is True

    assert rows_seen
    rows = rows_seen[0]
    diagnosis_row = next(row for row in rows if row[0] == "Diagnosis API")
    assert diagnosis_row[1] == "ok"
    assert "worker=sim" in diagnosis_row[2]


def test_diagnostico_command_enqueues_remote_diagnosis(make_context, monkeypatch):
    router = build_router()
    ctx = make_context()
    session = ctx.measurements.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    ctx.measurements.add_snapshots(
        session["id"],
        [{"type": "hall_snapshot", "timestamp_us": 1, "frequency_hz": 120}],
    )
    messages = []

    def capture_msg(ctx, method, text):
        messages.append((method, text))

    monkeypatch.setattr("cous.cli.commands._route_msg", capture_msg)

    assert router.dispatch(f"/diagnostico {session['id']}", ctx=ctx) is True
    assert any(method == "success" and "enfileirado" in text for method, text in messages)
    assert any("correlation_id=" in text for _, text in messages)


def test_diagnostico_v3_command_is_not_registered(make_context, monkeypatch):
    router = build_router()
    ctx = make_context()
    messages = []

    def capture_msg(ctx, method, text):
        messages.append((method, text))

    monkeypatch.setattr("cous.cli.commands._route_msg", capture_msg)

    assert router.dispatch("/diagnostico_v3 qualquer", ctx=ctx) is True
    assert any("Comando desconhecido" in text for _, text in messages)


def test_diagnostico_status_warns_when_no_result(make_context, monkeypatch):
    router = build_router()
    ctx = make_context()
    session = ctx.measurements.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    messages = []

    def capture_msg(ctx, method, text):
        messages.append((method, text))

    monkeypatch.setattr("cous.cli.commands._route_msg", capture_msg)

    assert router.dispatch(f"/diagnostico status {session['id']}", ctx=ctx) is True
    assert any(method == "warning" and "Nenhum diagnostico" in text for method, text in messages)


def test_diagnostico_status_renders_persisted_result(make_context, monkeypatch):
    router = build_router()
    ctx = make_context()
    session = ctx.measurements.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    session["diagnosis_status"] = "completed"
    session["diagnosis_correlation_id"] = "corr-123"
    session["diagnosis_result"] = {
        "hypotheses": [
            {
                "description": "Atrito elevado no conjunto rotativo",
                "confidence": 0.82,
                "is_primary": True,
            }
        ]
    }
    ctx.measurements._store.replace_session(session)
    rendered = []
    ctx.post_assistant = rendered.append

    assert router.dispatch(f"/diagnostico resultado {session['id']}", ctx=ctx) is True

    assert rendered
    assert "corr-123" in rendered[0]
    assert "Atrito elevado no conjunto rotativo" in rendered[0]


def test_diagnostico_status_refreshes_remote_queue_status(make_context, monkeypatch):
    router = build_router()
    ctx = make_context()
    session = ctx.measurements.create_session(
        {
            "fabricante": "DKLAB",
            "modelo": "W1PRO",
            "tipo_coleta": "desempenho",
            "verticais": ["hall"],
            "baudrate": 115200,
            "duracao_seg": 30.0,
        }
    )
    session["diagnosis_correlation_id"] = "corr-queued"
    session["diagnosis_status"] = "queued"
    ctx.measurements._store.replace_session(session)

    def fake_refresh(session_id):
        updated = ctx.measurements.get_session(session_id)
        updated["diagnosis_status"] = "processing"
        updated["diagnosis_attempts"] = 2
        ctx.measurements._store.replace_session(updated)
        return {"session": updated, "diagnostic": {"status": "processing"}}

    monkeypatch.setattr(ctx.measurements, "refresh_diagnosis_status", fake_refresh)
    rendered = []
    ctx.post_assistant = rendered.append

    assert router.dispatch(f"/diagnostico status {session['id']}", ctx=ctx) is True

    assert rendered
    assert "processing" in rendered[0]
    assert "Tentativas diagnostico: 2" in rendered[0]
