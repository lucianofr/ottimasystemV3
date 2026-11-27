"""Camada L2 do sensor virtual da SV-1 (ADR-046; plano da SV-1, Task 12): E2E-SV-01..04.

Cobre o caminho que os testes de unidade não atravessam: arquivo de projeto com modelo e vínculo
-> import -> deploy no flow-runtime -> `flow.status`, evento e `GET /api/softsensor/*`. Na SV-1 o
único jeito de um modelo entrar é o import (treino e ativação por tela são da SV-2/SV-3), então o
modelo sintético vai no bundle, montado aqui com `ottima_core.softsensor.synthetic`.

Um projeto só para o módulo, com um flow por cenário (`sv01`..`sv04`): a troca de modelo do
E2E-SV-02 não pode mexer no `b` que o E2E-SV-01 confere, e cada cenário roda sozinho com `-k`.
As entradas são a senoide e a estática do opcsim (as duas já com histórico gravado pelo recorder
no instante do deploy, que é o que o pré-aquecimento do E2E-SV-03 lê de `samples`).
"""

import base64
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import redis

from opcsim import NODE_SINE, NODE_STATIC
from ottima_core.bus import KIND_SOFT_SENSOR_MODEL_ACTIVATED
from ottima_core.portability.schemas import (
    BundleConnection,
    BundleFlow,
    BundleProject,
    BundleSoftSensorBinding,
    BundleSoftSensorModel,
    BundleTag,
    BundleTagRef,
    ProjectBundle,
)
from ottima_core.signal import Quality
from ottima_core.softsensor import ModelMeta, synthetic

from .conftest import RUN_ID, EventStream, esperar_ate, esperar_conexao
from .f3_support import (
    aguardar_parado,
    aresta,
    assinantes_de_status,
    ativar_projeto,
    bloco,
    bloco_softsensor,
    blocos_softsensor,
    de_varredura,
    deploy,
    esperar_historico,
    esperar_saida_boa,
    id_da_sentinela,
    montar_grafo,
    porta,
    valor,
)

pytestmark = pytest.mark.e2e

CONEXAO = "opcsim-sv"
BLOCO = "sv"
TS_SV = 1  # Ts dos flows (s); o período dos modelos sintéticos é o mesmo (1 varredura por passo)
PESOS = [0.02, 0.5]  # w do PLS: uma contribuição pequena da senoide (0..100) e uma da estática (42)
B_A = 1.5
B_B = 51.5  # 50 de distância de B_A: um valor jamais é confundido com o do outro modelo
TOLERANCIA = 1e-3
SEQUENCE_LENGTH = 10  # K do LSTM: sem pré-aquecimento seriam 10 varreduras até o 1o valor

FLOW_01, FLOW_02, FLOW_03, FLOW_04 = "sv01", "sv02", "sv03", "sv04"
MODELO_PLS_A, MODELO_PLS_B, MODELO_ESN, MODELO_LSTM = "pls-a", "pls-b", "esn", "lstm"


@dataclass(frozen=True, slots=True)
class ProjetoSv:
    """Projeto importado e ativo: ids resolvidos por nome depois do import (ids são do banco)."""

    project_id: int
    conn_id: int
    tag_ids: list[int]  # na ordem das portas do sensor: IN1 = senoide, IN2 = estática
    flows: dict[str, int]
    modelos: dict[str, int]


# --------------------------------------------------------------------------------------
# O arquivo de projeto (spec F6 §2.1-4 + RF-590): conexão, tags, 4 flows, 4 modelos
# --------------------------------------------------------------------------------------


def _grafo(tipo: str) -> dict:
    """`r1` (senoide) e `r2` (estática) alimentam `IN1`/`IN2` do sensor, na forma do bundle."""
    return montar_grafo(
        [
            bloco("r1", "opc_read", 1, tag_ref={"connection": CONEXAO, "tag": "sine"}),
            bloco("r2", "opc_read", 2, tag_ref={"connection": CONEXAO, "tag": "static"}),
            bloco(BLOCO, tipo, 3, n_inputs=2),
        ],
        [aresta("r1", "out", BLOCO, "IN1"), aresta("r2", "out", BLOCO, "IN2")],
    )


