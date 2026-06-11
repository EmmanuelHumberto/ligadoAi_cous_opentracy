"""Domain constants for measurement verticals."""

from __future__ import annotations

# Verticais suportadas pelo protocolo TMA_DATA.
# Esta é a fonte canônica — não alterar em serial_capture.py ou validation.py.
# course foi removido: sem _summarize_course em analysis.py, vertical órfão.
DEFAULT_VERTICALS: tuple[str, ...] = ("hall", "power", "vibration")

# Mapa de aliases de tipo para o nome canônico da vertical.
TYPE_ALIASES: dict[str, str] = {
    "hall": "hall",
    "hall_snapshot": "hall",
    "power": "power",
    "power_snapshot": "power",
    "vibration": "vibration",
    "vibration_snapshot": "vibration",
}
