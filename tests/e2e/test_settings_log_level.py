"""E2E — nível de log dos serviços aplicado em runtime (RF-805).

O PUT persiste em `system_settings` e aplica no root logger da API na hora; os workers
convergem pelo `watch_log_level` (poll de 10 s). A prova é uma linha DEBUG induzida no
flow-runtime: uma mensagem não-JSON publicada no canal `events` é descartada com log DEBUG
pelo listener — o descarte só vira linha visível quando o nível sobe para DEBUG.
"""

from __future__ import annotations

import httpx
import pytest
import redis

from .conftest import REDIS_URL, compose, esperar_ate

pytestmark = pytest.mark.e2e


def test_log_level_debug_propaga_aos_workers_em_ate_15s(admin: httpx.Client) -> None:
    r = admin.put("/api/system-settings", json={"log_level": "DEBUG"})
    assert r.status_code == 200, r.text

    def _debug_visivel() -> bool:
        # Lixo não-JSON no canal `events`: o listener do flow-runtime descarta com log DEBUG.
        bus = redis.Redis.from_url(REDIS_URL)
        bus.publish("events", "lixo-nao-json")
        bus.close()
        logs = compose("logs", "--tail=100", "flow-runtime")
        return '"level": "DEBUG"' in logs and "Mensagem descartada" in logs

    try:
        esperar_ate(
            lambda: _debug_visivel() or None,
            timeout=20.0,
            intervalo=2.0,
            descricao="linha DEBUG do flow-runtime após PUT DEBUG",
        )
    finally:
        restaurar = admin.put("/api/system-settings", json={"log_level": "INFO"})
        assert restaurar.status_code == 200