def _modelo(nome: str, artefato: tuple[ModelMeta, bytes]) -> BundleSoftSensorModel:
    """Modelo do bundle. `input_tags` em ordem de porta: é o que o pré-aquecimento usa para
    achar a série das entradas em `samples` (sem elas o bloco sobe sem histórico)."""
    meta, pesos = artefato
    return BundleSoftSensorModel(
        name=nome,
        method=meta.method,
        period_s=meta.period_s,
        n_inputs=len(meta.inputs),
        meta=meta.model_dump(mode="json"),
        weights_b64=base64.b64encode(pesos).decode("ascii"),
        input_tags=[
            BundleTagRef(connection=CONEXAO, tag="sine"),
            BundleTagRef(connection=CONEXAO, tag="static"),
        ],
    )


def _bundle(endpoint: str, nome: str) -> dict[str, Any]:
    periodo = float(TS_SV)
    modelos = [
        _modelo(MODELO_PLS_A, synthetic.pls(PESOS, B_A, period_s=periodo)),
        _modelo(MODELO_PLS_B, synthetic.pls(PESOS, B_B, period_s=periodo)),  # sem vínculo (SV-02)
        _modelo(MODELO_ESN, synthetic.esn(2, period_s=periodo)),  # sem vínculo (SV-04)
        _modelo(
            MODELO_LSTM,
            synthetic.lstm(2, sequence_length=SEQUENCE_LENGTH, period_s=periodo),
        ),
    ]
    flows = {
        FLOW_01: "soft_sensor_pls",
        FLOW_02: "soft_sensor_pls",
        FLOW_03: "soft_sensor_lstm",
        FLOW_04: "soft_sensor_pls",
    }
    vinculos = [  # só o modelo DESEJADO viaja (ADR-046 D6): active/candidate são do runtime
        BundleSoftSensorBinding(flow=FLOW_01, block_id=BLOCO, model=MODELO_PLS_A),
        BundleSoftSensorBinding(flow=FLOW_02, block_id=BLOCO, model=MODELO_PLS_A),
        BundleSoftSensorBinding(flow=FLOW_03, block_id=BLOCO, model=MODELO_LSTM),
        BundleSoftSensorBinding(flow=FLOW_04, block_id=BLOCO, model=MODELO_PLS_A),
    ]
    bundle = ProjectBundle(
        schema_version=1,
        exported_at=datetime.now(UTC),
        project=BundleProject(name=nome, description="L2 do sensor virtual (SV-1)"),
        connections=[BundleConnection(name=CONEXAO, endpoint=endpoint)],
        tags=[
            BundleTag(
                connection=CONEXAO, name="sine", node_id=NODE_SINE, direction="r", data_type="float"
            ),
            BundleTag(
                connection=CONEXAO,
                name="static",
                node_id=NODE_STATIC,
                direction="r",
                data_type="float",
            ),
        ],
        flows=[
            BundleFlow(name=nome_flow, ts_seconds=TS_SV, graph=_grafo(tipo))
            for nome_flow, tipo in flows.items()
        ],
        soft_sensor_models=modelos,
        soft_sensor_bindings=vinculos,
    )
    return bundle.model_dump(mode="json")


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def assinar_status(redis_bus: redis.Redis) -> Iterator[Any]:
    yield from assinantes_de_status(redis_bus)


