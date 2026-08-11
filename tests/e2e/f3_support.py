"""Infraestrutura compartilhada da camada L2 da F3 (spec §7.2).

Construção de `graph_json`, assinante de `flow.status.<id>`, predicados de evento de flow e
de bloco, `/health` do flow-runtime e os atalhos de API que os cenários usam. Vive fora dos
módulos de teste porque os dez cenários da F3 estão divididos em dois arquivos por assunto e
os dois precisam exatamente das mesmas peças.

As fixtures `assinar_status` e `criar_flow` moram aqui e são importadas por nome nos módulos
de teste: o `conftest.py` da suíte é o da F2 e está em uso por outros três arquivos.
"""

import json
import subprocess
import time
from collections.abc import Callable
from typing import Any

import httpx
import redis

from ottima_core.bus import channel_flow_status

from .conftest import (
    NODE_WD_FROM_SYSTEM,
    NODE_WD_TO_SYSTEM,
    RUN_ID,
    SENTINELA,
    Ambiente,
    EventStream,
    compose,
    esperar_ate,
    esperar_flow_watchdog,
)

# Ts do aceite (PRD §8-F3): o menor do ADR-007 e o mais exigente para a grade de varredura.
TS = 0.5

# Aceite do jitter (RNF-02): ≥120 s de coleta e p95 do desvio de fronteira abaixo de 50 ms.
JANELA_JITTER_S = 120.0
LIMITE_P95_MS = 50.0
# Duas fronteiras de folga sobre as 240 da janela: a grade dispara alguns milissegundos
# depois de cada fronteira, então contar exatamente 241 amostras fecha uma janela de
# 119,9998 s. A exigência dos 120 s é verificada no cenário, sobre os `ts` medidos.
AMOSTRAS_JITTER = int(JANELA_JITTER_S / TS) + 3

# Ganho do integrador do TFS: com Ki=1 e u constante, y1 cresce Ki·Ts·u por varredura, o que
# torna a continuidade do estado no hot-swap visível a olho nu (E2E-F3-04).
KI = 1.0

# Janela de observação negativa: 6 varreduras a Ts=0,5 s. Provar que algo NÃO acontece exige
# olhar por um tempo — não é sincronização por sleep, é a medida do silêncio.
SILENCIO_S = 3.0

_RUNTIME_HEALTH_SNIPPET = (
    "import urllib.request;"
    "print(urllib.request.urlopen('http://localhost:8002/health', timeout=3).read().decode())"
)


# Construção de grafo (spec §5.2: forma React Flow, `data` com exec_order + config)
# --------------------------------------------------------------------------------------


def bloco(node_id: str, tipo: str, exec_order: int, *, label: str = "", **config: Any) -> dict:
    """Nó React Flow: `exec_order`, `label` e a config do tipo moram todos em `data`."""
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 160.0 * exec_order, "y": 0.0},
        "data": {"exec_order": exec_order, "label": label, **config},
    }


def aresta(origem: str, saida: str, destino: str, entrada: str) -> dict:
    return {
        "id": f"{origem}.{saida}->{destino}.{entrada}",
        "source": origem,
        "target": destino,
        "sourceHandle": saida,
        "targetHandle": entrada,
    }


def montar_grafo(nos: list[dict], arestas: list[dict]) -> dict:
    return {"nodes": nos, "edges": arestas}


def elemento_iopdt(*, enabled: bool, ki: float = 0.0) -> dict:
    """Elemento IOPDT da matriz do TFS (spec §3.4): `acc += Ki·Ts·u`, sem tempo morto."""
    return {"enabled": enabled, "kind": "iopdt", "params": {"Ki": ki, "theta": 0.0}}


def matriz_integrador(ki: float = KI) -> list[list[dict]]:
    """Só y1/u1 habilitado: `u2` deixa de ser obrigatória e y2 vale 0,0 (ADR-022, §3.4)."""
    return [
        [elemento_iopdt(enabled=True, ki=ki), elemento_iopdt(enabled=False)],
        [elemento_iopdt(enabled=False), elemento_iopdt(enabled=False)],
    ]


