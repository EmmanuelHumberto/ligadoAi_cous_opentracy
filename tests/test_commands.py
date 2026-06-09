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
    answers = iter(["s", "n", "sim", "nao"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))

    assert _prompt_verticals() == ["course", "hall"]


def test_prompt_does_not_parse_default_as_rich_markup(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "")

    assert _prompt("Porta serial", "/dev/ttyACM0") == "/dev/ttyACM0"


def test_command_alias_dispatches_to_registered_handler(make_context):
    router = build_router()
    ctx = make_context()

    assert router.dispatch("/h", ctx=ctx) is True