@pytest.fixture(scope="module")
def projeto_sv(admin: httpx.Client, opcsim_standalone: str) -> Iterator[ProjetoSv]:
    """Importa o arquivo, ativa o projeto (o import o deixa inativo, e `/api/softsensor/*` só
    enxerga o ativo) e espera a conexão subir. Teardown: devolve a ativação à sentinela e
    exclui (excluir o ativo é 409); os flows já foram parados pelos próprios cenários."""
    nome = f"sv1-{RUN_ID}"
    r = admin.post(
        "/api/projects/import", json={"name": nome, "bundle": _bundle(opcsim_standalone, nome)}
    )
    assert r.status_code == 201, f"import do projeto SV-1: HTTP {r.status_code} {r.text}"
    project_id = int(r.json()["project"]["id"])
    try:
        ativar_projeto(admin, project_id)
        conn_id = next(
            int(c["id"])
            for c in admin.get("/api/connections").json()
            if c["project_id"] == project_id
        )
        tags = {
            t["name"]: int(t["id"])
            for t in admin.get("/api/tags").json()
            if t["connection_id"] == conn_id
        }
        flows = {
            f["name"]: int(f["id"])
            for f in admin.get("/api/flows").json()
            if f["project_id"] == project_id
        }
        r = admin.get("/api/softsensor/models")
        assert r.status_code == 200, f"GET /api/softsensor/models: HTTP {r.status_code} {r.text}"
        modelos = {m["name"]: int(m["id"]) for m in r.json()}
        assert set(modelos) == {MODELO_PLS_A, MODELO_PLS_B, MODELO_ESN, MODELO_LSTM}, modelos
        esperar_conexao(conn_id)
        yield ProjetoSv(
            project_id=project_id,
            conn_id=conn_id,
            tag_ids=[tags["sine"], tags["static"]],
            flows=flows,
            modelos=modelos,
        )
    finally:
        ativar_projeto(admin, id_da_sentinela(admin))
        admin.delete(f"/api/projects/{project_id}")


@pytest.fixture
def implantar(admin: httpx.Client) -> Iterator[Callable[[int], None]]:
    """Deploy do flow; o teardown para e espera a parada (excluir o projeto com flow rodando
    daria 409, e varredura órfã continuaria lendo as tags do cenário seguinte)."""
    implantados: list[int] = []

    def implantar_flow(flow_id: int) -> None:
        deploy(admin, flow_id)
        implantados.append(flow_id)

    try:
        yield implantar_flow
    finally:
        for flow_id in reversed(implantados):
            admin.post(f"/api/flows/{flow_id}/stop")
            aguardar_parado(flow_id)


# --------------------------------------------------------------------------------------
# Leitura de estado
# --------------------------------------------------------------------------------------


def _estimativa(status: dict[str, Any], b: float) -> float:
    """`w·x + b` com as entradas do MESMO `flow.status` do `out` (as portas `r1`/`r2`)."""
    x1, x2 = valor(status, "r1", "out"), valor(status, "r2", "out")
    assert x1 is not None and x2 is not None, "entrada do sensor sem valor na varredura"
    return PESOS[0] * float(x1) + PESOS[1] * float(x2) + b


def _ativacao(flow_id: int, model_id: int) -> Callable[[dict[str, Any]], bool]:
    """Predicado do evento `soft_sensor_model_activated`: origem `flow-runtime` (sem bloco no
    `origin`), então o flow, o bloco e o modelo vêm do payload."""

    def casa(evento: dict[str, Any]) -> bool:
        payload = evento.get("payload", {})
        return (
            evento.get("origin") == "flow-runtime"
            and payload.get("kind") == KIND_SOFT_SENSOR_MODEL_ACTIVATED
            and payload.get("flow_id") == flow_id
            and payload.get("block_id") == BLOCO
            and payload.get("model_id") == model_id
        )

    return casa


# --------------------------------------------------------------------------------------
# Cenários
# --------------------------------------------------------------------------------------


def test_e2e_sv_01_import_deploy_e_estimativa(
    admin: httpx.Client, projeto_sv: ProjetoSv, assinar_status: Any, implantar: Any
) -> None:
    """RF-581/582/590: import com modelo vinculado, deploy e `out` GOOD igual a `w·x + b` em até
    5 varreduras; o vínculo na API mostra o modelo em uso igual ao desejado."""
    flow_id = projeto_sv.flows[FLOW_01]
    esperar_historico(admin, projeto_sv.tag_ids, span_s=0)
    estado = assinar_status(flow_id)
    implantar(flow_id)

    status = esperar_saida_boa(estado, BLOCO, ate=5)
    assert porta(status, BLOCO, "out")["v"] == pytest.approx(
        _estimativa(status, B_A), abs=TOLERANCIA
    )

    def vinculo_em_dia() -> dict[str, Any] | None:
        vinculo = bloco_softsensor(admin, flow_id, BLOCO)
        em_uso = vinculo["active_model_id"]
        return vinculo if em_uso is not None and em_uso == vinculo["desired_model_id"] else None

    vinculo = esperar_ate(
        vinculo_em_dia, timeout=10.0, descricao="active_model_id igual a desired_model_id"
    )
    assert vinculo["desired_model_id"] == projeto_sv.modelos[MODELO_PLS_A]
    assert vinculo["candidate_model_id"] is None