def grafo_script_tfs(constante: float) -> dict:
    """Script (constante) → TFS integrador: o par do aceite da fase (PRD §8-F3)."""
    return montar_grafo(
        [
            bloco("calculo", "script", 1, n_inputs=0, n_outputs=1, code=f"OUT1 = {constante!r}"),
            bloco("planta", "tfs", 2, matrix=matriz_integrador()),
        ],
        [aresta("calculo", "OUT1", "planta", "u1")],
    )


# Contador de varreduras via `state` (RF-512): a única forma de o teste enxergar em qual
# varredura um valor foi produzido, e por isso a base do atraso do E2E-F3-05.
CODE_CONTADOR = "n = state.get('n', 0) + 1\nstate['n'] = n\nOUT1 = float(n)\n"

# Divisão por zero: erro do interpretador, sem depender de nome de exceção — a lista fechada
# de builtins do ADR-018 não expõe `ValueError`, então `raise ValueError` daria NameError.
CODE_ERRO = "OUT1 = 1.0 / 0.0\n"

# Três varreduras boas e depois busy-loop para sempre: como o `state` só é adotado em retorno
# OK (§3.3), o contador congela em 3 e toda varredura seguinte estoura o timeout de 0,7×Ts.
CODE_TIMEOUT_APOS_TRES = (
    "n = state.get('n', 0) + 1\n"
    "state['n'] = n\n"
    "OUT1 = 42.0\n"
    "if n > 3:\n"
    "    while True:\n"
    "        pass\n"
)


# --------------------------------------------------------------------------------------
# Barramento e API
# --------------------------------------------------------------------------------------


class StatusStream:
    """Assinatura de `flow.status.<flow_id>` aberta ANTES do gatilho (estilo do `EventStream`).

    A sequência importa tanto quanto os valores: o E2E-F3-04 prova que o hot-swap não passou
    por `stopped` justamente por não haver lacuna entre as amostras.
    """

    def __init__(self, pubsub: redis.client.PubSub) -> None:
        self._pubsub = pubsub

    def proxima(self, *, timeout: float, descricao: str) -> dict[str, Any]:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            mensagem = self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if mensagem is None or mensagem.get("type") != "message":
                continue
            return json.loads(mensagem["data"])
        raise AssertionError(f"{descricao}: nenhum flow.status em {timeout:.0f}s")

    def esperar(
        self, pred: Callable[[dict[str, Any]], bool], *, timeout: float, descricao: str
    ) -> dict[str, Any]:
        limite = time.monotonic() + timeout
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise AssertionError(f"{descricao}: nenhum flow.status correspondente")
            status = self.proxima(timeout=restante, descricao=descricao)
            if pred(status):
                return status

    def coletar(self, *, quantidade: int, timeout: float, descricao: str) -> list[dict[str, Any]]:
        """Amostras consecutivas, sem lacuna: coleta por mensagem recebida, nunca por sleep."""
        limite = time.monotonic() + timeout
        amostras: list[dict[str, Any]] = []
        while len(amostras) < quantidade:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise AssertionError(
                    f"{descricao}: {len(amostras)} de {quantidade} amostras em {timeout:.0f}s"
                )
            amostras.append(self.proxima(timeout=restante, descricao=descricao))
        return amostras

    def silencio(self, *, duracao: float = SILENCIO_S) -> list[dict[str, Any]]:
        """Tudo o que chegou na janela; lista vazia é a prova de que o flow não está varrendo."""
        fim = time.monotonic() + duracao
        recebidas: list[dict[str, Any]] = []
        while time.monotonic() < fim:
            mensagem = self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if mensagem is not None and mensagem.get("type") == "message":
                recebidas.append(json.loads(mensagem["data"]))
        return recebidas


def evento_de_flow(kind: str, flow_id: int) -> Callable[[dict[str, Any]], bool]:
    """`origin` de evento de flow é `flow:<id>` exato (§2.2-7); o `kind` mora no payload."""
    origem = f"flow:{flow_id}"

    def casa(evento: dict[str, Any]) -> bool:
        return evento.get("origin") == origem and evento.get("payload", {}).get("kind") == kind

    return casa


