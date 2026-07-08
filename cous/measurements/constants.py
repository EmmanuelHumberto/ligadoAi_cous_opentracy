"""Domain constants for measurement verticals — COUS v3.1."""

from __future__ import annotations

# Verticais suportadas pelo protocolo TMA_DATA.
# Esta é a fonte canônica — não alterar em serial_capture.py ou validation.py.
DEFAULT_VERTICALS: tuple[str, ...] = (
    "hall",
    "power",
    "course",
    "vibration",
    "signature",
    "magnetic",
)

# Mapa de aliases de tipo para o nome canônico da vertical.
TYPE_ALIASES: dict[str, str] = {
    # Hall (campo magnético + RPM + duty cycle)
    "hall": "hall",
    "hall_snapshot": "hall",
    # Potência (tensão, corrente, potência)
    "power": "power",
    "power_snapshot": "power",
    # Curso (deslocamento via MLX90393)
    "course": "course",
    "course_snapshot": "course",
    # Vibração (acelerômetro)
    "vibration": "vibration",
    "vibration_snapshot": "vibration",
    # Assinatura eletromecânica (COUS v3.0 — payload consolidado)
    "signature": "signature",
    "electromechanical_signature": "signature",
    # Sensores magnéticos brutos (raw_lsb, raw_field_uT)
    "magnetic": "magnetic",
    "magnetic_snapshot": "magnetic",
    "raw_magnetic": "magnetic",
}