def test_e2e_sv_02_troca_de_modelo_em_execucao(
    admin: httpx.Client,
    projeto_sv: ProjetoSv,
    assinar_status: Any,
    eventos: EventStream,
    implantar: Any,
) -> None:
    """RF-584: trocar o modelo com o flow rodando vira o novo `active_model_id` e o evento
    `soft_sensor_model_activated` em até 10 s, sem nenhuma amostra de `out` fora de GOOD."""
    flow_id = projeto_sv.flows[FLOW_02]
    modelo_b = projeto_sv.modelos[MODELO_PLS_B]
    esperar_historico(admin, projeto_sv.tag_ids, span_s=0)
    estado = assinar_status(flow_id)
    implantar(flow_id)

    status = esperar_saida_boa(estado, BLOCO, ate=5)
    assert porta(status, BLOCO, "out")["v"] == pytest.approx(
        _estimativa(status, B_A), abs=TOLERANCIA
    )
    assert (
        bloco_softsensor(admin, flow_id, BLOCO)["active_model_id"]
        == projeto_sv.modelos[MODELO_PLS_A]
    )

    r = admin.post(f"/api/operate/{flow_id}/{BLOCO}/model", json={"model_id": modelo_b})
    assert r.status_code == 202, f"POST /operate model: HTTP {r.status_code} {r.text}"

    # Coleta a `out` de cada varredura até aparecer o valor do modelo B (o `b` difere em 50).
    # Varreduras antigas ainda na fila do assinante entram na coleta: são do modelo A e GOOD.
    amostras = [porta(status, BLOCO, "out")]
    limite = time.monotonic() + 10.0
    while True:
        restante = limite - time.monotonic()
        if restante <= 0:
            pytest.fail(f"`out` não passou ao modelo B em 10 s: {amostras[-5:]}")
        status = estado.esperar(
            de_varredura, timeout=restante, descricao="varredura da troca de modelo"
        )
        amostras.append(porta(status, BLOCO, "out"))
        v = amostras[-1]["v"]
        if v is not None and abs(v - _estimativa(status, B_B)) <= TOLERANCIA:
            break

    assert all(a["quality"] == Quality.GOOD for a in amostras), (
        f"a troca derrubou a qualidade de `out`: {amostras}"
    )
    esperar_ate(
        lambda: bloco_softsensor(admin, flow_id, BLOCO)["active_model_id"] == modelo_b,
        timeout=5.0,
        descricao="active_model_id passar ao modelo B",
    )
    eventos.esperar(
        _ativacao(flow_id, modelo_b),
        timeout=5.0,
        descricao="evento soft_sensor_model_activated do modelo B",
    )


def test_e2e_sv_03_prewarm_pelo_historico(
    admin: httpx.Client, projeto_sv: ProjetoSv, assinar_status: Any, implantar: Any
) -> None:
    """RF-583: o LSTM de K=10 implantado depois de 20 s de histórico sai GOOD em até 3 varreduras
    (sem o pré-aquecimento de `samples` seriam 10)."""
    flow_id = projeto_sv.flows[FLOW_03]
    esperar_historico(admin, projeto_sv.tag_ids, span_s=20.0)
    estado = assinar_status(flow_id)
    implantar(flow_id)

    esperar_saida_boa(estado, BLOCO, ate=3)


def test_e2e_sv_04_recusa_de_modelo_de_outro_metodo(
    admin: httpx.Client, projeto_sv: ProjetoSv
) -> None:
    """RF-584: ESN num bloco PLS é 422 com o método na mensagem, e o vínculo não muda."""
    flow_id = projeto_sv.flows[FLOW_04]
    antes = blocos_softsensor(admin)

    r = admin.post(
        f"/api/operate/{flow_id}/{BLOCO}/model", json={"model_id": projeto_sv.modelos[MODELO_ESN]}
    )

    assert r.status_code == 422, f"POST /operate model: HTTP {r.status_code} {r.text}"
    assert "é ESN" in r.json()["detail"], r.text
    assert blocos_softsensor(admin) == antes