def evento_de_bloco(kind: str, flow_id: int, block_id: str) -> Callable[[dict[str, Any]], bool]:
    """Evento de bloco carrega o bloco no `origin`: `flow:<id>/block:<bid>` (§4.3)."""
    origem = f"flow:{flow_id}/block:{block_id}"

    def casa(evento: dict[str, Any]) -> bool:
        return evento.get("origin") == origem and evento.get("payload", {}).get("kind") == kind

    return casa


def esperar_todos(
    eventos: EventStream,
    predicados: dict[str, Callable[[dict[str, Any]], bool]],
    *,
    timeout: float,
    descricao: str,
) -> dict[str, dict[str, Any]]:
    """Espera todos os predicados em qualquer ordem.

    Eventos da mesma varredura chegam em rajada: esperar um por vez descartaria os demais,
    porque o `EventStream` consome o que não casa.
    """
    pendentes = dict(predicados)
    achados: dict[str, dict[str, Any]] = {}
    limite = time.monotonic() + timeout
    while pendentes:
        restante = limite - time.monotonic()
        if restante <= 0:
            raise AssertionError(f"{descricao}: faltaram {sorted(pendentes)} em {timeout:.0f}s")
        evento = eventos.esperar(
            lambda candidato: any(pred(candidato) for pred in pendentes.values()),
            timeout=restante,
            descricao=descricao,
        )
        for nome, pred in list(pendentes.items()):
            if pred(evento):
                achados[nome] = evento
                del pendentes[nome]
    return achados


def runtime_health() -> dict[str, Any] | None:
    """`/health` do flow-runtime, lido de dentro do container (a porta não é publicada).

    `None` enquanto o serviço não responde: reinício é estado transitório de espera, não erro.
    """
    try:
        return json.loads(
            compose("exec", "-T", "flow-runtime", "python", "-c", _RUNTIME_HEALTH_SNIPPET)
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


def esperar_runtime_saudavel(*, timeout: float = 120.0) -> dict[str, Any]:
    """Espera o `/health` do runtime voltar com `status=ok`.

    Depois de um `restart` o healthcheck do compose tem período de partida: cenário que corra
    na janela de subida vira vermelho falso.
    """

    def checar() -> dict[str, Any] | None:
        saude = runtime_health()
        return saude if saude is not None and saude.get("status") == "ok" else None

    return esperar_ate(checar, timeout=timeout, intervalo=1.0, descricao="flow-runtime saudável")


def flow_no_runtime(flow_id: int) -> dict[str, Any] | None:
    saude = runtime_health()
    return None if saude is None else saude.get("flows", {}).get(str(flow_id))


def aguardar_parado(flow_id: int, *, timeout: float = 60.0) -> None:
    """Espera o runtime materializar a parada antes de o teste excluir o flow.

    Flow excluído do banco mas ainda varrendo escreveria na tag de um cenário seguinte: o
    watermark o pegaria, mas só em até 10 s (§2.2-9).
    """

    def parado() -> bool:
        flow = flow_no_runtime(flow_id)
        return flow is None or flow["state"] != "running"

    esperar_ate(parado, timeout=timeout, intervalo=1.0, descricao=f"flow {flow_id} deixar de rodar")


def salvar(admin: httpx.Client, flow_id: int, grafo: dict) -> list[str]:
    """`PUT` do grafo; devolve os `warnings[]` (RF-307: aviso de inversão não bloqueia)."""
    r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
    assert r.status_code == 200, f"PUT do grafo falhou: HTTP {r.status_code} {r.text}"
    return list(r.json()["warnings"])


def reprovar(admin: httpx.Client, flow_id: int, grafo: dict) -> str:
    """`PUT` que deve dar 422 de domínio; devolve o `detail`, que é string pt-BR única."""
    r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
    assert r.status_code == 422, f"grafo inválido aceito: HTTP {r.status_code} {r.text}"
    detalhe = r.json()["detail"]
    assert isinstance(detalhe, str) and detalhe, f"`detail` deveria ser string única: {detalhe!r}"
    return detalhe


def deploy(admin: httpx.Client, flow_id: int) -> None:
    r = admin.post(f"/api/flows/{flow_id}/deploy")
    assert r.status_code == 202, f"deploy do flow {flow_id}: HTTP {r.status_code} {r.text}"


def ativar_projeto(admin: httpx.Client, project_id: int) -> None:
    r = admin.post(f"/api/projects/{project_id}/activate")
    assert r.status_code == 200, f"ativação do projeto {project_id}: HTTP {r.status_code}"


def id_da_sentinela(admin: httpx.Client) -> int:
    """Projeto estável da suíte, criado se ainda não existir (mesmo padrão do conftest)."""
    r = admin.post("/api/projects", json={"name": SENTINELA})
    if r.status_code == 201:
        return int(r.json()["id"])
    projetos = admin.get("/api/projects").json()
    return int(next(p for p in projetos if p["name"] == SENTINELA)["id"])


def porta(status: dict[str, Any], block_id: str, handle: str) -> dict[str, Any]:
    portas = status["ports"]
    assert block_id in portas, f"bloco '{block_id}' ausente de `ports`: {sorted(portas)}"
    assert handle in portas[block_id], f"porta '{handle}' ausente: {sorted(portas[block_id])}"
    return portas[block_id][handle]


def valor(status: dict[str, Any], block_id: str, handle: str) -> float | bool | None:
    return porta(status, block_id, handle)["v"]


def de_varredura(status: dict[str, Any]) -> bool:
    """Publicação de varredura, não de transição: `ports` vazio é o contrato do §4.2."""
    return bool(status["ports"])


# --------------------------------------------------------------------------------------
# Corpo das fixtures
# --------------------------------------------------------------------------------------
#
# Geradores, não fixtures: importar uma fixture para o namespace de um módulo de teste faz o
# nome dela colidir com o próprio parâmetro que a recebe. Cada módulo declara a fixture com
# uma linha de `yield from`, e o comportamento vive aqui, numa cópia só.


def assinantes_de_status(redis_bus: redis.Redis) -> Any:
    """Fábrica de assinantes de `flow.status.<id>`, para abrir a inscrição antes do gatilho."""
    pubsubs: list[redis.client.PubSub] = []

    def assinar(flow_id: int) -> StatusStream:
        pubsub = redis_bus.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel_flow_status(flow_id))
        pubsubs.append(pubsub)
        return StatusStream(pubsub)

    try:
        yield assinar
    finally:
        for pubsub in pubsubs:
            pubsub.close()


