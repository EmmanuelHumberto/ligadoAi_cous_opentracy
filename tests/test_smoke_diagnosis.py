"""Tests for the diagnosis smoke script."""

import importlib.util
from pathlib import Path

from cous.config import Config, MeasurementsConfig, OpenTracyConfig

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "smoke_diagnosis.py"
_SPEC = importlib.util.spec_from_file_location("smoke_diagnosis", _SCRIPT_PATH)
assert _SPEC is not None
smoke_diagnosis = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(smoke_diagnosis)

_callback_status_url = smoke_diagnosis._callback_status_url
_check_local_identity_config = smoke_diagnosis._check_local_identity_config


def test_callback_status_url_from_callback_endpoint():
    assert (
        _callback_status_url("http://localhost:8000/cous/diagnosis/callback")
        == "http://localhost:8000/cous/diagnosis/callback/status"
    )


def test_callback_status_url_preserves_existing_status_endpoint():
    assert (
        _callback_status_url("http://localhost:8000/cous/diagnosis/callback/status")
        == "http://localhost:8000/cous/diagnosis/callback/status"
    )


def test_local_identity_config_accepts_auto_resolve(tmp_path):
    config = Config(
        opentracy=OpenTracyConfig(diagnosis_auto_resolve_identity=True),
        measurements=MeasurementsConfig(storage_file=str(tmp_path / "measurements.json")),
    )

    name, ok, detail = _check_local_identity_config(config)

    assert name == "local diagnosis config"
    assert ok is True
    assert "auto_resolve=True" in detail


def test_local_identity_config_requires_ids_without_auto_resolve(tmp_path):
    config = Config(
        opentracy=OpenTracyConfig(diagnosis_auto_resolve_identity=False),
        measurements=MeasurementsConfig(storage_file=str(tmp_path / "measurements.json")),
    )

    _name, ok, detail = _check_local_identity_config(config)

    assert ok is False
    assert "domain_id=False" in detail
    assert "instance_id=False" in detail
