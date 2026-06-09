"""Testes de atomicidade para MeasurementLocalStore._save()."""

import json
import os
from unittest.mock import patch

import pytest

from cous.measurements.store import MeasurementLocalStore


def test_save_cleans_up_temp_file(tmp_path):
    """Após _save bem-sucedido, nenhum .tmp residual e JSON íntegro."""
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    store.create_session({"fabricante": "Test"})
    store.create_session({"fabricante": "Test2"})
    # Nenhum .tmp órfão
    assert list(tmp_path.glob("*.tmp")) == []
    # Arquivo contém JSON íntegro
    data = json.loads((tmp_path / "measurements.json").read_text())
    assert len(data["sessions"]) == 2


def test_original_preserved_when_temp_write_fails(tmp_path):
    """Falha durante fsync não corrompe o original nem deixa .tmp órfão."""
    store = MeasurementLocalStore(tmp_path / "measurements.json")
    store.create_session({"fabricante": "Original"})
    original = (tmp_path / "measurements.json").read_text()

    # Simula falha durante fsync (após escrita parcial no tmp)
    with patch("os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.create_session({"fabricante": "Perdida"})

    # Original intacto
    assert (tmp_path / "measurements.json").read_text() == original
    # Nenhum .tmp órfão (try/except no _save faz unlink)
    assert list(tmp_path.glob("*.tmp")) == []
