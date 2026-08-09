import json
import logging
import sys

from ottima_core.logging import JsonFormatter, setup_logging


def _make_record(**overrides):
    defaults = dict(
        name="ottima.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="mensagem de teste",
        args=(),
        exc_info=None,
    )
    defaults.update(overrides)
    return logging.LogRecord(**defaults)


def test_formatter_emite_service_configurado():
    formatter = JsonFormatter(service="api")
    entry = json.loads(formatter.format(_make_record()))
    assert entry["service"] == "api"


def test_formatter_usa_unknown_como_default_sem_service():
    formatter = JsonFormatter()
    entry = json.loads(formatter.format(_make_record()))
    assert entry["service"] == "unknown"


def test_formatter_preserva_os_quatro_campos_antigos():
    formatter = JsonFormatter(service="recorder")
    entry = json.loads(formatter.format(_make_record(name="ottima.recorder", msg="oi")))
    assert entry["logger"] == "ottima.recorder"
    assert entry["message"] == "oi"
    assert entry["level"] == "INFO"
    assert "ts" in entry


def test_formatter_emite_exc_quando_ha_exc_info():
    try:
        raise ValueError("falha proposital")
    except ValueError:
        exc_info = sys.exc_info()
    formatter = JsonFormatter(service="api")
    entry = json.loads(formatter.format(_make_record(exc_info=exc_info)))
    assert "ValueError" in entry["exc"]


def test_setup_logging_grava_service_no_formatter_do_handler():
    setup_logging("INFO", "opc-worker")
    handler = logging.getLogger().handlers[0]
    entry = json.loads(handler.formatter.format(_make_record()))
    assert entry["service"] == "opc-worker"


def test_setup_logging_default_service_e_unknown():
    setup_logging("INFO")
    handler = logging.getLogger().handlers[0]
    entry = json.loads(handler.formatter.format(_make_record()))
    assert entry["service"] == "unknown"
