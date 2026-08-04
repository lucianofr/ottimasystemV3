"""Camada L2 da F3 (spec §7.2): motor de varredura, blocos e os dois cenários de aceite.

Cobre E2E-F3-01..06 e E2E-F3-10 — validação de grafo, cadeia Read→Script→Write, o aceite de
jitter (PRD §8-F3), o aceite de hot-swap (RF-304), o atraso do `exec_order` invertido, as duas
falhas de script do RF-514 e a supressão de escrita da §3.2. Os cenários de ciclo de vida
(E2E-F3-07..09) estão em `test_f3_lifecycle.py`.

Dois deles medem número, não só comportamento: o E2E-F3-03 mede o desvio de fronteira de um
flow Script+TFS a Ts=0,5 s ao longo de 120 s, e o E2E-F3-04 mede em quantas varreduras uma
edição entra em vigor sem o flow passar por `stopped`.
"""

import math
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import redis

from opcsim import NODE_MIRROR_FLOAT
from ottima_core.bus import (
    KIND_FLOW_DEPLOYED,
    KIND_SCRIPT_ERROR,
    KIND_SCRIPT_TIMEOUT,
    KIND_WRITE_SUPPRESSED,
)

from .conftest import (
    RUN_ID,
    Ambiente,
    EventStream,
    OpcSim,
    esperar_ate,
    esperar_conexao,
    valor_unico,
)
from .f3_support import (
    AMOSTRAS_JITTER,
    CODE_CONTADOR,
    CODE_ERRO,
    CODE_TIMEOUT_APOS_TRES,
    JANELA_JITTER_S,
    KI,
    LIMITE_P95_MS,
    TS,
    aresta,
    assinantes_de_status,
    bloco,
    de_varredura,
    deploy,
    esperar_todos,
    evento_de_bloco,
    evento_de_flow,
    fabrica_de_flows,
    grafo_script_tfs,
    montar_grafo,
    porta,
    reprovar,
    salvar,
    valor,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def assinar_status(redis_bus: redis.Redis) -> Iterator[Any]:
    yield from assinantes_de_status(redis_bus)


@pytest.fixture
def criar_flow(admin: httpx.Client, projeto_com_conexao: Ambiente) -> Iterator[Any]:
    yield from fabrica_de_flows(admin, projeto_com_conexao)


# --------------------------------------------------------------------------------------
# E2E-F3-01 — CRUD e as três reprovações 422 (RF-302/307)
# --------------------------------------------------------------------------------------


def test_e2e_f3_01_crud_e_validacoes_de_grafo(
    admin: httpx.Client, projeto_com_conexao: Ambiente, criar_flow: Any
) -> None:
    """RF-302/307: CRUD completo; ciclo, `exec_order` duplicado e tag inexistente dão 422."""
    ambiente = projeto_com_conexao
    flow_id = criar_flow("f3-01-crud", ts_seconds=1)

    detalhe = admin.get(f"/api/flows/{flow_id}").json()
    assert detalhe["desired_state"] == "stopped", "flow nasce parado (ADR-017)"
    assert detalhe["graph_json"] == {"nodes": [], "edges": []}
    assert detalhe["ts_seconds"] == 1

    valido = montar_grafo(
        [
            bloco("leitura", "opc_read", 1, tag_id=ambiente.static),
            bloco("escrita", "opc_write", 2, tag_id=ambiente.w_float),
        ],
        [aresta("leitura", "out", "escrita", "in")],
    )
    assert salvar(admin, flow_id, valido) == [], "grafo em ordem não gera aviso de inversão"
    gravado = admin.get(f"/api/flows/{flow_id}").json()
    assert gravado["graph_json"] == valido, "o `graph_json` é gravado verbatim"

    r = admin.put(
        f"/api/flows/{flow_id}", json={"name": f"f3-01-renomeado-{RUN_ID}", "graph_json": valido}
    )
    assert r.status_code == 200
    assert admin.get(f"/api/flows/{flow_id}").json()["name"] == f"f3-01-renomeado-{RUN_ID}"

    ciclo = montar_grafo(
        [
            bloco("a", "script", 1, n_inputs=1, n_outputs=1, code="OUT1 = IN1\n"),
            bloco("b", "script", 2, n_inputs=1, n_outputs=1, code="OUT1 = IN1\n"),
        ],
        [aresta("a", "OUT1", "b", "IN1"), aresta("b", "OUT1", "a", "IN1")],
    )
    assert "ciclo detectado" in reprovar(admin, flow_id, ciclo)

    duplicado = montar_grafo(
        [
            bloco("a", "script", 1, n_inputs=0, n_outputs=1, code="OUT1 = 1.0\n"),
            bloco("b", "script", 1, n_inputs=0, n_outputs=1, code="OUT1 = 2.0\n"),
        ],
        [],
    )
    assert "exec_order duplicado" in reprovar(admin, flow_id, duplicado)

    tag_fantasma = montar_grafo([bloco("leitura", "opc_read", 1, tag_id=2**40)], [])
    assert "não existe ou não pertence ao projeto" in reprovar(admin, flow_id, tag_fantasma)

    # Reprovação não grava: o grafo vigente sobrevive às três tentativas.
    assert admin.get(f"/api/flows/{flow_id}").json()["graph_json"] == valido

    assert admin.delete(f"/api/flows/{flow_id}").status_code == 204
    assert admin.get(f"/api/flows/{flow_id}").status_code == 404


# --------------------------------------------------------------------------------------
# E2E-F3-02 — Read→Script→Write ponta a ponta (RF-401/501/502)
# --------------------------------------------------------------------------------------


def test_e2e_f3_02_deploy_read_script_write_chega_ao_opcsim(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    eventos: EventStream,
    assinar_status: Any,
    opcsim_client: OpcSim,
) -> None:
    """RF-401/501/502: a cadeia varre, o espelho do opcsim muda e o `flow_deployed` sai."""
    ambiente = projeto_com_conexao
    esperar_conexao(ambiente.conn_id)
    # Offset distinto entre rodadas: o espelho sobrevive à execução e um valor repetido faria
    # o cenário passar sem que escrita nenhuma tivesse acontecido.
    offset = valor_unico()
    esperado = 42.0 + offset  # `sim.float.static` é constante 42,0 no opcsim

    grafo = montar_grafo(
        [
            bloco("leitura", "opc_read", 1, tag_id=ambiente.static),
            bloco("calculo", "script", 2, n_inputs=1, n_outputs=1, code=f"OUT1 = IN1 + {offset!r}"),
            bloco("escrita", "opc_write", 3, tag_id=ambiente.w_float),
        ],
        [
            aresta("leitura", "out", "calculo", "IN1"),
            aresta("calculo", "OUT1", "escrita", "in"),
        ],
    )
    flow_id = criar_flow("f3-02-cadeia", grafo=grafo)
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    evento = eventos.esperar(
        evento_de_flow(KIND_FLOW_DEPLOYED, flow_id),
        timeout=30.0,
        descricao="flow_deployed após o comando de deploy",
    )
    assert evento["severity"] == "info"
    assert evento["payload"]["flow_id"] == flow_id

    varredura = status.esperar(
        lambda s: de_varredura(s) and valor(s, "calculo", "OUT1") is not None,
        timeout=30.0,
        descricao="flow.status com a cadeia já produzindo valor",
    )
    assert varredura["state"] == "running"
    assert valor(varredura, "leitura", "out") == pytest.approx(42.0)
    assert valor(varredura, "calculo", "OUT1") == pytest.approx(esperado)
    assert valor(varredura, "escrita", "in") == pytest.approx(esperado)

    esperar_ate(
        lambda: opcsim_client.read(NODE_MIRROR_FLOAT) == pytest.approx(esperado),
        timeout=30.0,
        descricao=f"espelho do opcsim assumir {esperado} escrito pelo flow",
    )


# --------------------------------------------------------------------------------------
# E2E-F3-03 — ACEITE do jitter (PRD §8-F3, RNF-02)
# --------------------------------------------------------------------------------------


def test_e2e_f3_03_aceite_jitter_do_script_com_tfs(
    admin: httpx.Client, criar_flow: Any, assinar_status: Any
) -> None:
    """PRD §8-F3: Script+TFS a Ts=0,5 s por ≥120 s com p95 do desvio < 50 ms e zero overruns."""
    flow_id = criar_flow("f3-03-jitter", grafo=grafo_script_tfs(1.0))
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    primeira = status.esperar(
        de_varredura, timeout=30.0, descricao="primeira varredura do flow do aceite"
    )
    assert primeira["state"] == "running"

    # Janela de medição: coletada por evento recebido, não por dormir e olhar depois.
    amostras = [
        primeira,
        *status.coletar(
            quantidade=AMOSTRAS_JITTER - 1,
            timeout=JANELA_JITTER_S + 90.0,
            descricao="janela de 120 s de flow.status",
        ),
    ]
    assert all(de_varredura(a) for a in amostras), "publicação de transição no meio da janela"
    assert all(a["state"] == "running" for a in amostras), "o flow do aceite não pode oscilar"

    instantes = [datetime.fromisoformat(a["ts"]) for a in amostras]
    duracao = (instantes[-1] - instantes[0]).total_seconds()
    assert duracao >= JANELA_JITTER_S, f"janela de {duracao:.1f}s é menor que os 120 s exigidos"

    # `ts` é o instante real de disparo (§2.2-5); a grade teórica é o primeiro `ts` + n×Ts.
    # O índice vem do arredondamento, para uma fronteira pulada não deslocar as seguintes.
    base = instantes[0]
    desvios_ms = []
    for instante in instantes:
        deslocamento = (instante - base).total_seconds()
        indice = round(deslocamento / TS)
        desvios_ms.append(abs(deslocamento - indice * TS) * 1000.0)

    ordenados = sorted(desvios_ms)
    p50 = ordenados[math.ceil(0.50 * len(ordenados)) - 1]
    p95 = ordenados[math.ceil(0.95 * len(ordenados)) - 1]
    maximo = ordenados[-1]
    overruns = max(int(a["overruns"]) for a in amostras)
    scan_max = max(float(a["scan_ms"]) for a in amostras)
    print(
        f"\nE2E-F3-03: {len(amostras)} amostras em {duracao:.1f}s | desvio de fronteira "
        f"p50={p50:.1f}ms p95={p95:.1f}ms máx={maximo:.1f}ms | overruns={overruns} "
        f"| scan_ms máx={scan_max:.1f}ms (teto p95 {LIMITE_P95_MS:.0f}ms)"
    )

    assert overruns == 0, f"aceite exige zero overruns; o flow acumulou {overruns}"
    assert p95 < LIMITE_P95_MS, (
        f"aceite do PRD §8-F3 violado: p95 do desvio de fronteira = {p95:.1f}ms "
        f"(teto {LIMITE_P95_MS:.0f}ms, máx observado {maximo:.1f}ms)"
    )


# --------------------------------------------------------------------------------------
# E2E-F3-04 — ACEITE do hot-swap (RF-304, ADR-011)
# --------------------------------------------------------------------------------------


def test_e2e_f3_04_aceite_hot_swap_sem_parar_o_flow(
    admin: httpx.Client, criar_flow: Any, assinar_status: Any
) -> None:
    """RF-304/ADR-011: edição entra em ≤2×Ts, sem passar por `stopped`, com o TFS contínuo."""
    flow_id = criar_flow("f3-04-hotswap", grafo=grafo_script_tfs(1.0))
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    primeira = status.esperar(
        de_varredura, timeout=30.0, descricao="primeira varredura antes da edição"
    )
    antes = [
        primeira,
        *status.coletar(
            quantidade=7, timeout=30.0, descricao="varreduras com a definição original"
        ),
    ]
    y1_antes = [float(valor(a, "planta", "y1")) for a in antes]
    passo_antes = KI * TS * 1.0
    assert y1_antes[-1] - y1_antes[-2] == pytest.approx(passo_antes), (
        f"o integrador deveria subir {passo_antes} por varredura: {y1_antes}"
    )
    assert y1_antes[-1] >= 3.0, f"acumulador ainda pequeno para provar continuidade: {y1_antes}"

    # Só o `code` do Script muda; a matriz do TFS é a mesma, então o bloco é "não alterado"
    # (§4.1-3) e o acumulador tem de sobreviver ao swap.
    salvar(admin, flow_id, grafo_script_tfs(10.0))
    instante_do_put = datetime.now(UTC)
    passo_depois = KI * TS * 10.0

    depois = status.coletar(
        quantidade=8, timeout=30.0, descricao="varreduras após o PUT em flow rodando"
    )
    sequencia = [a["state"] for a in [*antes, *depois]]
    assert set(sequencia) == {"running"}, (
        f"o flow saiu de 'running' durante o hot-swap: {sequencia}"
    )
    assert all(de_varredura(a) for a in depois), "transição de estado publicada no meio do swap"

    anterior = antes[-1]
    adocao: dict[str, Any] | None = None
    for amostra in depois:
        delta = float(valor(amostra, "planta", "y1")) - float(valor(anterior, "planta", "y1"))
        if delta == pytest.approx(passo_depois):
            adocao = amostra
            break
        assert delta == pytest.approx(passo_antes), (
            f"passo inesperado antes da adoção: {delta} (nem {passo_antes} nem {passo_depois})"
        )
        anterior = amostra

    assert adocao is not None, "a edição não entrou em vigor em 8 varreduras"
    atraso = (datetime.fromisoformat(adocao["ts"]) - instante_do_put).total_seconds()
    y1_adocao = float(valor(adocao, "planta", "y1"))
    y1_anterior = float(valor(anterior, "planta", "y1"))
    print(
        f"\nE2E-F3-04: edição em vigor {atraso * 1000:.0f}ms após o PUT"
        f" (teto {2 * TS * 1000:.0f}ms)"
        f" | y1 {y1_anterior:.2f} -> {y1_adocao:.2f} | estados observados={sorted(set(sequencia))}"
    )

    assert atraso <= 2 * TS, f"hot-swap levou {atraso:.3f}s, acima de 2×Ts ({2 * TS}s)"
    assert y1_adocao == pytest.approx(y1_anterior + passo_depois), (
        "o estado do TFS não foi preservado no swap"
    )
    assert y1_adocao > passo_depois, (
        f"o integrador reiniciou do zero no swap: y1={y1_adocao} == primeiro passo"
    )


# --------------------------------------------------------------------------------------
# E2E-F3-05 — exec_order invertido (RF-401, ADR-024)
# --------------------------------------------------------------------------------------


def _grafo_contador(admin_tag: int, *, ordem_do_contador: int, ordem_da_escrita: int) -> dict:
    """Contador → Write. Invertendo a ordem, a escrita consome o valor da varredura anterior."""
    return montar_grafo(
        [
            bloco(
                "contador",
                "script",
                ordem_do_contador,
                n_inputs=0,
                n_outputs=1,
                code=CODE_CONTADOR,
            ),
            bloco("escrita", "opc_write", ordem_da_escrita, tag_id=admin_tag),
        ],
        [aresta("contador", "OUT1", "escrita", "in")],
    )


def test_e2e_f3_05_exec_order_invertido_atrasa_uma_varredura(
    admin: httpx.Client, projeto_com_conexao: Ambiente, criar_flow: Any, assinar_status: Any
) -> None:
    """RF-401/ADR-024: aresta invertida lê o valor da varredura anterior; o save avisa."""
    tag = projeto_com_conexao.w_float
    grafo_normal = _grafo_contador(tag, ordem_do_contador=1, ordem_da_escrita=2)
    flow_id = criar_flow("f3-05-ordem", grafo=grafo_normal)
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    status.esperar(de_varredura, timeout=30.0, descricao="primeira varredura em ordem normal")
    normais = status.coletar(quantidade=5, timeout=30.0, descricao="varreduras com a ordem normal")
    for amostra in normais:
        assert valor(amostra, "escrita", "in") == pytest.approx(
            valor(amostra, "contador", "OUT1")
        ), "em ordem normal a escrita consome o valor desta varredura"

    # Invertida: a escrita executa antes do contador. `exec_order` está fora da identidade do
    # bloco (ADR-024), então o contador não reinicia — o atraso é o único efeito.
    avisos = salvar(admin, flow_id, _grafo_contador(tag, ordem_do_contador=2, ordem_da_escrita=1))
    assert avisos, "aresta invertida deveria gerar `warnings[]` no save (RF-307)"
    assert any("escrita" in aviso and "contador" in aviso for aviso in avisos), avisos

    invertidas = status.coletar(
        quantidade=10, timeout=30.0, descricao="varreduras após inverter o exec_order"
    )
    estaveis = invertidas[-5:]
    for amostra in estaveis:
        atual = float(valor(amostra, "contador", "OUT1"))
        escrito = float(valor(amostra, "escrita", "in"))
        assert escrito == pytest.approx(atual - 1.0), (
            f"atraso deveria ser de exatamente 1 varredura: contador={atual} escrita={escrito}"
        )
    print(
        f"\nE2E-F3-05: avisos do save={len(avisos)} | atraso estável de 1 varredura em "
        f"{len(estaveis)} amostras consecutivas"
    )


# --------------------------------------------------------------------------------------
# E2E-F3-06 — RF-514: timeout e exceção de script
# --------------------------------------------------------------------------------------


def test_e2e_f3_06_timeout_e_erro_de_script_nao_derrubam_o_flow(
    admin: httpx.Client,
    criar_flow: Any,
    eventos: EventStream,
    assinar_status: Any,
) -> None:
    """RF-514: busy-loop ⇒ `script_timeout` com saídas mantidas; exceção ⇒ `script_error`."""
    grafo_timeout = montar_grafo(
        [bloco("calculo", "script", 1, n_inputs=0, n_outputs=1, code=CODE_TIMEOUT_APOS_TRES)], []
    )
    flow_timeout = criar_flow("f3-06-timeout", grafo=grafo_timeout)
    status_timeout = assinar_status(flow_timeout)

    deploy(admin, flow_timeout)
    boa = status_timeout.esperar(
        lambda s: de_varredura(s) and valor(s, "calculo", "OUT1") is not None,
        timeout=30.0,
        descricao="varredura boa antes do busy-loop",
    )
    assert valor(boa, "calculo", "OUT1") == pytest.approx(42.0)

    alarme = eventos.esperar(
        evento_de_bloco(KIND_SCRIPT_TIMEOUT, flow_timeout, "calculo"),
        timeout=60.0,
        descricao="script_timeout após o busy-loop",
    )
    assert alarme["severity"] == "alarm"
    assert alarme["payload"]["block_id"] == "calculo"
    assert alarme["payload"]["timeout_s"] == pytest.approx(0.7 * TS)

    # RF-514: o flow segue rodando e as saídas ficam nas últimas boas, não em `null`.
    apos = status_timeout.coletar(
        quantidade=4, timeout=30.0, descricao="varreduras após o timeout do script"
    )
    for amostra in apos:
        assert amostra["state"] == "running", "timeout de script não derruba o flow (RF-514)"
        assert valor(amostra, "calculo", "OUT1") == pytest.approx(42.0), (
            "as saídas do script deveriam ser mantidas no timeout"
        )

    grafo_erro = montar_grafo(
        [bloco("calculo", "script", 1, n_inputs=0, n_outputs=1, code=CODE_ERRO)], []
    )
    flow_erro = criar_flow("f3-06-erro", grafo=grafo_erro)
    status_erro = assinar_status(flow_erro)

    deploy(admin, flow_erro)
    erro = eventos.esperar(
        evento_de_bloco(KIND_SCRIPT_ERROR, flow_erro, "calculo"),
        timeout=60.0,
        descricao="script_error do script que levanta",
    )
    assert erro["severity"] == "alarm"
    detalhe = erro["payload"]["detail"]
    assert "Traceback" in detalhe and "ZeroDivisionError" in detalhe, detalhe
    seguinte = status_erro.esperar(
        de_varredura, timeout=30.0, descricao="varredura após o script_error"
    )
    assert seguinte["state"] == "running", "exceção de script não derruba o flow (RF-514)"
    print("\nE2E-F3-06: script_timeout e script_error emitidos; ambos os flows seguiram rodando")


# --------------------------------------------------------------------------------------
# E2E-F3-10 — script em erro desde a 1ª varredura (§3.0/§3.2)
# --------------------------------------------------------------------------------------


def test_e2e_f3_10_script_em_erro_suprime_a_escrita(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    eventos: EventStream,
    assinar_status: Any,
    opcsim_client: OpcSim,
) -> None:
    """§3.0/§3.2: saídas `null` desde a 1ª varredura ⇒ `write_suppressed` e espelho intacto."""
    ambiente = projeto_com_conexao
    esperar_conexao(ambiente.conn_id, timeout=180.0)
    espelho_antes = opcsim_client.read(NODE_MIRROR_FLOAT)

    grafo = montar_grafo(
        [
            bloco("calculo", "script", 1, n_inputs=0, n_outputs=1, code=CODE_ERRO),
            bloco("escrita", "opc_write", 2, tag_id=ambiente.w_float),
        ],
        [aresta("calculo", "OUT1", "escrita", "in")],
    )
    flow_id = criar_flow("f3-10-supressao", grafo=grafo)
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    achados = esperar_todos(
        eventos,
        {
            "script_error": evento_de_bloco(KIND_SCRIPT_ERROR, flow_id, "calculo"),
            "write_suppressed": evento_de_bloco(KIND_WRITE_SUPPRESSED, flow_id, "escrita"),
        },
        timeout=60.0,
        descricao="script_error e write_suppressed da primeira varredura",
    )
    supressao = achados["write_suppressed"]
    assert supressao["severity"] == "warning"
    assert supressao["payload"]["tag_id"] == ambiente.w_float
    assert supressao["payload"]["reason"] == "entrada sem valor"

    # A primeira publicação depois do deploy é a transição de estado, com `ports` vazio
    # (§4.2): a janela de observação começa na primeira varredura de verdade.
    primeira = status.esperar(
        de_varredura, timeout=30.0, descricao="primeira varredura do flow com script em erro"
    )
    amostras = [
        primeira,
        *status.coletar(
            quantidade=4, timeout=30.0, descricao="varreduras do flow com script em erro"
        ),
    ]
    for amostra in amostras:
        assert amostra["state"] == "running"
        saida = porta(amostra, "calculo", "OUT1")
        assert saida["v"] is None and saida["ok"] is False, f"saída deveria ser nula: {saida}"
        assert porta(amostra, "escrita", "in")["v"] is None

    assert opcsim_client.read(NODE_MIRROR_FLOAT) == pytest.approx(espelho_antes), (
        "a escrita saiu apesar da entrada nula (§3.2)"
    )
    print(
        f"\nE2E-F3-10: {len(amostras)} varreduras com saída nula, escrita suprimida e espelho "
        f"parado em {espelho_antes}"
    )
