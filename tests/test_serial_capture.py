from cous.measurements.serial_capture import (
    _iter_lines,
    collect_tma_snapshots_from_lines,
    normalize_verticals,
    parse_tma_data_line,
)


def test_parse_tma_data_line_accepts_firmware_payload():
    snapshot = parse_tma_data_line(
        'I (123) app: TMA_DATA {"type":"hall_snapshot","timestamp_us":10,"rpm":120}'
    )

    assert snapshot == {"type": "hall_snapshot", "timestamp_us": 10, "rpm": 120}


def test_collect_tma_snapshots_filters_selected_verticals():
    lines = [
        'TMA_DATA {"type":"hall_snapshot","timestamp_us":10,"rpm":120}',
        'TMA_DATA {"type":"power_snapshot","timestamp_us":11,"current_ma":90}',
        'TMA_DATA {"type":"course_snapshot","timestamp_us":12,"course_mm":3.5}',
        'TMA_DATA {"type":"vibration_snapshot","timestamp_us":13,"rms_g":0.2}',
    ]

    snapshots = collect_tma_snapshots_from_lines(
        lines,
        allowed_types=normalize_verticals(["hall", "power"]),
    )

    assert [item["type"] for item in snapshots] == ["hall_snapshot", "power_snapshot"]


def test_normalize_verticals_accepts_snapshot_aliases():
    assert normalize_verticals(["hall_snapshot", "vibration_snapshot"]) == {"hall", "vibration"}


def test_iter_lines_does_not_stop_on_empty_serial_read(monkeypatch):
    class Stream:
        def __init__(self) -> None:
            self._chunks = iter([b"", b'TMA_DATA {"type":"hall_snapshot"}\n'])

        def read(self, size: int) -> bytes:
            return next(self._chunks, b"")

    stream = Stream()
    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr("cous.measurements.serial_capture.time.monotonic", lambda: next(times))
    # select é importado localmente em _iter_lines; patch diretamente no módulo select
    monkeypatch.setattr(
        "select.select",
        lambda read, write, error, timeout: (read, write, error),
    )

    assert list(_iter_lines(stream, deadline=1.0)) == ['TMA_DATA {"type":"hall_snapshot"}']


def test_module_imports_without_termios(monkeypatch):
    """Importar o módulo não lança ImportError quando termios está ausente."""
    import sys
    # Simula ambiente sem termios
    monkeypatch.setitem(sys.modules, "termios", None)
    # Remove do cache para forçar reimport limpo
    sys.modules.pop("cous.measurements.serial_capture", None)
    # Deve importar sem erro
    import cous.measurements.serial_capture as sc
    # Funções de domínio devem estar acessíveis (não dependem de termios)
    assert sc.normalize_snapshot_type("hall_snapshot") == "hall"
    assert sc.collect_tma_snapshots_from_lines is not None
