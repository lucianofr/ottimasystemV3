#!/usr/bin/env python3
"""Monta no ottimaSystemV3 o projeto de controle da planta virtual debutanizadora.

Idempotente: pode rodar de novo que reaproveita projeto, conexao, tags e flow.

    uv run python planta_virtual/setup_planta.py

O que cria:
  - projeto "Planta Debutanizadora" (ativo)
  - conexao OPC-UA anonima para a planta, com life-bit em Plant.Sim.Watchdog
  - 24 tags: 6 lidas pelo MPC, 4 escritas pelo MPC, 4 de readback das MVs (leitura do
    MESMO no que a MV escreve), 10 lidas so para tendencia
  - flow "Controle-MPC-Debutanizadora" (Ts 10 s) com:
      6 opc_read -> bloco MPC 4x4+2DV (portas absolutas) -> 4 opc_write

Convencao de unidades e coordenadas (decisao de projeto):
  - MV e DV sao ABSOLUTAS na porta do bloco MPC (mesma coordenada da planta). O bloco
    converte para o ponto de operacao internamente via `operating_point` por MV/DV
    (`coluna - operating_point`); o modelo integrador do ottima e `y' = Ki*u` com `u`
    de desvio -- sem a conversao o nivel previsto despencaria ~10 %/execucao no proprio
    ponto nominal. A MV direta tambem leva `readback_tag_id`: em LOCAL ela acompanha a
    posicao real da planta, entao a troca para REMOTO e bumpless.
  - CV entra em unidade de engenharia absoluta: o bias do DMC (`bias = y_medido - C.x`)
    absorve o offset do ponto de operacao a cada execucao.
  - tau e theta em SEGUNDOS (a mesma base do Ts do flow); a matriz do arquivo
    `mpc_models.json` esta em minutos.
  - Ki em (unidade da CV)/s por unidade da coluna; o do arquivo esta em .../min.
  - ganho usado = o TANGENTE (`gain` do arquivo), nao o secante que a doc da planta
    recomenda: ver `ganho_recomendado()` -- o tangente e o lado seguro do erro (preve
    mais efeito do que obtem, move menos). Com o secante o MPC sobre-moveu 1,8x.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

RAIZ = Path(__file__).resolve().parents[1]
MODELOS = json.loads((RAIZ / "planta_virtual" / "mpc_models.json").read_text())

PROJETO = "Planta Debutanizadora"
CONEXAO = "planta-debutanizadora"
FLOW = "Controle-MPC-Debutanizadora"
BLOCO_MPC = "mpc1"

# Endpoint visto de dentro do compose: a planta roda no host, o worker no container.
ENDPOINT = os.environ.get("PLANTA_OPC_ENDPOINT", "opc.tcp://172.18.0.1:4843/plant/")
NS = 2
NODE_WATCHDOG = f"ns={NS};s=Plant.Sim.Watchdog"

TS_FLOW = 10.0
MULTIPLICADOR = 12  # Ts_mpc = 120 s
TSS_TEMPERATURA = 7200.0  # Np = ceil(7200/120) = 60 (teto de aviso da spec)
TSS_NIVEL = 3600.0

NOMINAL = MODELOS["operating_point"]["inputs"]

MV_TAG = {"mv_xv101": "XV-101", "mv_xv102": "XV-102", "mv_xv103": "XV-103", "mv_sc102": "SC-102"}
CV_TAG = {"cv_tt101": "TT-101", "cv_tt102": "TT-102", "cv_lt101": "LT-101", "cv_lt102": "LT-102"}
DV_TAG = {"dv_ft100": "FT-100", "dv_at100": "AT-100"}
TAG_MV = {v: k for k, v in MV_TAG.items()}
TAG_CV = {v: k for k, v in CV_TAG.items()}
TAG_DV = {v: k for k, v in DV_TAG.items()}

# Curso mecanico real de cada atuador, em valor ABSOLUTO (doc da planta secao 8):
# valvulas 5-95 %, bombas 40-100 % (abaixo de ~39 % a bomba nao produz vazao alguma).
CURSO = {
    "XV-101": (5.0, 95.0),
    "XV-102": (5.0, 95.0),
    "XV-103": (5.0, 95.0),
    "SC-102": (40.0, 100.0),
}
# Delta maximo por execucao do MPC (120 s). XV-101/XV-102 ficam MUITO abaixo dos 2 %/exec
# sugeridos pela doc da planta: com K(XV-101 -> TT-102) = -18,9 degC/%, um degrau de 2 %
# vale 38 degC de regime -- na campanha anterior isso levou TT-102 a oscilar 12,7 degC de
# pico a pico. 0,5 % ainda esta acima da histerese de 0,4 % da valvula (movimento menor nao
# move a haste), entao e o menor valor que a planta de fato executa. XV-103 e SC-102 pesam
# quase nada na temperatura (K(XV-103 -> TT-102) = 0,86 degC/%, SC-102 nem entra nas duas
# linhas de temperatura) e servem so ao nivel: podem andar mais por execucao.
DU_MAX = {"XV-101": 0.5, "XV-102": 0.5, "XV-103": 1.0, "SC-102": 1.5}

# Faixa de setpoint de cada CV = escala de normalizacao do custo (span do objetivo).
SP_LIMITS = {
    "cv_tt101": {"min": 45.0, "max": 65.0},
    "cv_tt102": {"min": 110.0, "max": 140.0},
    "cv_lt101": {"min": 20.0, "max": 80.0},
    "cv_lt102": {"min": 45.0, "max": 80.0},
}
# TT-102 entra com peso baixo de proposito. O par (XV-101, XV-102) x (TT-101, TT-102) tem
# numero de condicao 62: mover as duas temperaturas JUNTAS e barato (valor singular 14,6),
# mover a DIFERENCA entre elas custa 62x mais (0,234). Perseguir setpoint nas duas com o
# mesmo peso poe o MPC na direcao cara, onde alguns por cento de erro de ganho ja viram
# movimento oposto grande nas duas valvulas -- foi o ciclo-limite de +-3,5 degC em TT-102
# (periodo ~25 min) observado nesta campanha. TT-101 e a inferencia de composicao do
# destilado (a especificacao apertada) e fica com o peso; TT-102 vira alvo frouxo, o
# equivalente pratico do "zone control" que a doc da planta recomenda.
PESO_CV = {"cv_tt101": 1.0, "cv_tt102": 0.15, "cv_lt101": 2.0, "cv_lt102": 2.0}
EU_CV = {"cv_tt101": "degC", "cv_tt102": "degC", "cv_lt101": "%", "cv_lt102": "%"}
LINHA_KIND = {
    "cv_tt101": "selfreg",
    "cv_tt102": "selfreg",
    "cv_lt101": "integrating",
    "cv_lt102": "integrating",
}
TSS_CV = {
    "cv_tt101": TSS_TEMPERATURA,
    "cv_tt102": TSS_TEMPERATURA,
    "cv_lt101": TSS_NIVEL,
    "cv_lt102": TSS_NIVEL,
}

# AT-100 -> LT-102 nao e representavel por SOPDT+I: o `secant_over_tangent` do par e
# NEGATIVO (-0,43), ou seja o efeito acumulado num degrau finito tem sinal contrario ao do
# ganho tangente -- resposta nao-monotonica, que a doc da planta manda tratar com FIR. Sem
# FIR no ottima o par fica desabilitado: o feedback pelo bias cobre o efeito, um
# feedforward de sinal errado nao cobriria.
PARES_DESABILITADOS = {("cv_lt102", "dv_at100")}

# Tags lidas so para tendencia (nao entram no grafo; o opc-worker assina toda tag 'r'
# e o recorder grava tudo que passa pelo barramento).
TAGS_CONTEXTO = [
    ("XV-101-POS", "Plant.MV.XV-101.POS", "%", "Posicao real da haste da valvula de refluxo"),
    ("XV-102-POS", "Plant.MV.XV-102.POS", "%", "Posicao real da haste da valvula de vapor"),
    ("XV-103-POS", "Plant.MV.XV-103.POS", "%", "Posicao real da haste da valvula de destilado"),
    ("SC-102-SPD", "Plant.MV.SC-102.SPD", "%", "Velocidade real da bomba de fundo"),
    ("FT-101", "Plant.Readings.FT-101.PV", "m3/h", "Vazao de refluxo"),
    ("FT-102", "Plant.Readings.FT-102.PV", "kg/h", "Vazao de vapor ao refervedor"),
    ("FT-103", "Plant.Readings.FT-103.PV", "m3/h", "Vazao de destilado"),
    ("FT-104", "Plant.Readings.FT-104.PV", "m3/h", "Vazao de produto de fundo"),
    ("PT-101", "Plant.Readings.PT-101.PV", "kPa", "Pressao de topo"),
    ("PT-102", "Plant.Readings.PT-102.PV", "kPa", "Pressao de fundo"),
]


# ---------------------------------------------------------------------------------------
# Matriz de modelos
# ---------------------------------------------------------------------------------------


def ganho_recomendado(par: dict[str, Any]) -> float:
    """Ganho TANGENTE da linearizacao, nao o secante recomendado pela doc da planta.

    A doc sugere `K_rec = K_tan x (secante/tangente)` para casar a amplitude de um
    movimento finito, e avisa qual e o lado seguro do erro: "usar o tangente puro nao
    desestabiliza -- o MPC preve mais efeito do que obtem, move menos que o necessario e
    fica lento". Com `K_rec` (0,56 x K_tan nos canais de valvula) o MPC preve 1,8x menos
    efeito do que a planta entrega e sobre-move na mesma proporcao; num bloco 2x2 de
    numero de condicao 62 e tau de 33 min isso virou oscilacao sustentada na primeira
    rodada desta campanha. Fica o tangente, que e o lado lento.
    """
    return float(par["gain"])


def montar_modelos() -> dict[str, dict[str, dict[str, Any]]]:
    """Matriz `models` do bloco MPC a partir de `mpc_models.json`."""
    modelos: dict[str, dict[str, dict[str, Any]]] = {linha: {} for linha in CV_TAG}
    for coluna_tag, linhas in MODELOS["models"].items():
        coluna = TAG_MV.get(coluna_tag) or TAG_DV.get(coluna_tag)
        if coluna is None:
            continue
        for linha_tag, par in linhas.items():
            linha = TAG_CV.get(linha_tag)
            if linha is None or par["form"] == "zero":
                continue
            kind = LINHA_KIND[linha]
            ganho = ganho_recomendado(par)
            theta_s = float(par["theta_min"]) * 60.0
            if kind == "selfreg":
                params = {
                    "K": ganho,
                    "tau1": float(par["tau1_min"]) * 60.0,
                    "tau2": float(par["tau2_min"]) * 60.0,
                    "theta": theta_s,
                }
            else:
                params = {"Ki": ganho / 60.0, "theta": theta_s}
            habilitado = (linha, coluna) not in PARES_DESABILITADOS
            modelos[linha][coluna] = {"enabled": habilitado, "params": params}
    return modelos


# Readback de cada MV: a LEITURA do MESMO no que a MV escreve (`Plant.MV.*.CMD`), e nao a
# posicao mecanica (`.POS`/`.SPD`). Em LOCAL a saida da MV acompanha esse readback e o
# `opc_write` a jusante devolve o valor a planta -- com o CMD isso e um eco exato, inofensivo,
# e a transferencia para REMOTO parte do comando que esta de fato em vigor. Com `.POS` seria
# uma briga: a haste vem atrasada pelo tempo de curso e pela histerese de 0,4 %, entao
# qualquer rampa iniciada pelo operador em LOCAL seria puxada de volta a cada varredura.
# O no CMD e RW na planta (address_space.py: escrita liberada, leitura sempre); a unicidade
# de tag e por (conexao, NOME), entao a tag 'r' convive com a tag 'w' no mesmo node_id.
MV_READBACK = {tag: f"{tag}-CMD-RB" for tag in MV_TAG.values()}


def config_mpc(tags: dict[str, int]) -> dict[str, Any]:
    mvs = []
    for mv_id, tag in MV_TAG.items():
        low, high = CURSO[tag]
        mvs.append(
            {
                "id": mv_id,
                "name": tag,
                "eu": "%",
                "limits": {"min": low, "max": high},
                "du_max": DU_MAX[tag],
                "initial_value": NOMINAL[tag],
                "operating_point": NOMINAL[tag],
                "readback_tag_id": tags[MV_READBACK[tag]],
            }
        )
    cvs = [
        {
            "id": cv_id,
            "name": tag,
            "eu": EU_CV[cv_id],
            "kind": LINHA_KIND[cv_id],
            "tss": TSS_CV[cv_id],
            "weight": PESO_CV[cv_id],
            "sp_limits": SP_LIMITS[cv_id],
        }
        for cv_id, tag in CV_TAG.items()
    ]
    dvs = [
        {
            "id": "dv_ft100",
            "name": "FT-100",
            "eu": "m3/h",
            "range": {"low": 0.0, "high": 80.0},
            "operating_point": NOMINAL["FT-100"],
        },
        {
            "id": "dv_at100",
            "name": "AT-100",
            "eu": "frac molar",
            "range": {"low": 0.20, "high": 0.70},
            "operating_point": NOMINAL["AT-100"],
        },
    ]
    return {
        "name": "MPC Debutanizadora",
        "multiplier": MULTIPLICADOR,
        "variables": {"mvs": mvs, "cvs": cvs, "constraints": [], "dvs": dvs},
        "models": montar_modelos(),
    }


# ---------------------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------------------


# A conversao para o ponto de operacao (antes um Script de subtracao + filtro de FT-100,
# tau=60 s) agora e nativa do bloco MPC via `operating_point`; nao ha mais Script no flow.
# Se o ruido de amostra de FT-100 voltar a incomodar, o caminho e um bloco `tfs` de 1a
# ordem entre `rd_ft100` e o MPC -- nunca um Script de novo.


def _no(node_id: str, tipo: str, ordem: int, x: float, y: float, **dados: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": x, "y": y},
        "data": {"exec_order": ordem, **dados},
    }


def montar_grafo(tags: dict[str, int]) -> dict[str, Any]:
    leitura = [
        ("rd_tt101", "TT-101", "cv_tt101"),
        ("rd_tt102", "TT-102", "cv_tt102"),
        ("rd_lt101", "LT-101", "cv_lt101"),
        ("rd_lt102", "LT-102", "cv_lt102"),
    ]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    ordem = 1
    for i, (node_id, tag, _) in enumerate(leitura):
        nodes.append(_no(node_id, "opc_read", ordem, 0.0, i * 90.0, tag_id=tags[tag], label=tag))
        ordem += 1
    for i, (node_id, tag) in enumerate((("rd_ft100", "FT-100"), ("rd_at100", "AT-100"))):
        nodes.append(
            _no(node_id, "opc_read", ordem, 0.0, 380.0 + i * 90.0, tag_id=tags[tag], label=tag)
        )
        ordem += 1

    nodes.append(_no(BLOCO_MPC, "mpc", ordem, 400.0, 180.0, label="MPC", **config_mpc(tags)))
    ordem += 1

    for i, (mv_id, tag) in enumerate(MV_TAG.items()):
        nodes.append(
            _no(
                f"wr_{mv_id[3:]}",
                "opc_write",
                ordem,
                800.0,
                i * 90.0,
                tag_id=tags[f"{tag}-CMD"],
                label=f"{tag}.CMD",
            )
        )
        ordem += 1

    def aresta(source: str, sh: str, target: str, th: str) -> None:
        edges.append(
            {
                "id": f"e{len(edges) + 1}",
                "source": source,
                "sourceHandle": sh,
                "target": target,
                "targetHandle": th,
            }
        )

    for node_id, _, cv_id in leitura:
        aresta(node_id, "out", BLOCO_MPC, cv_id)
    aresta("rd_ft100", "out", BLOCO_MPC, "dv_ft100")
    aresta("rd_at100", "out", BLOCO_MPC, "dv_at100")
    for mv_id in MV_TAG:
        aresta(BLOCO_MPC, mv_id, f"wr_{mv_id[3:]}", "in")
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------


def env_deploy() -> dict[str, str]:
    valores: dict[str, str] = {}
    for linha in (RAIZ / "deploy" / ".env").read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip()
    return valores


def login() -> httpx.Client:
    env = env_deploy()
    cliente = httpx.Client(
        base_url=os.environ.get("OTTIMA_BASE_URL", "http://localhost:8080"), timeout=30.0
    )
    r = cliente.post(
        "/api/auth/login",
        json={
            "username": os.environ.get("OTTIMA_ADMIN_USERNAME") or env["OTTIMA_ADMIN_USERNAME"],
            "password": os.environ.get("OTTIMA_ADMIN_PASSWORD") or env["OTTIMA_ADMIN_PASSWORD"],
        },
    )
    r.raise_for_status()
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def obter_projeto(api: httpx.Client) -> int:
    for p in api.get("/api/projects").raise_for_status().json():
        if p["name"] == PROJETO:
            api.post(f"/api/projects/{p['id']}/activate").raise_for_status()
            return int(p["id"])
    r = api.post(
        "/api/projects",
        json={"name": PROJETO, "description": "Coluna debutanizadora virtual sob MPC"},
    )
    r.raise_for_status()
    pid = int(r.json()["id"])
    api.post(f"/api/projects/{pid}/activate").raise_for_status()
    return pid


def obter_conexao(api: httpx.Client, projeto_id: int) -> int:
    """Conexao com life-bit: sem watchdog o opc-worker recusa TODA escrita
    (`no_watchdog`, spec F2 secao 3.5) e o MPC nunca alcancaria as MVs. O no
    `Plant.Sim.Watchdog` e Boolean RW e nao e tocado pela fisica, entao serve de eco:
    o worker le, reescreve invertido e ve a alternancia no ciclo seguinte."""
    campos: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "security_policy": "none",
        "security_mode": "none",
        "auth_mode": "anonymous",
        "watchdog_read_node_id": NODE_WATCHDOG,
        "watchdog_write_node_id": NODE_WATCHDOG,
        "watchdog_period_ms": 1000,
    }
    for c in api.get("/api/connections", params={"project_id": projeto_id}).json():
        if c["name"] == CONEXAO:
            divergente = {k: v for k, v in campos.items() if c.get(k) != v}
            if divergente:
                api.patch(f"/api/connections/{c['id']}", json=divergente).raise_for_status()
            return int(c["id"])
    r = api.post("/api/connections", json={"project_id": projeto_id, "name": CONEXAO, **campos})
    r.raise_for_status()
    return int(r.json()["id"])


def obter_tag(
    api: httpx.Client,
    conn_id: int,
    nome: str,
    node_id: str,
    direcao: str,
    eu: str,
    descricao: str,
) -> int:
    for t in api.get("/api/tags", params={"connection_id": conn_id}).json():
        if t["name"] == nome:
            if t["node_id"] != node_id or t["direction"] != direcao:
                api.patch(
                    f"/api/tags/{t['id']}", json={"node_id": node_id, "direction": direcao}
                ).raise_for_status()
            return int(t["id"])
    r = api.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": node_id,
            "direction": direcao,
            "data_type": "float",
            "eu": eu,
            "description": descricao,
        },
    )
    r.raise_for_status()
    return int(r.json()["id"])


def criar_tags(api: httpx.Client, conn_id: int) -> dict[str, int]:
    tags: dict[str, int] = {}
    for tag in CV_TAG.values():
        tags[tag] = obter_tag(
            api, conn_id, tag, f"ns={NS};s=Plant.CV.{tag}.PV", "r", "", f"CV {tag}"
        )
    for tag in DV_TAG.values():
        tags[tag] = obter_tag(
            api, conn_id, tag, f"ns={NS};s=Plant.DV.{tag}.PV", "r", "", f"DV {tag}"
        )
    for tag in MV_TAG.values():
        caminho = f"ns={NS};s=Plant.MV.{tag}.CMD"
        nome = f"{tag}-CMD"
        tags[nome] = obter_tag(api, conn_id, nome, caminho, "w", "%", f"Comando de {tag}")
        # Mesmo no, tag separada em direcao 'r': o opc-worker so assina tag 'r', e e dela
        # que sai o readback da MV (tracking em LOCAL + `u_applied` do solve).
        rb = MV_READBACK[tag]
        tags[rb] = obter_tag(api, conn_id, rb, caminho, "r", "%", f"Comando vigente de {tag}")
    for nome, caminho, eu, descricao in TAGS_CONTEXTO:
        tags[nome] = obter_tag(api, conn_id, nome, f"ns={NS};s={caminho}", "r", eu, descricao)
    return tags


def obter_flow(api: httpx.Client, projeto_id: int) -> int:
    for f in api.get("/api/flows", params={"project_id": projeto_id}).json():
        if f["name"] == FLOW:
            return int(f["id"])
    r = api.post("/api/flows", json={"project_id": projeto_id, "name": FLOW, "ts_seconds": TS_FLOW})
    r.raise_for_status()
    return int(r.json()["id"])


def main() -> None:
    api = login()
    projeto_id = obter_projeto(api)
    conn_id = obter_conexao(api, projeto_id)
    tags = criar_tags(api, conn_id)
    flow_id = obter_flow(api, projeto_id)

    grafo = montar_grafo(tags)
    r = api.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
    if r.status_code != 200:
        print(f"[!] PUT do grafo falhou: HTTP {r.status_code}", file=sys.stderr)
        print(json.dumps(r.json(), indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    avisos = r.json().get("warnings", [])

    r = api.post(f"/api/flows/{flow_id}/deploy")
    if r.status_code != 202:
        print(f"[!] Deploy falhou: HTTP {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)

    estado = ""
    for _ in range(60):
        estado = api.get(f"/api/flows/{flow_id}").json().get("desired_state", "")
        mpcs = api.get("/api/operate/mpcs").json()
        if any(m["flow_id"] == flow_id and m["block_id"] == BLOCO_MPC for m in mpcs):
            break
        time.sleep(1.0)

    print(
        json.dumps(
            {
                "project_id": projeto_id,
                "connection_id": conn_id,
                "flow_id": flow_id,
                "block_id": BLOCO_MPC,
                "ts_flow": TS_FLOW,
                "ts_mpc": TS_FLOW * MULTIPLICADOR,
                "desired_state": estado,
                "tags": tags,
                "warnings": avisos,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