def fabrica_de_flows(admin: httpx.Client, ambiente: Ambiente) -> Any:
    """Cria flows no projeto do módulo e garante o teardown: parar, aguardar e excluir.

    Excluir flow rodando é 409 (§5.1), e excluir sem esperar a parada deixaria varredura
    órfã escrevendo em tag que o cenário seguinte observa.
    """
    criados: list[int] = []

    def criar(nome: str, *, ts_seconds: float = TS, grafo: dict | None = None) -> int:
        r = admin.post(
            "/api/flows",
            json={
                "project_id": ambiente.project_id,
                "name": f"{nome}-{RUN_ID}",
                "ts_seconds": ts_seconds,
            },
        )
        assert r.status_code == 201, f"criação do flow {nome}: HTTP {r.status_code} {r.text}"
        flow_id = int(r.json()["id"])
        criados.append(flow_id)
        if grafo is not None:
            salvar(admin, flow_id, grafo)
        # ADR-009 revisado: watchdog é por flow. Todo flow que escreve em OPC precisa do
        # seu próprio watchdog armado — sem ele, o gate recusa como `no_watchdog`.
        admin.put(
            f"/api/flows/{flow_id}",
            json={
                "watchdog_enabled": True,
                "watchdog_connection_id": ambiente.conn_id,
                "watchdog_read_node_id": NODE_WD_TO_SYSTEM,
                "watchdog_write_node_id": NODE_WD_FROM_SYSTEM,
                "watchdog_period_ms": 1000,
            },
        )
        esperar_flow_watchdog(flow_id, ambiente.conn_id)
        return flow_id

    try:
        yield criar
    finally:
        for flow_id in reversed(criados):
            admin.post(f"/api/flows/{flow_id}/stop")
            aguardar_parado(flow_id)
            admin.delete(f"/api/flows/{flow_id}")
