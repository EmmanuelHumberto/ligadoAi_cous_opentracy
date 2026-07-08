"""Serial TMA_DATA capture for the Cous terminal."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from contextlib import suppress
from typing import Any, BinaryIO

from cous.measurements.constants import DEFAULT_VERTICALS, TYPE_ALIASES as _TYPE_ALIASES

TMA_PREFIX = "TMA_DATA "
_logger = logging.getLogger("cous.serial")


def normalize_snapshot_type(value: object) -> str:
    raw = str(value or "").strip().lower()
    return _TYPE_ALIASES.get(raw, raw)


def normalize_verticals(values: Iterable[str] | None) -> set[str]:
    if not values:
        return set(DEFAULT_VERTICALS)
    normalized = {normalize_snapshot_type(value) for value in values if value.strip()}
    unknown = normalized.difference(DEFAULT_VERTICALS)
    if unknown:
        raise ValueError(f"Vertical desconhecida: {', '.join(sorted(unknown))}")
    return normalized or set(DEFAULT_VERTICALS)


def parse_tma_data_line(line: str) -> dict[str, Any] | None:
    if TMA_PREFIX not in line:
        return None
    payload = line.split(TMA_PREFIX, 1)[1].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        _logger.warning("TMA_DATA com JSON malformado: %.80s", payload)
        return None
    return data if isinstance(data, dict) else None


def _infer_snapshot_type(snapshot: dict[str, Any]) -> str:
    """Infere o tipo do snapshot quando o campo 'type' está ausente.

    Snaps raw do sensor magnético (MLX90393) não possuem campo type
    mas contém raw_lsb, raw_field_uT, native_offset_field_uT.
    """
    if "type" in snapshot:
        return normalize_snapshot_type(snapshot["type"])
    # Detecção por campos característicos
    if "raw_lsb" in snapshot or "raw_field_uT" in snapshot:
        return "magnetic"
    return "unknown"


def should_collect_snapshot(snapshot: dict[str, Any], allowed_types: set[str]) -> bool:
    return _infer_snapshot_type(snapshot) in allowed_types


def collect_tma_snapshots_from_lines(
    lines: Iterable[str],
    *,
    allowed_types: set[str],
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for line in lines:
        snapshot = parse_tma_data_line(line)
        if snapshot is not None and should_collect_snapshot(snapshot, allowed_types):
            snapshots.append(snapshot)
    return snapshots


def capture_tma_snapshots(
    *,
    port: str,
    baudrate: int,
    duration_seconds: float,
    allowed_types: set[str],
    on_snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        _configure_serial(fd, baudrate)
        deadline = time.monotonic() + duration_seconds
        with os.fdopen(fd, "rb", buffering=0, closefd=False) as stream:
            return _capture_from_stream(
                stream,
                deadline=deadline,
                allowed_types=allowed_types,
                on_snapshot=on_snapshot,
            )
    finally:
        with suppress(OSError):
            os.close(fd)


def _capture_from_stream(
    stream: BinaryIO,
    *,
    deadline: float,
    allowed_types: set[str],
    on_snapshot: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for line in _iter_lines(stream, deadline):
        snapshot = parse_tma_data_line(line)
        if snapshot is None or not should_collect_snapshot(snapshot, allowed_types):
            continue
        snapshots.append(snapshot)
        if on_snapshot is not None:
            on_snapshot(snapshot)
    return snapshots


def _configure_serial(fd: int, baudrate: int) -> None:
    try:
        import termios  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "Captura serial requer Linux (termios nao disponivel neste sistema)."
        ) from exc

    _baud_rates = {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
        230400: termios.B230400,
        460800: termios.B460800,
        921600: termios.B921600,
    }
    speed = _baud_rates.get(baudrate)
    if speed is None:
        raise ValueError(f"Baudrate nao suportado: {baudrate}")
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = speed
    attrs[5] = speed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _iter_lines(stream: BinaryIO, deadline: float) -> Iterable[str]:
    try:
        import select  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "Captura serial requer Linux (select nao disponivel neste sistema)."
        ) from exc
    buffer = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if buffer:
                line = buffer.decode("utf-8", errors="replace").strip()
                if line:
                    yield line
            return
        ready, _, _ = select.select([stream], [], [], min(0.5, remaining))
        if not ready:
            continue
        chunk = stream.read(512)
        if not chunk:
            continue
        buffer.extend(chunk)
        while b"\n" in buffer:
            raw_line, _, rest = buffer.partition(b"\n")
            buffer = bytearray(rest)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                yield line
