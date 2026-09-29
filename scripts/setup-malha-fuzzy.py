#!/usr/bin/env python3
"""Setup idempotente do demo MIMO do fuzzy_loop v2: projeto + conexão + flow
"TFS 2x2 acoplado <-> Fuzzy Malha multicanal" + usuário operador.

O grafo fecha DUAS malhas de controle num único bloco `fuzzy_loop` de `n_loops=2`
(SPEC_FUZZY v2 MIMO): o bloco lê `pv_1`/`pv_2` das saídas `y1`/`y2` da TFS e escreve
`out_1`/`out_2` nas duas MVs. Como o grafo não pode ter ciclo (RF-302), a realimentação
fecha pelo OPC (mesmo padrão do E2E-F4/ADR-022): `out_i -> opc_write -> opcsim ->
espelho -> opc_read -> TFS u_i`.

Executa via `uv run python scripts/setup-malha-fuzzy.py` (stack de 9 serviços subida:
`cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d`).
Idempotente: rodar 2x não duplica projeto/conexão/tags/flow/usuário; o grafo é sempre
reatualizado e o flow redeployado.

Retorno: resumo JSON em stdout (project_id, flow_id, bloco, URL da página MALHA).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / "deploy"
sys.path.insert(0, str(REPO_ROOT))

# Fonte canônica do endpoint do opcsim dentro da rede do compose (gateway) e da porta no
# host — mesma resolução que a suíte L2 usa (tests/e2e/conftest.py).
from tests.e2e.conftest import (  # noqa: E402
    OPCSIM_HOST,
    OPCSIM_HOST_PORT,
    _endpoint_na_rede,
)

if TYPE_CHECKING:
    from httpx import Client

PROJECT_NAME = "Fuzzy MIMO (malha)"
CONNECTION_NAME = "opcsim-mimo"
FLOW_NAME = "malha-fuzzy-mimo"
BLOCK_ID = "fm"
OPERATOR_USERNAME = "operador_e2e"
OPERATOR_PASSWORD = "OperadorE2E" + "#2026"  # mesma credencial dev do setup-l3.py
TS_FLOW = 1.0
FLL_PATH = REPO_ROOT / "scripts" / "fll" / "malha-mimo-2x2.fll"

# Node IDs do opcsim (tests/opcsim/src/opcsim/server.py): dois pares w/espelho float
# independentes — um por MV da planta 2x2.
NODE_W_FLOAT = "ns=2;s=sim.w.float"
NODE_MIRROR_FLOAT = "ns=2;s=sim.mirror.float"
NODE_W_FLOAT2 = "ns=2;s=sim.w.float2"
NODE_MIRROR_FLOAT2 = "ns=2;s=sim.mirror.float2"
# Watchdog no SEGUNDO par do opcsim: o primeiro pertence ao flow da L3 (ADR-009 revisado —
# watchdog é por flow, uma conexão pode ter vários).
WD_FROM = "ns=2;s=sim.watchdog.from_system_2"
WD_TO = "ns=2;s=sim.watchdog.to_system_2"


def _deploy_env() -> dict[str, str]:
    """Lê pares do `deploy/.env` sem exportar."""
    valores: dict[str, str] = {}
    arquivo = DEPLOY_DIR / ".env"
    if not arquivo.exists():
        return valores
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, _, valor = limpa.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


_DEPLOY = _deploy_env()


def _conf(nome: str, default: str) -> str:
    """Ambiente do processo vence; `deploy/.env` é o fallback; depois o default."""
    return os.environ.get(nome) or _DEPLOY.get(nome) or default


BASE = _conf("E2E_BASE_URL", "http://localhost:8080")
ADMIN_USER = _conf("E2E_ADMIN_USERNAME", _conf("OTTIMA_ADMIN_USERNAME", "admin"))
ADMIN_PASS = _conf("E2E_ADMIN_PASSWORD", _conf("OTTIMA_ADMIN_PASSWORD", ""))


def _porta_ocupada(host: str, porta: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex((host, porta)) == 0


def _garantir_opcsim() -> None:
    """opcsim standalone no host (a suíte L2 faz o mesmo): se a porta está livre, sobe um
    processo destacado com segurança `none` (a conexão do demo não usa certificado)."""
    if _porta_ocupada(OPCSIM_HOST, OPCSIM_HOST_PORT):
        print(f"[+] opcsim já ouvindo em {OPCSIM_HOST}:{OPCSIM_HOST_PORT}", file=sys.stderr)
        return
    print("[*] Subindo opcsim standalone...", file=sys.stderr)
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "opcsim",
            "--host",
            "0.0.0.0",
            "--port",
            str(OPCSIM_HOST_PORT),
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(60):
        if _porta_ocupada(OPCSIM_HOST, OPCSIM_HOST_PORT):
            print("[+] opcsim ouvindo", file=sys.stderr)
            return
        time.sleep(0.5)
    print("[!] opcsim não abriu a porta em 30 s", file=sys.stderr)
    sys.exit(1)


def _criar_tag(admin: Client, conn_id: int, nome: str, node_id: str, direcao: str) -> int:
    """Cria tag ou retorna existente (idempotente; corrige node_id divergente)."""
    r = admin.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": node_id,
            "direction": direcao,
            "data_type": "float",
        },
    )
    if r.status_code == 201:
        return int(r.json()["id"])
    if r.status_code == 409:
        r = admin.get(f"/api/tags?connection_id={conn_id}")
        if r.status_code == 200:
            for tag in r.json():
                if tag["name"] == nome:
                    return int(tag["id"])
    raise RuntimeError(f"Falha ao criar/recuperar tag {nome}: HTTP {r.status_code} {r.text}")


def _sopdt(k: float, tau1: float, tau2: float, theta: float) -> dict:
    return {
        "enabled": True,
        "kind": "sopdt",
        "params": {"K": k, "tau1": tau1, "tau2": tau2, "theta": theta},
    }


def _matriz_planta() -> list[list[dict]]:
    """Planta 2x2 acoplada: ganho diagonal 1.0, cruzado 0.4 (40% de interação)."""
    return [
        [_sopdt(1.0, 10.0, 3.0, 1.0), _sopdt(0.4, 12.0, 3.0, 2.0)],
        [_sopdt(0.4, 12.0, 3.0, 2.0), _sopdt(1.0, 10.0, 3.0, 1.0)],
    ]


def _grafo(tag_rb1: int, tag_rb2: int, tag_w1: int, tag_w2: int, fll: str) -> dict:
    def no(node_id: str, tipo: str, ordem: int, **config) -> dict:
        return {
            "id": node_id,
            "type": tipo,
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": ordem, **config},
        }

    def aresta(edge_id: str, src: str, src_h: str, dst: str, dst_h: str) -> dict:
        return {
            "id": edge_id,
            "source": src,
            "sourceHandle": src_h,
            "target": dst,
            "targetHandle": dst_h,
        }

    return {
        "nodes": [
            no("rb1", "opc_read", 1, tag_id=tag_rb1),
            no("rb2", "opc_read", 2, tag_id=tag_rb2),
            no("planta", "tfs", 3, matrix=_matriz_planta(), output_eu={"y1": "°C", "y2": "t/h"}),
            no(
                BLOCK_ID,
                "fuzzy_loop",
                4,
                label="Fuzzy Malha MIMO",
                n_loops=2,
                fll=fll,
                ke=0.05,
                kde=0.0,
                ku=0.9,
                tf_de=1.0,
                # Planta: MV1 = (SP1 - 0,4*SP2)/0,84 (simetrico no canal 2), OUT em [0, 100].
                # SP em [45, 95] mantem MV em ~[8, 92] % na caixa inteira: margem dos dois
                # lados. Em [40, 100] o canto SP1=40/SP2=100 ja da MV1 = 0 % (saturado).
                sp_hi_lim=95.0,
                sp_lo_lim=45.0,
                out_scale_lo=0.0,
                out_scale_hi=100.0,
                out_hi_lim=100.0,
                out_lo_lim=0.0,
            ),
            no("w1", "opc_write", 5, tag_id=tag_w1),
            no("w2", "opc_write", 6, tag_id=tag_w2),
        ],
        "edges": [
            aresta("e1", "rb1", "out", "planta", "u1"),
            aresta("e2", "rb2", "out", "planta", "u2"),
            aresta("e3", "planta", "y1", BLOCK_ID, "pv_1"),
            aresta("e4", "planta", "y2", BLOCK_ID, "pv_2"),
            aresta("e5", BLOCK_ID, "out_1", "w1", "in"),
            aresta("e6", BLOCK_ID, "out_2", "w2", "in"),
        ],
    }


def _falha(msg: str, r: httpx.Response) -> None:
    print(f"[!] {msg}: HTTP {r.status_code} {r.text}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    _garantir_opcsim()
    fll = FLL_PATH.read_text(encoding="utf-8")

    with httpx.Client(base_url=BASE, timeout=20) as admin:
        r = admin.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        if r.status_code != 200:
            _falha("Falha na autenticação", r)
        admin.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        print(f"[+] Autenticado como {ADMIN_USER}", file=sys.stderr)

        # 1. Projeto ativo (ADR-017: projeto ativo único — ativar este desativa outro).
        r = admin.get("/api/projects")
        if r.status_code != 200:
            _falha("Falha ao listar projetos", r)
        projeto_id = next((int(p["id"]) for p in r.json() if p["name"] == PROJECT_NAME), None)
        if projeto_id is None:
            r = admin.post("/api/projects", json={"name": PROJECT_NAME})
            if r.status_code != 201:
                _falha("Falha ao criar projeto", r)
            projeto_id = int(r.json()["id"])
            print(f"[+] Projeto criado: id={projeto_id}", file=sys.stderr)
        r = admin.post(f"/api/projects/{projeto_id}/activate")
        if r.status_code != 200:
            _falha("Falha ao ativar projeto", r)
        print(f"[+] Projeto ativo: id={projeto_id}", file=sys.stderr)

        # 2. Conexão com o opcsim.
        r = admin.get(f"/api/connections?project_id={projeto_id}")
        if r.status_code != 200:
            _falha("Falha ao listar conexões", r)
        conn_id = next((int(c["id"]) for c in r.json() if c["name"] == CONNECTION_NAME), None)
        if conn_id is None:
            r = admin.post(
                "/api/connections",
                json={
                    "project_id": projeto_id,
                    "name": CONNECTION_NAME,
                    "endpoint": _endpoint_na_rede(),
                    "security_policy": "none",
                    "security_mode": "none",
                    "auth_mode": "anonymous",
                },
            )
            if r.status_code != 201:
                _falha("Falha ao criar conexão", r)
            conn_id = int(r.json()["id"])
            print(f"[+] Conexão criada: id={conn_id}", file=sys.stderr)
        # Endpoint divergente (ex.: opcsim movido de porta para isolar de outra sessão):
        # reconcilia via PATCH — idempotente de verdade.
        endpoint_alvo = _endpoint_na_rede()
        r = admin.get(f"/api/connections/{conn_id}")
        if r.status_code == 200 and r.json().get("endpoint") != endpoint_alvo:
            r = admin.patch(f"/api/connections/{conn_id}", json={"endpoint": endpoint_alvo})
            if r.status_code != 200:
                _falha("Falha ao atualizar endpoint da conexão", r)
            print(f"[+] Endpoint reconciliado: {endpoint_alvo}", file=sys.stderr)
        # `/api/connections/{id}/health` não existe (o setup-l3 ainda o consulta — deriva
        # pré-existente); a fonte real é `/api/health/workers` (F5), com o estado da
        # conexão no bloco do opc-worker.
        for _ in range(60):
            r = admin.get("/api/health/workers")
            if r.status_code == 200:
                conns = r.json().get("opc_worker", {}).get("connections", {})
                if conns.get(str(conn_id), {}).get("state") == "up":
                    break
            time.sleep(1.0)
        else:
            print("[!] Conexão não ficou up em 60 s", file=sys.stderr)
            sys.exit(1)
        print("[+] Conexão operacional", file=sys.stderr)

        # 3. Tags: dois pares MV (escrita) / readback (espelho).
        tag_w1 = _criar_tag(admin, conn_id, "mv1-write", NODE_W_FLOAT, "w")
        tag_rb1 = _criar_tag(admin, conn_id, "mv1-readback", NODE_MIRROR_FLOAT, "r")
        tag_w2 = _criar_tag(admin, conn_id, "mv2-write", NODE_W_FLOAT2, "w")
        tag_rb2 = _criar_tag(admin, conn_id, "mv2-readback", NODE_MIRROR_FLOAT2, "r")
        print(f"[+] Tags: w1={tag_w1} rb1={tag_rb1} w2={tag_w2} rb2={tag_rb2}", file=sys.stderr)

        # 4. Flow + grafo (PUT sempre: idempotente e garante a config vigente).
        r = admin.get(f"/api/flows?project_id={projeto_id}")
        if r.status_code != 200:
            _falha("Falha ao listar flows", r)
        flow_id = next((int(f["id"]) for f in r.json() if f["name"] == FLOW_NAME), None)
        if flow_id is None:
            r = admin.post(
                "/api/flows",
                json={"project_id": projeto_id, "name": FLOW_NAME, "ts_seconds": TS_FLOW},
            )
            if r.status_code != 201:
                _falha("Falha ao criar flow", r)
            flow_id = int(r.json()["id"])
            print(f"[+] Flow criado: id={flow_id}", file=sys.stderr)
        r = admin.put(
            f"/api/flows/{flow_id}",
            json={
                "graph_json": _grafo(tag_rb1, tag_rb2, tag_w1, tag_w2, fll),
                "watchdog_enabled": True,
                "watchdog_connection_id": conn_id,
                "watchdog_read_node_id": WD_TO,
                "watchdog_write_node_id": WD_FROM,
                "watchdog_period_ms": 1000,
            },
        )
        if r.status_code != 200:
            _falha("Falha ao atualizar grafo", r)
        print("[+] Grafo atualizado (TFS 2x2 + fuzzy_loop n_loops=2)", file=sys.stderr)

        # 5. Deploy e espera do runtime.
        r = admin.post(f"/api/flows/{flow_id}/deploy")
        if r.status_code != 202:
            _falha("Falha no deploy", r)
        # `GET /api/flows/{id}` devolve `desired_state`, não o estado vivo (o setup-l3
        # consulta um campo `state` que não existe — deriva pré-existente); a autoridade
        # do runtime é `/api/health/workers` -> flow_runtime.flows (F5).
        for _ in range(60):
            r = admin.get("/api/health/workers")
            if r.status_code == 200:
                flows = r.json().get("flow_runtime", {}).get("flows", {})
                estado = flows.get(str(flow_id))
                if isinstance(estado, dict) and estado.get("state") == "running":
                    break
                if isinstance(estado, dict) and estado.get("state") == "failed":
                    print(f"[!] Flow falhou no deploy: {estado}", file=sys.stderr)
                    sys.exit(1)
            time.sleep(1.0)
        else:
            print("[!] Flow não ficou running em 60 s", file=sys.stderr)
            sys.exit(1)
        print("[+] Flow running", file=sys.stderr)

        # 6. Usuário operador (mesmo nome/senha do ambiente L3 — idempotente).
        r = admin.get("/api/users")
        existe = r.status_code == 200 and any(u["username"] == OPERATOR_USERNAME for u in r.json())
        if not existe:
            r = admin.post(
                "/api/users",
                json={
                    "username": OPERATOR_USERNAME,
                    "name": "Operador E2E",
                    "password": OPERATOR_PASSWORD,
                    "role": "operator",
                },
            )
            if r.status_code != 201:
                _falha("Falha ao criar operador", r)
            print(f"[+] Operador criado: {OPERATOR_USERNAME}", file=sys.stderr)
        else:
            print(f"[+] Operador existente: {OPERATOR_USERNAME}", file=sys.stderr)

        # 7. Confirma a descoberta da malha multicanal.
        r = admin.get("/api/operate/loop")
        malhas = [no for no in r.json() if no["flow_id"] == flow_id] if r.status_code == 200 else []
        if not any(no["block_id"] == BLOCK_ID and no["n_loops"] == 2 for no in malhas):
            print(f"[!] {BLOCK_ID} não aparece como malha de 2 canais: {malhas}", file=sys.stderr)
            sys.exit(1)
        print("[+] Malha descoberta em /api/operate/loop com n_loops=2", file=sys.stderr)

        print(
            json.dumps(
                {
                    "project_id": projeto_id,
                    "connection_id": conn_id,
                    "flow_id": flow_id,
                    "block_id": BLOCK_ID,
                    "operator": OPERATOR_USERNAME,
                    "malha_url": f"{BASE}/operacao/loop?flow={flow_id}&bloco={BLOCK_ID}",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
