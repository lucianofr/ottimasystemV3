"""Verificação independente (SUPERVISOR): propagação de qualidade OPC-UA já existente.

Prova os 4 itens do pedido original SEM mudança de feature — só exercita o sistema rodando:

QE-1  Tag OPC lida publica valor+quality a cada ciclo (quality=0 em normalidade).
QE-2  Node com StatusCode Bad => ok=False propaga OPC-Read -> Filtro -> MPC;
      MPC pula o solve, congela as MVs, publica input_valid=false e mpc_input_invalid.
QE-3  Node volta a Good => MPC volta a input_valid=true e resolve de novo (reversível).
QE-4  Tag calculada com 2 entradas: UMA entrada Bad força quality=2 na publicada (pior-de-N).
QE-5  DV com Bad NÃO invalida o MPC (ADR-038): input_valid segue true, a DV reportada
      congela no último valor bom e volta a seguir a tag quando a qualidade volta.

O cenário usa um bloco MPC mínimo (1 MV direta sem readback, 1 CV self-reg) armado até
AUTO, e um flow com watchdog habilitado — exigência do deploy, não a feature sob teste.

Restauro: o fixture captura o projeto ativo (o "Elkem") e os flows dele em `running`, e no
teardown reativa o projeto, reimplanta esses flows e espera o runtime confirmar — a API não
expõe "desativar", e ativar outro projeto para tudo na mesma transação.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import redis
from asyncua import Client, ua

from opcsim import NODE_SINE, NODE_STATIC, NODE_W_FLOAT, NODE_WD_FROM_SYSTEM, NODE_WD_TO_SYSTEM
from ottima_core.bus import KIND_MPC_INPUT_INVALID

from .conftest import (
    OPCSIM_HOST_URL,
    RUN_ID,
    EventStream,
    _health_do_runtime,
    armar_auto_com_retentativa,
    armar_remoto_direto,
    assinar_mpc_state,
    deploy_flow,
    esperar_ate,
    esperar_conexao,
    esperar_flow_watchdog,
    evento_mpc,
    valor_unico,
)

pytestmark = pytest.mark.e2e

# O simulador OPC-UA saiu da stack do compose: o conftest o sobe standalone no host e
# entrega o endpoint de dentro da rede (via gateway da rede `ottima_*`).

SUFIXO = f"qe-quality-{RUN_ID}"

# MPC mínimo — Ts_flow=1 s, multiplier=2 => Ts_mpc=2 s, Np=ceil(10/2)=5.
TS_FLOW = 1.0
MULTIPLIER = 2
TS_MPC = TS_FLOW * MULTIPLIER
GANHO_CV = 1.0
TAU1_CV = 2.0
TAU2_CV = 0.5
TSS_MALHA = 10.0
LIMITES_MV = {"min": 0.0, "max": 100.0}
LIMITES_SP_CV = {"min": 0.0, "max": 100.0}


@pytest.fixture(scope="session")
def redis_bus() -> Iterator[redis.Redis]:
    """O `redis_bus` do conftest usa a porta do overlay e2e (6399), que NÃO está publicada
    (o stack roda sem o overlay). Fala direto com o container pela IP da rede `ottima_*`."""
    ip = subprocess.run(
        [
            "docker",
            "inspect",
            "ottima-redis-1",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()
    assert ip, "não achei o IP do container ottima-redis-1"
    cliente = redis.Redis(host=ip, port=6379, decode_responses=True)
    assert cliente.ping(), "redis do stack não responde"
    yield cliente
    cliente.close()



def _historico(
    admin: httpx.Client, tag_id: int, *, start: datetime | None = None
) -> dict[str, Any]:
    params: dict[str, str] = {"tag_ids": str(tag_id)}
    if start is not None:
        params["start"] = start.isoformat()
    r = admin.get("/api/history", params=params)
    assert r.status_code == 200, f"/api/history falhou: HTTP {r.status_code} {r.text}"
    corpo = r.json()
    assert len(corpo["series"]) == 1, "uma série por tag pedida, sempre"
    return corpo["series"][0]


def _escrever_status(node_id: str, *, valor: float, ruim: bool) -> None:
    """Escreve um DataValue completo: valor bom OU StatusCode Bad (sob status ruim o servidor
    asyncua anula o Variant — OPC-UA Part 4 §7.7.1 — e é o STATUS que o opc-worker lê)."""

    async def _run() -> None:
        status = ua.StatusCodes.BadSensorFailure if ruim else ua.StatusCodes.Good
        dv = ua.DataValue(
            ua.Variant(valor, ua.VariantType.Double),
            StatusCode=ua.StatusCode(status),
        )
        async with Client(url=OPCSIM_HOST_URL, timeout=10) as client:
            await client.get_node(node_id).write_value(dv)

    import asyncio

    asyncio.run(_run())


def _config_mpc_minimo() -> dict[str, Any]:
    """1 MV direta (sem PID, sem readback — sempre RCAS_OK), 1 CV self-reg, 1 DV."""
    return {
        "name": "MPC QE",
        "multiplier": MULTIPLIER,
        "variables": {
            "mvs": [
                {
                    "id": "mv_1",
                    "name": "MV direta",
                    "eu": "%",
                    "limits": dict(LIMITES_MV),
                    "max_rate": 5.0,
                    "initial_value": 0.0,
                }
            ],
            "cvs": [
                {
                    "id": "cv_1",
                    "name": "CV filtrada",
                    "eu": "C",
                    "kind": "selfreg",
                    "tss": TSS_MALHA,
                    "weight": 1.0,
                    "sp_limits": dict(LIMITES_SP_CV),
                }
            ],
            "constraints": [],
            "dvs": [
                {
                    "id": "dv_1",
                    "name": "DV de carga",
                    "eu": "m3/h",
                }
            ],
        },
        "models": {
            "cv_1": {
                "mv_1": {
                    "enabled": True,
                    "params": {"K": GANHO_CV, "tau1": TAU1_CV, "tau2": TAU2_CV, "theta": 0.0},
                },
                "dv_1": {
                    "enabled": True,
                    "params": {"K": 0.5, "tau1": 5.0, "tau2": 0.0, "theta": 0.0},
                },
            }
        },
    }


def _grafo_qe(tag_senso: int, tag_dv: int) -> dict[str, Any]:
    """OPC-Read(node de teste) -> Filtro 1ª ordem -> MPC(cv_1); OPC-Read -> MPC(dv_1).

    `exec_order` contíguo 1..4 (RF-307): a leitura da DV entra direto no MPC, sem filtro —
    o cenário QE-5 corrompe exatamente a tag que alimenta a porta da DV."""
    return {
        "nodes": [
            {
                "id": "leitura",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 1, "tag_id": tag_senso},
            },
            {
                "id": "dv_leitura",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 2, "tag_id": tag_dv},
            },
            {
                "id": "filtro",
                "type": "first_order",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 3, "tau": 2.0},
            },
            {
                "id": "mpc_qe",
                "type": "mpc",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 4, **_config_mpc_minimo()},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "leitura",
                "sourceHandle": "out",
                "target": "filtro",
                "targetHandle": "in",
            },
            {
                "id": "e2",
                "source": "filtro",
                "sourceHandle": "out",
                "target": "mpc_qe",
                "targetHandle": "cv_1",
            },
            {
                "id": "e3",
                "source": "dv_leitura",
                "sourceHandle": "out",
                "target": "mpc_qe",
                "targetHandle": "dv_1",
            },
        ],
    }


@pytest.fixture(scope="session")
def ambiente_qe(admin: httpx.Client, opcsim_standalone: str) -> Iterator[dict[str, Any]]:
    """Projeto de teste ativo + conexão ao opcsim standalone + tags + flow com watchdog.

    Captura o projeto ativo (Elkem) e os flows dele em `running`; o teardown reativa o
    projeto, reimplanta esses flows e espera o runtime confirmar.
    """
    r = admin.get("/api/projects")
    assert r.status_code == 200
    anterior = next((p for p in r.json() if p["is_active"]), None)
    assert anterior is not None, "nenhum projeto ativo — nada para restaurar depois"

    r = admin.get("/api/flows", params={"project_id": anterior["id"]})
    assert r.status_code == 200
    flows_ativos_anteriores = [f["id"] for f in r.json() if f.get("desired_state") == "running"]

    projeto_id: int | None = None
    flow_id: int | None = None
    tag_calc: int | None = None
    r = admin.post(
        "/api/projects",
        json={"name": f"qe-quality-{SUFIXO}", "description": "SUPERVISOR E2E (descartável)"},
    )
    assert r.status_code == 201, f"criação do projeto falhou: HTTP {r.status_code} {r.text}"
    projeto_id = int(r.json()["id"])
    try:
        assert admin.post(f"/api/projects/{projeto_id}/activate").status_code == 200
        r = admin.post(
            "/api/connections",
            json={
                "project_id": projeto_id,
                "name": f"opcsim-{SUFIXO}",
                "endpoint": opcsim_standalone,
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
            },
        )
        assert r.status_code == 201, f"criação da conexão falhou: HTTP {r.status_code} {r.text}"
        conn_id = int(r.json()["id"])

        def criar_tag(nome: str, node_id: str, direcao: str) -> int:
            r = admin.post(
                "/api/tags",
                json={
                    "connection_id": conn_id,
                    "name": f"{nome}-{valor_unico()}",
                    "node_id": node_id,
                    "direction": direcao,
                    "data_type": "float",
                },
            )
            assert r.status_code == 201, f"criação da tag {nome}: HTTP {r.status_code} {r.text}"
            return int(r.json()["id"])

        tag_senso = criar_tag("senso", NODE_STATIC, "r")  # node que vamos corromper
        tag_dv = criar_tag("dv", NODE_W_FLOAT, "r")  # node da DV — corrompido só no QE-5
        tag_aux = criar_tag("aux", NODE_SINE, "r")  # entrada sempre boa da tag calculada

        r = admin.post(
            "/api/calculated-tags",
            json={
                "project_id": projeto_id,
                "name": f"soma-qe-{valor_unico()}",
                "eu": "u",
                "period_seconds": 1,
                "code": "OUT = IN1 + IN2\n",
                "input_tag_ids": [tag_senso, tag_aux],
            },
        )
        assert r.status_code == 201, f"tag calculada falhou: HTTP {r.status_code} {r.text}"
        tag_calc = int(r.json()["id"])

        r = admin.post(
            "/api/flows",
            json={"project_id": projeto_id, "name": f"qe-{SUFIXO}", "ts_seconds": TS_FLOW},
        )
        assert r.status_code == 201, f"criação do flow falhou: HTTP {r.status_code} {r.text}"
        flow_id = int(r.json()["id"])
        r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": _grafo_qe(tag_senso, tag_dv)})
        assert r.status_code == 200, f"PUT do grafo falhou: HTTP {r.status_code} {r.text}"
        r = admin.put(
            f"/api/flows/{flow_id}",
            json={
                "watchdog_enabled": True,
                "watchdog_connection_id": conn_id,
                "watchdog_read_node_id": NODE_WD_TO_SYSTEM,
                "watchdog_write_node_id": NODE_WD_FROM_SYSTEM,
                "watchdog_period_ms": 1000,
            },
        )
        assert r.status_code == 200, f"watchdog do flow falhou: HTTP {r.status_code} {r.text}"

        esperar_conexao(conn_id)
        esperar_flow_watchdog(flow_id, conn_id)
        yield {
            "project_id": projeto_id,
            "conn_id": conn_id,
            "flow_id": flow_id,
            "tag_senso": tag_senso,
            "tag_dv": tag_dv,
            "tag_aux": tag_aux,
            "tag_calc": tag_calc,
        }
    finally:
        if flow_id is not None:
            admin.post(f"/api/flows/{flow_id}/stop")

            def parado() -> bool:
                saude = _health_do_runtime()
                if saude is None:
                    return True
                fluxo = saude.get("flows", {}).get(str(flow_id))
                return fluxo is None or fluxo["state"] != "running"

            esperar_ate(parado, timeout=60.0, intervalo=1.0, descricao=f"flow {flow_id} parado")
        # Reativa o projeto anterior (desativa o nosso). A tag calculada precisa ser
        # removida ANTES do projeto: `calculated_tag_inputs.source_tag_id` é RESTRICT, e o
        # CASCADE do projeto bateria na FK com a linha de entrada ainda viva (HTTP 500).
        if tag_calc is not None:
            admin.delete(f"/api/calculated-tags/{tag_calc}")
        admin.post(f"/api/projects/{anterior['id']}/activate")
        if projeto_id is not None:
            r = admin.delete(f"/api/projects/{projeto_id}")
            assert r.status_code == 204, (
                f"remoção do projeto de teste: HTTP {r.status_code} {r.text}"
            )
        # A ativação do nosso projeto parou os flows do anterior (desired_state -> stopped
        # na mesma transação): reimplanta cada um e espera o runtime confirmar.
        for fid in flows_ativos_anteriores:
            admin.post(f"/api/flows/{fid}/deploy")

        def rodando_de_novo() -> bool | None:
            saude = _health_do_runtime()
            if saude is None:
                return None
            flows = saude.get("flows", {})
            return all(
                flows.get(str(fid), {}).get("state") == "running" for fid in flows_ativos_anteriores
            )

        esperar_ate(
            rodando_de_novo,
            timeout=120.0,
            intervalo=2.0,
            descricao=f"flows {flows_ativos_anteriores} rodando de novo",
        )


def test_qe1_tag_opc_publica_valor_e_quality_bom(
    admin: httpx.Client, ambiente_qe: dict[str, Any]
) -> None:
    """QE-1: a tag de leitura publica valor+quality=0 a cada ciclo (via /api/history)."""
    marco = datetime.now(UTC)

    def serie_boa() -> dict[str, Any] | None:
        s = _historico(admin, ambiente_qe["tag_senso"], start=marco)
        return s if len(s["t"]) >= 3 else None

    serie = esperar_ate(serie_boa, timeout=45.0, intervalo=2.0, descricao="amostras boas da tag")
    assert set(serie["q"]) == {0}, f"esperado quality=0 em todas as amostras: {serie['q']}"
    assert all(isinstance(v, float) for v in serie["v"])


def test_qe2_qe3_bad_invalida_mpc_e_good_restaura(
    admin: httpx.Client,
    ambiente_qe: dict[str, Any],
    eventos: EventStream,
) -> None:
    """QE-2/QE-3: Bad => solve pulado, MV congelada, input_valid=false, mpc_input_invalid;
    Good => input_valid=true e solve volta (last_solve_ms avança)."""
    flow_id = ambiente_qe["flow_id"]
    tag_senso = ambiente_qe["tag_senso"]

    deploy_flow(admin, flow_id)

    with assinar_mpc_state(admin, flow_id, "mpc_qe") as fluxo:
        # 0) sanidade + arme até AUTO (LOCAL não dispara solve)
        fluxo.esperar(
            lambda e: e["status"].get("solver") != "building",
            timeout=90.0,
            descricao="host do MPC pronto",
        )
        armar_remoto_direto(admin, fluxo, flow_id, "mpc_qe")
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc_qe")
        fluxo.esperar(
            lambda e: e["modes"]["man_auto"] == "auto" and e["status"]["input_valid"],
            timeout=30.0,
            descricao="MPC em AUTO com entrada válida",
        )

        # primeiro solve real (last_solve_ms populado) — âncora da prova de congelamento
        def solve_vivo() -> dict[str, Any] | None:
            e = fluxo.proxima(timeout=TS_MPC + 10.0, descricao="quadra com solve")
            return e if e["status"].get("last_solve_ms") else None

        esperar_ate(solve_vivo, timeout=60.0, intervalo=1.0, descricao="primeiro solve aplicado")

        # 1) corrompe o node de origem
        marco_bad = datetime.now(UTC)
        _escrever_status(NODE_STATIC, valor=0.0, ruim=True)

        fluxo.esperar(
            lambda e: e["status"]["input_valid"] is False,
            timeout=45.0,
            descricao="mpc.state com input_valid=false após o Bad",
        )
        evento = eventos.esperar(
            evento_mpc(KIND_MPC_INPUT_INVALID, flow_id, "mpc_qe"),
            timeout=30.0,
            descricao="evento mpc_input_invalid",
        )
        assert evento["payload"]["kind"] == KIND_MPC_INPUT_INVALID

        # Congelamento: com entrada inválida o gate segura `_run_frontier` (spec §4.6), então
        # nenhum solve NOVO é despachado. UM solve já despachado antes do Bad ainda pode
        # pousar na primeira fronteira ruim (IPC assíncrono) — por isso a prova é a CAUDA da
        # janela estável: `last_solve_ms` E o valor da porta da MV constantes, com o bloco
        # reportando input_valid=false em todos os quadros.
        janela = fluxo.coletar(
            quantidade=6,
            timeout=TS_MPC * 6 + 15.0,
            descricao="janela com entrada ruim",
        )
        assert all(e["status"]["input_valid"] is False for e in janela), (
            f"algum quadro voltou a válido durante o Bad: "
            f"{[e['status']['input_valid'] for e in janela]}"
        )
        cauda = janela[-3:]
        ms_cauda = [e["status"].get("last_solve_ms") for e in cauda]
        mv_cauda = [e["vars"]["mv_1"]["v"] for e in cauda]
        assert len(set(ms_cauda)) == 1, f"solve continuou avançando em entrada inválida: {ms_cauda}"
        assert len(set(mv_cauda)) == 1, f"MV variou em entrada inválida (não congelou): {mv_cauda}"
        ms_congelado = ms_cauda[-1]

        # 2) cura o node: estado volta a válido E o solve recomeça
        _escrever_status(NODE_STATIC, valor=42.0, ruim=False)
        fluxo.esperar(
            lambda e: e["status"]["input_valid"] is True,
            timeout=45.0,
            descricao="mpc.state com input_valid=true após o Good",
        )

        def solve_novo() -> float | None:
            e = fluxo.proxima(timeout=TS_MPC + 10.0, descricao="fronteira pós-cura")
            ms = e["status"].get("last_solve_ms")
            if e["status"]["input_valid"] and ms and ms != ms_congelado:
                return ms
            return None

        ms_novo = esperar_ate(solve_novo, timeout=60.0, intervalo=1.0, descricao="solve retomado")
        assert ms_novo is not None, "solve não recomeçou após a cura"

    # 3) prova pelo histórico da tag: quality=2 durante o Bad, quality=0 depois da cura
    serie = _historico(admin, tag_senso, start=marco_bad)
    assert 2 in serie["q"], f"esperado amostras quality=2 após o Bad: {serie['q']}"

    marco_cura = datetime.now(UTC)

    def serie_curada() -> list[int] | None:
        s = _historico(admin, tag_senso, start=marco_cura)
        return s["q"] if len(s["t"]) >= 3 else None

    curadas = esperar_ate(serie_curada, timeout=45.0, intervalo=2.0, descricao="tag curada")
    assert set(curadas[-3:]) == {0}, f"esperado quality=0 após a cura: {curadas}"


def test_qe4_tag_calculada_pior_de_n(admin: httpx.Client, ambiente_qe: dict[str, Any]) -> None:
    """QE-4: com UMA entrada Bad, a tag calculada publica quality=2 mesmo com a outra boa."""
    tag_calc = ambiente_qe["tag_calc"]

    # sanidade: a tag calculada publicando boa (pior-de-N com tudo bom = 0)
    marco = datetime.now(UTC)

    def serie_calc() -> dict[str, Any] | None:
        s = _historico(admin, tag_calc, start=marco)
        return s if len(s["t"]) >= 2 else None

    serie = esperar_ate(
        serie_calc, timeout=90.0, intervalo=2.0, descricao="tag calculada publicando"
    )
    assert set(serie["q"]) == {0}, f"tag calculada deveria nascer boa: {serie['q']}"

    marco_bad = datetime.now(UTC)
    _escrever_status(NODE_STATIC, valor=0.0, ruim=True)

    def serie_ruim() -> list[int] | None:
        s = _historico(admin, tag_calc, start=marco_bad)
        ruins = [q for q in s["q"] if q == 2]
        return ruins if len(ruins) >= 2 else None

    ruins = esperar_ate(
        serie_ruim, timeout=60.0, intervalo=2.0, descricao="tag calculada em quality=2"
    )
    assert len(ruins) >= 2

    # cura: pior-de-N volta a good quando a entrada ruim volta
    _escrever_status(NODE_STATIC, valor=42.0, ruim=False)
    marco_cura = datetime.now(UTC)

    def serie_curada() -> list[int] | None:
        s = _historico(admin, tag_calc, start=marco_cura)
        return s["q"] if len(s["t"]) >= 3 else None

    curadas = esperar_ate(
        serie_curada, timeout=60.0, intervalo=2.0, descricao="tag calculada curada"
    )
    assert set(curadas[-3:]) == {0}, f"esperado quality=0 após a cura: {curadas}"


def test_qe5_dv_bad_congela_internamente_e_good_retoma(
    admin: httpx.Client, ambiente_qe: dict[str, Any]
) -> None:
    """QE-5 (ADR-038): DV Bad => input_valid SEGUE true, a DV reportada congela no último
    valor bom e o solve continua (feedforward parado não impacta o algoritmo); Good =>
    a DV volta a seguir a tag."""
    flow_id = ambiente_qe["flow_id"]

    deploy_flow(admin, flow_id)

    with assinar_mpc_state(admin, flow_id, "mpc_qe") as fluxo:
        # 0) sanidade + arme até AUTO (idempotente se o QE-2 já deixou armado)
        fluxo.esperar(
            lambda e: e["status"].get("solver") != "building",
            timeout=90.0,
            descricao="host do MPC pronto",
        )
        armar_remoto_direto(admin, fluxo, flow_id, "mpc_qe")
        armar_auto_com_retentativa(admin, fluxo, flow_id, "mpc_qe")
        fluxo.esperar(
            lambda e: e["modes"]["man_auto"] == "auto" and e["status"]["input_valid"],
            timeout=30.0,
            descricao="MPC em AUTO com entrada válida",
        )

        # 1) DV boa com valor distintivo: a DV reportada segue a tag
        _escrever_status(NODE_W_FLOAT, valor=25.0, ruim=False)
        fluxo.esperar(
            lambda e: abs(e["vars"]["dv_1"]["v"] - 25.0) < 0.01,
            timeout=45.0,
            descricao="DV boa seguindo a tag (25.0)",
        )

        # 2) corrompe o node da DV: o bloco NÃO invalida, a DV congela, o solve continua
        _escrever_status(NODE_W_FLOAT, valor=0.0, ruim=True)
        janela = fluxo.coletar(
            quantidade=6,
            timeout=TS_MPC * 6 + 15.0,
            descricao="janela com a DV ruim",
        )
        assert all(e["status"]["input_valid"] is True for e in janela), (
            f"DV ruim não pode invalidar o bloco: "
            f"{[e['status']['input_valid'] for e in janela]}"
        )
        dv_cauda = [e["vars"]["dv_1"]["v"] for e in janela]
        assert all(abs(v - 25.0) < 0.01 for v in dv_cauda), (
            f"DV reportada precisa congelar no último valor bom durante o Bad: {dv_cauda}"
        )
        solves = {e["status"].get("last_solve_ms") for e in janela}
        assert len(solves) >= 2, f"solve precisa continuar rodando com DV ruim: {solves}"

        # 3) cura: a DV volta a seguir a tag (valor novo flui)
        _escrever_status(NODE_W_FLOAT, valor=33.0, ruim=False)
        fluxo.esperar(
            lambda e: abs(e["vars"]["dv_1"]["v"] - 33.0) < 0.01,
            timeout=45.0,
            descricao="DV volta a seguir a tag após a cura (33.0)",
        )
