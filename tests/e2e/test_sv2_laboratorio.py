"""Camada L2 do laboratório e dos conjuntos de treino da SV-2 (ADR-046; plano da SV-2, Task 10):
E2E-SV2-01..04.

Atravessa o que os testes de unidade não atravessam: API -> fila `ml_jobs` -> ml-worker (processo
filho) -> leitura de `samples` gravado pelo recorder -> conjunto `ready`. Um projeto só para o
módulo (`projeto_com_conexao`: ativo, conexão ao opcsim `up`, tags `sine` e `static`); cada cenário
cria a SUA variável de laboratório, e o teardown do projeto leva tudo em cascata.

Cancelamento de job não tem cenário L2 de propósito: o job de montagem pode terminar antes de o
cancelamento chegar e o teste seria uma corrida. A morte do processo filho é provada em
`services/ml-worker/tests/test_runner.py`, e o cancelamento na fila em
`services/api/tests/test_softsensor_datasets.py`.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from .conftest import RUN_ID, Ambiente, esperar_ate
from .test_sv1_sensor_virtual import _esperar_historico

pytestmark = pytest.mark.e2e

LAB = "/api/softsensor"
CSV = {"Content-Type": "text/csv"}
MAX_CSV = 5 * 1024 * 1024  # MAX_LAB_CSV_BYTES da API
NGINX_PADRAO = 1024 * 1024  # client_max_body_size padrão do nginx: o import precisa passar dele


def _criar_variavel(admin: httpx.Client, nome: str) -> dict[str, Any]:
    r = admin.post(f"{LAB}/lab-variables", json={"name": nome, "eu": "%"})
    assert r.status_code == 201, f"POST lab-variables: HTTP {r.status_code} {r.text}"
    return r.json()


def _csv(nome: str, analises: list[tuple[datetime, float]]) -> bytes:
    """`"nome";"data/hora";"valor"` com ISO-8601 e fuso explícito (o `tz` da rota nem é usado)."""
    linhas = (f"{nome};{quando.isoformat()};{valor}" for quando, valor in analises)
    return "\n".join(linhas).encode()


def _importar(admin: httpx.Client, corpo: bytes, *, timeout: float = 20.0) -> httpx.Response:
    return admin.post(
        f"{LAB}/lab-samples/import",
        params={"tz": "UTC"},
        content=corpo,
        headers=CSV,
        timeout=timeout,
    )


def _job(admin: httpx.Client, job_id: int) -> dict[str, Any]:
    r = admin.get(f"{LAB}/jobs/{job_id}")
    assert r.status_code == 200, f"GET jobs/{job_id}: HTTP {r.status_code} {r.text}"
    return r.json()


def test_e2e_sv2_01_do_csv_ao_conjunto(admin: httpx.Client, projeto_com_conexao: Ambiente) -> None:
    """RF-585/586: variável -> CSV de 3 análises nos últimos 20 s -> conjunto de 2 tags, período
    1 s e início 1 min atrás -> finalizar. Em até 60 s o job fica `done`, o conjunto `ready` e
    `stats.paired == 3` (as 3 análises caem em instantes com processo gravado pelo recorder)."""
    tags = [projeto_com_conexao.sine, projeto_com_conexao.static]
    _esperar_historico(admin, tags, span_s=30.0)
    variavel = _criar_variavel(admin, f"lab01-{RUN_ID}")
    agora = datetime.now(UTC).replace(microsecond=0)

    r = _importar(
        admin,
        _csv(
            variavel["name"],
            [(agora - timedelta(seconds=s), v) for s, v in ((15, 1.5), (10, 2.5), (5, 3.5))],
        ),
    )
    assert r.status_code == 200, f"import do CSV: HTTP {r.status_code} {r.text}"
    assert r.json() == {"imported": 3, "by_variable": {variavel["name"]: 3}}

    r = admin.post(
        f"{LAB}/datasets",
        json={
            "name": f"ds01-{RUN_ID}",
            "lab_variable_id": variavel["id"],
            "input_tag_ids": tags,
            "period_s": 1,
            "start_ts": (agora - timedelta(minutes=1)).isoformat(),
        },
    )
    assert r.status_code == 201, f"POST datasets: HTTP {r.status_code} {r.text}"
    dataset_id = r.json()["id"]
    assert r.json()["status"] == "collecting"

    r = admin.post(f"{LAB}/datasets/{dataset_id}/finalize")
    assert r.status_code == 202, f"finalize: HTTP {r.status_code} {r.text}"
    job_id = r.json()["job_id"]

    def terminou() -> dict[str, Any] | None:
        job = _job(admin, job_id)
        assert job["status"] not in ("failed", "cancelled"), f"job {job_id}: {job}"
        return job if job["status"] == "done" else None

    esperar_ate(terminou, timeout=60.0, intervalo=1.0, descricao=f"job {job_id} done")

    conjunto = next(d for d in admin.get(f"{LAB}/datasets").json() if d["id"] == dataset_id)
    assert conjunto["status"] == "ready", conjunto
    assert conjunto["stats"]["paired"] == 3, conjunto["stats"]


def test_e2e_sv2_02_csv_recusado_nao_grava_nada(
    admin: httpx.Client, projeto_com_conexao: Ambiente
) -> None:
    """RF-585: uma linha de variável desconhecida recusa o arquivo inteiro (422 citando a linha)
    e a linha boa do mesmo arquivo não é importada."""
    variavel = _criar_variavel(admin, f"lab02-{RUN_ID}")
    agora = datetime.now(UTC).replace(microsecond=0)
    corpo = (
        _csv(variavel["name"], [(agora - timedelta(seconds=10), 1.5)])
        + b"\n"
        + _csv("OUTRA", [(agora - timedelta(seconds=5), 2.5)])
    )

    r = _importar(admin, corpo)

    assert r.status_code == 422, f"import do CSV: HTTP {r.status_code} {r.text}"
    assert "linha 2" in r.json()["detail"] and "OUTRA" in r.json()["detail"], r.text
    r = admin.get(f"{LAB}/lab-variables/{variavel['id']}/samples")
    assert r.status_code == 200 and r.json() == [], r.text


def test_e2e_sv2_03_saude_do_ml_worker(admin: httpx.Client) -> None:
    """ADR-046: o health agregado traz o `ml_worker` e ele está `up`."""
    r = admin.get("/api/health/workers")
    assert r.status_code == 200, f"GET /api/health/workers: HTTP {r.status_code} {r.text}"
    assert r.json()["ml_worker"]["up"] is True, r.json()


def test_e2e_sv2_04_csv_grande_pelo_nginx(
    admin: httpx.Client, projeto_com_conexao: Ambiente
) -> None:
    """Pelo nginx (a base da suíte é a porta do frontend): um CSV de ~2 MB, acima do 1 MB padrão
    do nginx e abaixo do teto de 5 MiB, é importado (o `location =` de 6m do import); um corpo
    acima de 5 MiB leva o 413 em pt-BR da API (JSON), não a página HTML do nginx."""
    variavel = _criar_variavel(admin, f"lab04-{RUN_ID}")
    inicio = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)
    linhas, tamanho, i = [], 0, 0
    while tamanho < 2_000_000:  # um instante por segundo, todos no passado
        linha = f"{variavel['name']};{(inicio + timedelta(seconds=i)).isoformat()};{i % 100}.5"
        linhas.append(linha)
        tamanho += len(linha) + 1
        i += 1
    corpo = "\n".join(linhas).encode()
    assert NGINX_PADRAO < len(corpo) < MAX_CSV

    r = _importar(admin, corpo, timeout=60.0)

    assert r.status_code == 200, (
        f"import de {len(corpo)} bytes: HTTP {r.status_code} {r.text[:200]}"
    )
    assert r.json()["imported"] == len(linhas)

    r = _importar(admin, b"x" * (MAX_CSV + 1024), timeout=60.0)

    assert r.status_code == 413, f"corpo > 5 MiB: HTTP {r.status_code} {r.text[:200]}"
    assert r.headers["content-type"].startswith("application/json"), r.headers
    assert r.json()["detail"] == "Arquivo excede o limite de 5 MiB."
